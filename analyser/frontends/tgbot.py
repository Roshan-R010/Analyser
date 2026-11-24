"""Telegram front door: people send statement PDFs, the bot sends back the report PDF.

Chat flow
    /start            what to do
    send PDF(s)       one or more statements of ONE borrower; asks for the password if a file has one
    /report           makes the report from the statements sent so far
    /clear            forget everything sent so far
    /myid             shows your Telegram id (to be added to ALLOWED_USERS)

Safety
    * Only Telegram ids in ALLOWED_USERS may use it. With none listed, nobody can.
    * Statements are kept in a private temp folder only until the report is sent (or /clear), then deleted.
    * Passwords are used once to open the file, never stored, and the message that carried it is deleted.
    * The log holds ids and events, never statement contents.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from logging.handlers import RotatingFileHandler
from dataclasses import dataclass, field
from pathlib import Path

from telegram import Update
from telegram.error import NetworkError, TimedOut
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from analyser import service

log = logging.getLogger("tgbot")

MAX_FILE_MB = 20  # Telegram lets bots download up to 20 MB
MAX_FILES = 2  # statements per borrower in one report
MAX_PASSWORD_TRIES = 3
SEND_TIMEOUT = 180  # seconds to upload a report: a 2-3 MB PDF over a slow line needs far more than the default 5-20
SEND_TRIES = 2
BUSY = asyncio.Semaphore(1)  # reading and printing are heavy: one at a time, everyone else waits their turn

HELP = (
    "StatementSense reads bank statements and makes a lending report.\n\n"
    "Send me bank statement PDFs of one borrower (up to 2), then send /report.\n\n"
    "If a statement has a password I will ask for it. I use it once and delete your message.\n"
    "/clear starts again · /myid shows your Telegram id"
)


# ---------------------------------------------------------------- settings

def parse_allowed(text: str | None) -> set[int]:
    """'123, 456' -> {123, 456}. Anything that is not a number is ignored."""
    return {int(x) for x in (text or "").replace(";", ",").split(",") if x.strip().lstrip("-").isdigit()}


def is_allowed(user_id: int, allowed: set[int]) -> bool:
    return user_id in allowed


def load_env_file(path: Path) -> None:
    """KEY=value lines from a .env file into the environment (existing variables win)."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# ---------------------------------------------------------------- one person's session

@dataclass
class Session:
    folder: Path
    files: list[service.FileOutcome] = field(default_factory=list)  # statements that read fine
    waiting: Path | None = None  # a password-protected file waiting for its password
    tries: int = 0

    def close(self) -> None:
        shutil.rmtree(self.folder, ignore_errors=True)


def session_of(context: ContextTypes.DEFAULT_TYPE) -> Session:
    s = context.user_data.get("session")
    if s is None:
        s = context.user_data["session"] = Session(folder=Path(tempfile.mkdtemp(prefix="stmt_")))
    return s


def end_session(context: ContextTypes.DEFAULT_TYPE) -> None:
    s = context.user_data.pop("session", None)
    if s:
        s.close()


# ---------------------------------------------------------------- guards

