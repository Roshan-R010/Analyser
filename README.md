# Statement Analyser

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

- `tests/statements/`: real statements; `passwords.txt`: `filename.pdf = password`
- `tests/expected/`: expected totals per statement
- `tests/reports/`: ProAnalyser reports for comparison
- `tests/private/`: tests that use real borrower data
- `out/`: generated reports

## Adding a statement or a new bank

1. Put the PDF in `tests/statements/` (and its password in `passwords.txt`).
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
4. Make a report and look at it: `.venv/Scripts/python cli.py tests/statements/<file>.pdf`
5. Run `.venv/Scripts/python -m pytest -q`. Every statement in the library must still pass.
