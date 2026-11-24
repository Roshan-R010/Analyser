"""Mark loan payments and disbursements, and who the lender is.

Three ways an entry becomes a loan entry:
1. The party or description matches a known lender (analyser/data/lenders.yaml).
2. The party's name says it lends: "... FINANCE", "... FINANCIERS", "... CHITS", "... NIDHI"
   (private finance companies and chit funds that are on no list).
3. The description says it: "HAND LOAN", "LOAN REPAY", "EMI", "DISBURSEMENT", "GOLD LOAN".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from analyser.enrich import modes as M
from analyser.model import Transaction

LENDERS_FILE = Path(__file__).resolve().parent.parent / "data" / "lenders.yaml"

PRIVATE_FINANCE = re.compile(r"FINANCE|FINANC|FINANCIERS?|FINCORP|FINSERV|FINVEST|CREDITS?\b|LENDERS?|"
                             r"\bFUNDS?\b|CAPITALS?\b|INVESTMENTS?\b|LEASING|MICROFIN|GRAMEEN|GRAMIN|\bKGFS\b", re.I)
CHIT = re.compile(r"\bCHITS?\b|CHITTY|CHITFUND|\bKURI\b|\bNIDHI\b|BENEFIT\s*FUND", re.I)
HAND_LOAN = re.compile(r"hand\s*loan|handloan|h/?loan\b|loan\s*return|loanreturn", re.I)
GOLD_LOAN = re.compile(r"gold\s*loan|goldloan|\bjewel\s*loan|\bjl\s*(int|repay|cl)", re.I)
BANK_LOAN = re.compile(r"\b(loan|ln)\s*(repay|recovery|rec\b|emi|instal|a/?c|account|int)|(?<![a-z])emi(?![a-z])|"
                       r"\bloan\s*(disb|disbursement)|\bdisbursement\s*credit|\bdisb\b|\bod\s*renewal", re.I)
DISBURSEMENT = re.compile(r"disburs|\bdisb\b|loan\s*credit|loan\s*a/?c\s*cr", re.I)
# The bank's own loan account debited for an EMI: "ABC012345678901_EMI_21-09-2026"
LOAN_ACCOUNT_EMI = re.compile(r"\b([A-Z]{2,5}\d{6,})[\s_\-/]*EMI(?![A-Z])", re.I)
# An auto-debit "installment" that names no lender: "ACH-DR-INSTALLMENT- 0000AAAA1111..."
UNNAMED_INSTALLMENT = re.compile(r"\binstal+ment\b|(?<![a-z])emi(?![a-z])", re.I)
# Payment companies that collect EMIs for lenders through a mandate (the lender isn't named)
COLLECTION_AGENTS = re.compile(r"RAZORPAY|CASHFREE|BILLDESK|DIGIO|PAYU|TECHPROCESS|\bTPSL\b|EASEBUZZ|"
                               r"CCAVENUE|PAYTM\s*PAYMENTS|JUSPAY|SETU\b|ZWITCH|ENACH", re.I)
MANDATE_REF = re.compile(r"\b[A-Z]{4}[A-Z0-9]{2}\d{10,}\b")  # UMRN-style, e.g. UTIBDE01111110202606
# Not lenders even though the words look like it
NOT_LENDER = re.compile(r"SAFE\s*GOLD|MUTUAL\s*FUND|\bSIP\b|INSURANCE|\bLIC\s*OF\s*INDIA|PREMIUM", re.I)


@cache
def _bank_names() -> dict[str, str]:
    from analyser.profiles import load_profiles
    return {p.id: p.name for p in load_profiles()}


def _own_bank(t: Transaction) -> str:
    return _bank_names().get(t.bank, (t.bank or "Bank").upper())


@dataclass(frozen=True)
class Lender:
    name: str
    type: str
    match: tuple[str, ...]


@cache
def known_lenders(path: Path = LENDERS_FILE) -> tuple[Lender, ...]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    return tuple(Lender(d["name"], d["type"], tuple(m.upper() for m in d["match"])) for d in data)


def _squash(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (text or "").upper())


def identify(t: Transaction) -> tuple[str, str]:
    """(lender name, lender type) or ('', '')."""
    if t.mode in (M.CHARGES, M.RETURN, M.INTEREST, M.CASH) or t.party_key in ("_SELF",):
        return "", ""
    party = t.party_clean if not t.party_key.startswith("_") else ""
    if NOT_LENDER.search(party) or NOT_LENDER.search(t.description or ""):
        return "", ""
    squashed_party = _squash(party)
    # The whole description is only searched for mandates and bill payments: elsewhere it
    # also names the counterparty's bank ("…/Ravi M/…/ESAF SMALL FINANCE B" is not a loan).
    squashed_desc = _squash(t.description) if t.mode in (M.ECS, M.BILLPAY) else ""
    for lender in known_lenders():
        if any(m in squashed_party or (squashed_desc and m in squashed_desc) for m in lender.match):
            return lender.name, lender.type
    desc = t.description or ""
    # The statement's own bank debiting one of its loan accounts
    m = LOAN_ACCOUNT_EMI.search(desc)
    if m and t.debit:
        return f"{_own_bank(t)} loan a/c …{m.group(1)[-4:]}", "Bank"
    # An auto-debit (ECS/NACH/ACH) to a bank is a loan or card repayment to that bank
    if t.mode == M.ECS and t.debit and party and re.search(r"\bBANK\b", party, re.I):
        return party, "Bank"
    # A mandate collected by a payment company: one loan per mandate reference
    if t.mode == M.ECS and t.debit and COLLECTION_AGENTS.search(party or desc):
        ref = MANDATE_REF.search(desc)
        agent = COLLECTION_AGENTS.search(party or desc).group(0).title()
        return f"Auto-debit via {agent}" + (f" (mandate {ref.group(0)})" if ref else ""), \
            "Lender not named"
    if t.mode == M.ECS and t.debit and not party and UNNAMED_INSTALLMENT.search(desc):
        return "Auto-debit installment", "Lender not named"
    if HAND_LOAN.search(t.description or ""):
        return (party or "Hand loan"), "Hand loan"
    if GOLD_LOAN.search(t.description or ""):
        return (party or f"{t.bank.upper()} gold loan"), "Gold loan"
    if party and CHIT.search(party):
        return party, "Chit fund"
    if party and PRIVATE_FINANCE.search(party):
        return party, "Private finance"
    if BANK_LOAN.search(t.description or "") and (t.debit or DISBURSEMENT.search(t.description or "")):
        return (party or f"{t.bank.upper()} loan"), "Bank"
    return "", ""


def assign_lenders(transactions: list[Transaction]) -> None:
    for t in transactions:
        t.lender, t.lender_type = identify(t)
