"""Payment mode of each transaction, from its description (and the bank's own code column).

Rules are checked in order; the first that matches wins. Order matters:
charges before returns ("Chq rtn chg" is a charge), returns before channels
("RTGS-RTN" is a return, not an RTGS payment), ECS/NACH before cheque
("To Clg:ECS ... NACH" is a NACH debit). Weak "transfer" wording is checked
only after the bank's code column ("TO K RAMANAN" with code CSH is cash).
"""
from __future__ import annotations

import re

from analyser.model import Transaction

NEFT, RTGS, IMPS, UPI = "NEFT", "RTGS", "IMPS", "UPI"
CASH, CHEQUE, ECS = "Cash", "Cheque", "ECS/NACH"
TRANSFER, BILLPAY, CARD = "Transfer", "Bill pay", "Card"
CHARGES, INTEREST, RETURN, OTHER = "Charges", "Interest", "Return", "Other"

def _r(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


RULES: list[tuple[str, re.Pattern]] = [
    # Bank charges, GST on charges, return charges
    (CHARGES, _r(r"\bchgs?\b|\bchrgs?\b|\bcharges?\b|\+\s*gst|incl\.?\s*gst|\bgst\s*on\b|\bcommission\b"
                 r"|\bsms\s*(alert|chg)|\bamc\b|\bpenal|min(imum)?\.?\s*bal|non[- ]?maint|\bsc\s*:"
                 r"|service\s*charge|\b[cs]gst\b|\bigst\b|chg[a-z]{3}-|\bprocessing\s*fee|\bannual\s*fee"
                 r"|returncharges|postxnmarkup|^mincrreqd|^tds\b|^gst$|^mc comm\b|mdr(rcvry)?\b|\b(edc|soundbox)\s*rental")),
    # Money sent back: cheque returns, rejected clearing, NEFT/RTGS/IMPS/ECS returns, reversals
    (RETURN, _r(r"\b(rtgs|neft|imps|ecs|nach|ach)[\s\-/]*(rtn|return|rej)"
                r"|\b(chq|cheque)\s*(rtn|return)|\breturned\s*:|\(rej\)|\bclg\s*\(?ret"
                r"|\b[io]/?w\s*(chq\s*)?(rtn|return)|inward\s*(chq|cheque)\s*return"
                r"|outward\s*(chq|cheque)\s*return|\brtn\s*(chq|cheque)|\bbounce"
                r"|\brvsl\b|\breversal\b|\breversed\b|\bupi[\s\-]*rev\b")),
    (INTEREST, _r(r"\binterest\b|\bint\.?\s*(pd|paid|cr|credit|coll|on|capitalised)\b|\bint\.pd|^o/sinterest")),
    # ECS / NACH / ACH mandates (EMIs)
    # ECS / NACH / ACH mandates and loan EMIs the bank debits itself ("ABC0123..._EMI_21-09-2026")
    (ECS, _r(r"\b(ecs|nach|achd?|bdecs|si)\b|\bach[\s\-]*d[\s\-]|achd-|ach-d|standing\s*instr"
             r"|\bmandate\b|\bnach[\-/]|(?<![a-z])emi(?![a-z])|\binstal+ment\b")),
    (UPI, _r(r"\bupi(mi|kvb)?\b|upi[\-/]|\bupiout\b|@ok|@ybl|@paytm|@axl|@ibl|@upi|@apl|@ptys|@ptyes|@fbl|@fbp|@hdfc|@sbi")),
    (IMPS, _r(r"\bimps\b|imps[\-/]|mmt/imps|\bp2a\b|imps[a-z]{0,4}\d{8,}")),
    (RTGS, _r(r"\brtgs\b|rtgs[\-/ ]|rtgsdr|rtgscr|^rtg/")),
    (NEFT, _r(r"\bneft\b|neft[\-/ ]|neftdr|neftcr|\bnft\b")),
    # No keyword, but the bank reference says it: XXXXR5... = RTGS, XXXXH... / XXXXN... = NEFT
    (RTGS, re.compile(r"\b[A-Z]{4}R[0-9]{12,}")),
    (NEFT, re.compile(r"\b[A-Z]{4}[HN][0-9]{8,}")),
    # Cash: branch deposits/withdrawals, ATM, self cheques
    (CASH, _r(r"\bcash\b|cashdep|cashwdl|cash\s*(dep|wdl|withdrawal|deposit)|\bcsh\b|\batm\b|\bnfs/"
              r"|\bcwdl\b|\bcsw\b|chq\s*paid[\s\-]*self|self\s*-\s*chq|^\s*your\s*self\s*$|^\s*self\s*$|^(nwd|atw)-")),
    (CARD, _r(r"\bpos\b|pos[\-/_]|^pos\d|^mps/|\bvps/|\bips/|debit\s*card|\becom\b|\bpcd/|card\s*pmt|cards?\s*settl|^\d{6}x{4,}\d{4}\b")),
    (BILLPAY, _r(r"^bil/|\bbbps\b|\bbpay\b|bill\s*pay")),
    (CHEQUE, _r(r"\bclg\b|clg[:/]|_clg\b|^chqpaid|clearing|\bchq\b|\bcheque\b|\bcts\b|\bi/w\b|\bo/w\b|inward\s*clg")),
]

# Transfers within the bank (own or third party). Checked after the bank's code column.
TRANSFER_RULE = _r(r"^inf/|\binft\b|\bft\s*-|\bfund\s*transfer|\bt(r)?fr?\b|\btpt\b"
                   r"|^ebank:|^ift/|^transfer\s+(to|from)\b|fundstransfer|mb-(quick_)?within|within-dr|\bsb\s*trf|^by\s+sb\b|\bib\s*fund|\bdisbursement\b"
                   r"|^cms/|^to\s+[a-z]|^mob/|\btpft\b|^inb/ift\b")

# Bank code column values (e.g. IOB "COD") that settle the mode when nothing else does
CODE_MODES = {"CSH": CASH, "CASH": CASH, "CLR": CHEQUE, "CLG": CHEQUE, "TRF": TRANSFER}


def classify(t: Transaction) -> str:
    text = re.sub(r"\s+", " ", t.description or "").strip()
    for mode, pattern in RULES:
        if pattern.search(text):
            return mode
    code = (t.code or "").strip().upper()
    if code in CODE_MODES:
        if CODE_MODES[code] == TRANSFER and t.cheque_no:
            return CHEQUE  # a transfer made by cheque
        return CODE_MODES[code]
    if TRANSFER_RULE.search(text):
        return TRANSFER
    if t.cheque_no:
        return CHEQUE
    return OTHER


def assign_modes(transactions: list[Transaction]) -> None:
    for t in transactions:
        t.mode = classify(t)