async def allowed(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if user and is_allowed(user.id, context.application.bot_data["allowed"]):
        return True
    log.info("refused user %s", user.id if user else "?")
    if update.effective_message:
        await update.effective_message.reply_text(
            f"Sorry, this bot is private. Ask its owner to add your id: {user.id if user else '?'}")
    return False


# ---------------------------------------------------------------- commands

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await allowed(update, context):
        await update.message.reply_text(HELP)


async def myid(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your Telegram id: {update.effective_user.id}")


async def clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await allowed(update, context):
        end_session(context)
        await update.message.reply_text("Cleared. Send the statements when you are ready.")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await allowed(update, context):
        return
    s = session_of(context)
    if s.waiting:
        await update.message.reply_text("I am still waiting for the password of the last statement.")
        return
    if not s.files:
        await update.message.reply_text("Send me at least one statement PDF first.")
        return
    await update.message.reply_text(f"Making the report from {len(s.files)} statement(s). This can take a minute…")
    await update.effective_chat.send_action(ChatAction.UPLOAD_DOCUMENT)
    out = s.folder / "report.pdf"
    delivered = False
    try:
        async with BUSY:
            result = await asyncio.to_thread(service.make_report, [f.loaded for f in s.files], out)
        delivered = await _send_report(update, result)
        if not delivered:
            await update.message.reply_text(
                "The report is ready but Telegram did not take the upload (a slow or unstable connection). "
                "Send /report to try again. Your statements are kept until it goes through or you send /clear.")
    except Exception:
        log.exception("report failed for %s", update.effective_user.id)
        await update.message.reply_text("Sorry, something went wrong while making the report. Nothing was saved.")
        delivered = True  # nothing to retry: start clean
    finally:
        if delivered:
            end_session(context)  # the statements are deleted as soon as the report is sent


async def _send_report(update: Update, result: service.ReportResult) -> bool:
    """Upload the report, patiently. False if Telegram still would not take it."""
    for attempt in range(1, SEND_TRIES + 1):
        try:
            with result.pdf.open("rb") as fh:
                await update.message.reply_document(
                    fh, filename="Statement analysis.pdf", caption=result.summary[:1000],
                    read_timeout=SEND_TIMEOUT, write_timeout=SEND_TIMEOUT, connect_timeout=30, pool_timeout=30)
            log.info("report sent to %s", update.effective_user.id)
            return True
        except (TimedOut, NetworkError):
            log.warning("upload to %s timed out (try %d of %d)", update.effective_user.id, attempt, SEND_TRIES)
    return False


# ---------------------------------------------------------------- statements and passwords

async def _read(update: Update, context: ContextTypes.DEFAULT_TYPE, path: Path, password: str | None) -> None:
    s = session_of(context)
    async with BUSY:
        outcome = await asyncio.to_thread(service.read_file, path, password)
    if outcome.status == service.NEEDS_PASSWORD:
        s.waiting, s.tries = path, 0
        await update.message.reply_text(f"{outcome.name} needs a password. Send it as your next message "
                                        "(I will delete that message).")
    elif outcome.status == service.WRONG_PASSWORD:
        s.tries += 1
        if s.tries >= MAX_PASSWORD_TRIES:
            s.waiting = None
            path.unlink(missing_ok=True)
            await update.message.reply_text(f"{outcome.name}: too many wrong passwords, I dropped it. Send it again to retry.")
        else:
            await update.message.reply_text("That password did not work. Try again.")
    else:
        s.waiting = None
        if outcome.ok:
            s.files.append(outcome)
            await update.message.reply_text(f"✓ {outcome.name}\n{outcome.message}\n\nSend more statements of the same "
                                            "borrower, or /report.")
        else:
            path.unlink(missing_ok=True)
            await update.message.reply_text(f"✕ {outcome.name}\n{outcome.message}")


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await allowed(update, context):
        return
    doc = update.message.document
    s = session_of(context)
    if s.waiting:
        await update.message.reply_text("Send the password for the last statement first (or /clear).")
        return
    if (doc.mime_type or "") != "application/pdf" and not (doc.file_name or "").lower().endswith(".pdf"):
        await update.message.reply_text("Please send the statement as a PDF file.")
        return
    if doc.file_size and doc.file_size > MAX_FILE_MB * 1024 * 1024:
        await update.message.reply_text(f"That file is over {MAX_FILE_MB} MB, which Telegram does not let me download.")
        return
    if len(s.files) >= MAX_FILES:
        await update.message.reply_text(f"That is {MAX_FILES} statements already. Send /report.")
        return
    await update.effective_chat.send_action(ChatAction.TYPING)
    path = s.folder / f"{len(s.files) + 1}_{Path(doc.file_name or 'statement.pdf').name}"
    await (await doc.get_file()).download_to_drive(path)
    await _read(update, context, path, None)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await allowed(update, context):
        return
    s = session_of(context)
    if not s.waiting:
        await update.message.reply_text(HELP)
        return
    password = update.message.text.strip()
    try:
        await update.message.delete()  # do not leave the password in the chat
    except Exception:
        pass
    await _read(update, context, s.waiting, password)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("unhandled error", exc_info=context.error)  # no statement data is ever in an exception message


# ---------------------------------------------------------------- start-up

def build_app(token: str, allowed_ids: set[int]) -> Application:
    app = (Application.builder().token(token)
           .read_timeout(60).write_timeout(60).connect_timeout(30).pool_timeout(30)  # downloads of statements
           .build())
    app.bot_data["allowed"] = allowed_ids
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    app.add_handler(CommandHandler("myid", myid))
    app.add_handler(CommandHandler("clear", clear))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)
    return app


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    load_env_file(root / ".env")
    (root / "logs").mkdir(exist_ok=True)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(message)s",
        handlers=[logging.StreamHandler(),  # the terminal, and a file others can read:
                  RotatingFileHandler(root / "logs" / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")])
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its URLs contain the bot token
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Set TELEGRAM_BOT_TOKEN (in .env). Make a bot with @BotFather on Telegram to get one.")
        return 2
    ids = parse_allowed(os.environ.get("ALLOWED_USERS"))
    if not ids:
        print("ALLOWED_USERS is empty: nobody can use the bot yet. Start it, send /myid to it, "
              "then put that number in .env as ALLOWED_USERS=...")
    print(f"Bot running. {len(ids)} allowed user(s). Press Ctrl+C to stop.")
    build_app(token, ids).run_polling(drop_pending_updates=True)
    return 0
