"""The Telegram bot's chat logic, driven with stand-in Telegram objects (no network, no token)."""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from telegram.error import TimedOut

from analyser.frontends import tgbot
from conftest import find_statement, load_passwords


def test_allowed_users_parsing_and_check():
    assert tgbot.parse_allowed("1, 22;x,-5") == {1, 22, -5}
    assert tgbot.parse_allowed("") == set() and tgbot.parse_allowed(None) == set()
    assert tgbot.is_allowed(22, {1, 22}) and not tgbot.is_allowed(3, {1, 22}) and not tgbot.is_allowed(3, set())


def test_env_file_does_not_override_real_environment(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# c\nTG_A=one\nTG_B="two"\nTG_C = three \n', encoding="utf-8")
    monkeypatch.setenv("TG_A", "real")
    monkeypatch.delenv("TG_B", raising=False)
    monkeypatch.delenv("TG_C", raising=False)
    tgbot.load_env_file(f)
    import os
    assert (os.environ["TG_A"], os.environ["TG_B"], os.environ["TG_C"]) == ("real", "two", "three")
    tgbot.load_env_file(tmp_path / "missing")  # no file is fine


# ---------------------------------------------------------------- a fake chat

class Chat:
    """One user's chat: records what the bot says, feeds it files and text."""

    def __init__(self, user_id=7, allowed=(7,)):
        self.said, self.documents, self.deleted = [], [], []
        self.user_data = {}
        self.app = SimpleNamespace(bot_data={"allowed": set(allowed)})
        self.user = SimpleNamespace(id=user_id)

    send_failures = 0  # how many uploads to fail with a timeout before one works

    def _document(self, fh, **k):
        if self.send_failures:
            self.send_failures -= 1
            raise TimedOut("Timed out")
        self.documents.append((fh.read(4), k))

    def _update(self, text=None, document=None):
        msg = MagicMock()
        msg.text, msg.document = text, document
        msg.reply_text = AsyncMock(side_effect=lambda t, **k: self.said.append(t))
        msg.reply_document = AsyncMock(side_effect=self._document)
        msg.delete = AsyncMock(side_effect=lambda: self.deleted.append(text))
        chat = SimpleNamespace(send_action=AsyncMock())
        return SimpleNamespace(message=msg, effective_message=msg, effective_user=self.user, effective_chat=chat)

    @property
    def context(self):
        return SimpleNamespace(user_data=self.user_data, application=self.app)

    def run(self, handler, **kw):
        asyncio.run(handler(self._update(**kw), self.context))

    def send_pdf(self, path: Path, name=None, size=1000, mime="application/pdf"):
        async def download(dest):
            shutil.copy(path, dest)
        doc = SimpleNamespace(file_name=name or path.name, mime_type=mime, file_size=size,
                              get_file=AsyncMock(return_value=SimpleNamespace(download_to_drive=download)))
        self.run(tgbot.on_document, document=doc)


def need(name):
    p = find_statement(name)
    if p is None:
        pytest.skip(f"{name} not present")
    return p


# ---------------------------------------------------------------- behaviour

def test_stranger_is_refused_and_told_their_id():
    c = Chat(user_id=99, allowed=(7,))
    c.run(tgbot.on_text, text="hello")
    c.run(tgbot.start)
    assert all("private" in s and "99" in s for s in c.said) and len(c.said) == 2


def test_nobody_allowed_until_configured():
    c = Chat(user_id=7, allowed=())
    c.run(tgbot.start)
    assert "private" in c.said[0]


def test_myid_works_for_anyone():
    c = Chat(user_id=42, allowed=())
    c.run(tgbot.myid)
    assert "42" in c.said[0]


def test_report_before_any_statement_and_clear():
    c = Chat()
    c.run(tgbot.report)
    assert "at least one" in c.said[0]
    c.run(tgbot.clear)
    assert "Cleared" in c.said[-1]


def test_rejects_non_pdf_and_oversize(tmp_path):
    c = Chat()
    f = tmp_path / "x.png"
    f.write_bytes(b"x")
    c.send_pdf(f, name="photo.png", mime="image/png")
    c.send_pdf(f, name="big.pdf", size=25 * 1024 * 1024)
    assert "PDF" in c.said[0] and "20 MB" in c.said[1]
    tgbot.end_session(c.context)


def test_a_junk_pdf_is_refused_and_deleted(tmp_path):
    c = Chat()
    f = tmp_path / "junk.pdf"
    f.write_bytes(b"not a pdf at all")
    c.send_pdf(f)
    session = c.user_data["session"]
    assert "✕" in c.said[-1] and not session.files and not any(session.folder.iterdir())
    tgbot.end_session(c.context)
    assert not session.folder.exists()


def test_statement_then_report_sends_pdf_and_deletes_everything():
    c = Chat()
    c.send_pdf(need("cub1.pdf"))
    assert "✓" in c.said[-1] and "balance" in c.said[-1]
    folder = c.user_data["session"].folder
    c.run(tgbot.report)
    assert c.documents and c.documents[0][0] == b"%PDF"
    assert "Checks:" in c.documents[0][1]["caption"] and "SIRAJ MILK AGENCY" in c.documents[0][1]["caption"]
    assert not folder.exists() and "session" not in c.user_data  # statements are gone once the report is sent


def test_password_flow_wrong_then_right_and_message_deleted():
    path = need("KVB.pdf")
    pw = load_passwords().get("KVB.pdf")
    if not pw:
        pytest.skip("no password for KVB.pdf")
    c = Chat()
    c.send_pdf(path)
    assert "password" in c.said[-1]
    c.run(tgbot.report)
    assert "waiting for the password" in c.said[-1]
    c.run(tgbot.on_text, text="wrong")
    assert "did not work" in c.said[-1] and c.deleted == ["wrong"]
    c.run(tgbot.on_text, text=pw)
    assert "✓" in c.said[-1] and c.deleted == ["wrong", pw]
    assert not c.user_data["session"].waiting
    tgbot.end_session(c.context)


def test_three_wrong_passwords_drop_the_file():
    path = need("KVB.pdf")
    c = Chat()
    c.send_pdf(path)
    for _ in range(tgbot.MAX_PASSWORD_TRIES):
        c.run(tgbot.on_text, text="nope")
    s = c.user_data["session"]
    assert "too many" in c.said[-1] and s.waiting is None and not any(s.folder.iterdir())
    tgbot.end_session(c.context)


def test_a_second_statement_waits_for_the_password_first():
    c = Chat()
    c.send_pdf(need("KVB.pdf"))
    c.send_pdf(need("cub1.pdf"))
    assert "password" in c.said[-1] and not c.user_data["session"].files
    tgbot.end_session(c.context)


def test_at_most_six_statements_per_borrower():
    c = Chat()
    for i in range(tgbot.MAX_FILES + 1):
        c.send_pdf(need("cub1.pdf"), name=f"{i}.pdf")
    s = c.user_data["session"]
    assert tgbot.MAX_FILES == 6 and len(s.files) == 6 and "6 statements already" in c.said[-1]
    tgbot.end_session(c.context)


def test_one_job_at_a_time():
    assert tgbot.BUSY._value == 1


def test_slow_upload_is_retried_and_uses_long_timeouts():
    c = Chat()
    c.send_pdf(need("cub1.pdf"))
    c.send_failures = 1  # the first upload times out, the second works
    c.run(tgbot.report)
    assert len(c.documents) == 1 and c.documents[0][1]["write_timeout"] >= 120
    assert "session" not in c.user_data


def test_upload_that_never_works_keeps_the_statements_for_a_retry():
    c = Chat()
    c.send_pdf(need("cub1.pdf"))
    c.send_failures = 99
    c.run(tgbot.report)
    assert not c.documents and "try again" in c.said[-1]
    s = c.user_data["session"]
    assert len(s.files) == 1 and s.folder.exists()  # kept, so /report can try again
    c.send_failures = 0
    c.run(tgbot.report)
    assert len(c.documents) == 1 and "session" not in c.user_data


def test_app_builds_and_main_refuses_without_a_token(monkeypatch, tmp_path):
    """Start-up code that tests would otherwise never touch (a missing import broke it once)."""
    app = tgbot.build_app("123:abc", {1})
    assert sum(len(v) for v in app.handlers.values()) >= 6 and app.bot_data["allowed"] == {1}
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setattr(tgbot, "load_env_file", lambda path: None)
    assert tgbot.main() == 2
