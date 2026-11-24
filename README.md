# StatementSense

Bank statement PDFs in, lending report out. The plan lives in `../plan.md`.

## Setup

```
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python -m pytest -q
```

## Making a report

```
.venv/Scripts/python cli.py statement.pdf                      # one statement
.venv/Scripts/python cli.py jan-oct.pdf nov.pdf --out out/x.pdf  # several statements, one borrower
.venv/Scripts/python cli.py locked.pdf --password 1234
.venv/Scripts/python cli.py statement.pdf --check-only         # just read + balance check
```

Writes the report PDF and a JSON summary (for the website/WhatsApp later). A statement whose
balances don't all add up is left out with a message, never shown with wrong numbers.

## How it works

`analyser/engine.py` unlock → detect bank → read (`readers/generic.py` + profile) → balance check
`analyser/analysis.py` combine statements → enrich (`enrich/`: mode, cheque no, party, lender) →
sections (`sections/`: returns, cashflow, parties, loans, recurring, cheques, modes, flags, checks)
`analyser/report/` HTML template + charts → PDF via headless Chromium

Lenders list: `analyser/data/lenders.yaml` (add new lenders there).

## Private files (never committed)

- `tests/statements/<bank>/`: real statements, one folder per bank profile id (axis, cub, federal, ...); `passwords.txt`: `filename.pdf = password`
- `tests/expected/`: expected totals per statement
- `tests/reports/`: ProAnalyser reports for comparison
- `tests/private/`: tests that use real borrower data
- `out/`: generated reports

## Adding a statement or a new bank

1. Put the PDF in `tests/statements/<bank>/` (and its password in `passwords.txt`).
2. Run `.venv/Scripts/python tools/make_expected.py <file>.pdf`
   - **Balance check passes:** it writes `tests/expected/<file>.yaml`. Compare the printed
     opening balance, closing balance and transaction count with the statement itself.
   - **Balance check fails, or the bank shows as `unknown`:** the bank needs a profile.
3. A new bank's profile is `analyser/readers/profiles/<bank>.yaml`. Usually it only needs:
   ```yaml
   id: sbi
   name: State Bank of India
   detect:
     header: ['\bSBIN0\d{6}\b']      # found above the transaction table on page 1
   reader:
     columns:                         # only if a heading isn't recognised
       'txn remarks': description
     description_join: auto           # only if words are cut mid-way in narrow columns
   details:
     holder: '...'                    # only if the holder's name isn't found
   ```
4. Make a report and look at it: `.venv/Scripts/python cli.py tests/statements/<bank>/<file>.pdf`
5. Run `.venv/Scripts/python -m pytest -q`. Every statement in the library must still pass.

## Telegram bot (front door for now)

People send statement PDFs to a Telegram bot and get the report PDF back. It uses `analyser/service.py`
(the same two calls a website or WhatsApp bot will use) and long polling, so it needs no public address.

1. On Telegram, talk to **@BotFather**, send `/newbot`, copy the token.
2. Copy `.env.example` to `.env` and put the token in `TELEGRAM_BOT_TOKEN`.
3. `.venv/Scripts/python run_bot.py`, then send `/myid` to your bot and put the number in `ALLOWED_USERS` in `.env`
   (comma separated for several people). With none listed, nobody can use the bot. Restart the bot.
4. In the chat: send the PDF(s) of one borrower (it asks for a password if needed), then `/report`.

Statements live in a temp folder only until the report is sent; passwords are never stored and their
message is deleted; the log has ids and events only. Telegram bot chats are not end-to-end encrypted,
so tell borrowers where their statement goes. Telegram lets a bot download files up to 20 MB.
The bot runs only while `run_bot.py` is running: for 24/7 it needs an always-on machine (a small server).
