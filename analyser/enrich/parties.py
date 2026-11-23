"""Who each transaction is with: find the name in the description, clean it, group it.

1. Special parties first: Cash, Charges, Interest, Returns, Self (the borrower's own accounts).
2. Otherwise the description is split into pieces ("MMT/IMPS/6003.../Raghavan/INDB0000859")
   and pieces that are channels, reference numbers, IFSC codes, bank codes or masked
   accounts are dropped. The first piece left is the party.
3. Names are grouped by a key that ignores spaces and punctuation ("BRIGHT AUTOMATIONS"
   = "BRIGHTAUTOMATIONS") and company suffixes (PVT LTD). A name that is a long prefix
   of another (bank truncation: "KALAIFINANC" / "KALAI FINANCE") joins that group.
   Names that only look alike are never merged; they are flagged as "possibly the same".
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from analyser.enrich import modes as M
from analyser.model import Transaction

CASH, SELF, CHARGES, INTEREST, RETURNS, UNKNOWN = "Cash", "Self", "Charges", "Interest", "Returns", "Unknown"
SPECIAL_KEYS = {CASH: "_CASH", SELF: "_SELF", CHARGES: "_CHARGES", INTEREST: "_INTEREST",
                RETURNS: "_RETURNS", UNKNOWN: "_UNKNOWN"}

# Words that describe the channel or the bank's plumbing, never the party
CHANNEL_WORDS = {
    "UPI", "UPIPAY", "IMPS", "MMT", "NEFT", "RTGS", "INF", "INFT", "CR", "DR", "TRF", "TFR", "TRFR",
    "TO", "FROM", "BY", "P2A", "IMPSP2A", "CLG", "CHQ", "PAID", "CTS", "NFS", "MPS", "BIL", "ONL",
    "CMS", "ACH", "ACHD", "NACH", "ECS", "BDECS", "FT", "TPT", "MB", "WITHIN", "QUICK", "NETBANK",
    "MUM", "IN", "NA", "UNKNOW", "RETURN", "RTN", "RETURNED", "VIA", "PAYMENT", "BILL", "VENDORPAYMENT",
    "PAYMENTS", "TRANSFER", "TRANSACTION", "IMPSTRANSACTION", "FUND", "FUNDS", "ONLINE", "MOB", "MOBILE",
    "IB", "NB", "INB", "OTHER", "OTHERS", "SB", "CA", "OD", "CC", "ATTN", "REF", "UTR", "INWARD", "OUTWARD",
    "REQPAY", "PAY", "SENT", "RECEIVED", "COLLECT", "MANDATE", "EMI", "NEFTCR", "NEFTDR", "RTGSCR",
    "RTGSDR", "BPAY", "BBPS", "POS", "ECOM", "VPS", "IPS", "PCD", "DEBIT", "CREDIT", "CARD", "REJ",
    "DISBURSEMENT", "DISB",
}
# IMPS remark typed by the sender after the masked account ("...xxxx4612-self")
SELF_REMARK = re.compile(r"x{3,}\d+\s*-\s*(self|own|own\s*a/?c)\b", re.I)
# Short bank codes used in UPI/IMPS descriptions, and IFSC prefixes
BANK_CODES = {
    "SBI", "SBIN", "IOB", "IOBA", "HDF", "HDFC", "ICI", "ICIC", "ICICI", "UBI", "UBIN", "BDB", "PUN", "PUNB",
    "PNB", "KVB", "KVBL", "TMB", "TMBL", "CIU", "CIUB", "CUB", "BKI", "BKID", "CBI", "CBIN", "BAR", "BARB",
    "BOB", "FDR", "FDRL", "IDB", "IDIB", "YESB", "UTIB", "AXL", "CNRB", "KKBK",
    "INDB", "DBSS", "DBS", "SIBL", "SIB", "KCU", "CAB", "IDFB", "AUBL", "ESFB", "UCBA", "UCO",
    "MAHB", "BOM", "PSIB", "JAKA", "KARB", "CSBK", "DLXB", "NTBL", "RATN", "TJSB", "COSB", "APGB", "SCBL",
    "HSBC", "DEUT", "AIRP", "PYTM", "FINO", "JIOP", "UJVN", "SURY", "UPIMI",
}
# Clearing-house cities printed on cheque lines ("900001:CTS-CHENNAI-IN10"): never a party
PLACES = {"CHENNAI", "MUMBAI", "DELHI", "NEW DELHI", "KOLKATA", "BANGALORE", "BENGALURU", "HYDERABAD",
          "COIMBATORE", "COIMBATOR", "MADURAI", "TRICHY", "SALEM", "VELLORE"}
# Bank codes some banks glue onto names ("ZEN INDUSTICIC" = "ZEN INDUST" + ICIC)
GLUED_BANK = re.compile(r"(?<=[A-Za-z]{4})(ICIC|HDFC|SBIN|IOBA|KVBL|UTIB)$", re.I)
REMARK_AFTER_MASK = re.compile(r"x{3,}\d+", re.I)  # IMPS: anything after a masked account is a remark
IFSC = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$", re.I)
VPA = re.compile(r"[^\s/|]*@[^\s/|]*")  # a UPI id never contains "/"
# "balareddy29011okicici" (VPA with the @ lost) -> "balareddy"
VPA_LOST_AT = re.compile(r"^([a-z]{3,})[a-z.]*\d*\.?(ok)?(icici|hdfcbank|sbi|axis|ybl|paytm|ibl|axl|upi)$", re.I)
COMPANY_SUFFIX = re.compile(
    r"\b(PVT|PRIVATE|PRIVAT|PRIV|LTD|LIMITED|LIMITE|LIMIT|LIMI|LTD\.|CO|COMPANY|M/S|MS|MR|MRS|THE)\b\.?", re.I)


@dataclass
class PartyGroup:
    key: str
    name: str  # display name
    variants: Counter = field(default_factory=Counter)  # raw names seen and how often


@dataclass
class PartyIndex:
    groups: dict[str, PartyGroup]
    possibly_same: list[tuple[str, str, int]]  # (key a, key b, similarity %)

    def name(self, key: str) -> str:
        if key in self.groups:
            return self.groups[key].name
        for label, k in SPECIAL_KEYS.items():
            if k == key:
                return label
        return key


def _is_code(word: str) -> bool:
    w = word.strip(".,()")
    if not w:
        return True
    if w.upper() in CHANNEL_WORDS or w.upper() in BANK_CODES:
        return True
    if IFSC.match(w):
        return True
    digits = sum(c.isdigit() for c in w)
    letters = sum(c.isalpha() for c in w)
    if digits and letters:  # mixed: references, UTRs, terminal ids ("ICI27c6ff", "S4", "C254")
        return True
    if digits and not letters:
        return True
    if re.fullmatch(r"x+\d*", w, re.I):
        return True
    return False


def _clean_piece(piece: str) -> str:
    words = []
    for w in piece.split():
        m = VPA_LOST_AT.match(w)
        if m and any(c.isdigit() for c in w):
            words.append(m.group(1))
            continue
        if not _is_code(w):
            words.append(GLUED_BANK.sub("", w.strip(".,()")))
    name = " ".join(words)
    name = re.sub(r"\(.*$", "", name)  # "Epimoney(R" -> "Epimoney"
    name = re.sub(r"\b(BANK|BAN|BANK LTD)\b.*$", "", name, flags=re.I) if re.search(
        r"\b(BANK|BAN)\b", name, re.I) and len(name.split()) > 1 else name
    name = re.sub(r"\s+", " ", name).strip(" .-&,")
    return "" if name.upper() in PLACES else name


def extract_name(description: str) -> str:
    """The party's name as written in the description, or '' if there is none."""
    text = description or ""
    text = REMARK_AFTER_MASK.split(text)[0]  # drop the free-text remark after a masked account
    text = VPA.sub(" / ", text)
    pieces = re.split(r"[/:|\\]+|-+|_|\s{2,}", text)
    for piece in pieces:
        name = _clean_piece(piece)
        letters = sum(c.isalpha() for c in name)
        if letters >= 2 and not re.fullmatch(r"(SELF|CASH)", name, re.I):
            return name.upper()
        if re.fullmatch(r"SELF", name, re.I):
            return "SELF"
    return ""


def name_key(name: str) -> str:
    """Grouping key: letters and digits only, no company suffixes, no spaces."""
    stripped = COMPANY_SUFFIX.sub(" ", name.upper())
    key = re.sub(r"[^A-Z0-9]", "", stripped)
    return key or re.sub(r"[^A-Z0-9]", "", name.upper())


def _words(name: str) -> set[str]:
    return set(re.sub(r"[^A-Z0-9 ]", " ", COMPANY_SUFFIX.sub(" ", name.upper())).split())


def _is_self(name: str, holders: list[str]) -> bool:
    """Is this name the account holder (the borrower's own account)?

    Strict on purpose: "RAMANAN" (a person) is not "RAMANA TRADERS SILK" (the firm).
    """
    key = name_key(name)
    if key == "SELF":
        return True
    words = _words(name)
    for holder in holders:
        hk = name_key(holder)
        if len(hk) < 4:
            continue
        if key == hk:
            return True
        # Truncated holder name ("ZENINDUST" of "ZENINDUSTRIES"), or 1-2 letters added ("...RIESC")
        if len(key) >= 8 and hk.startswith(key):
            return True
        if key.startswith(hk) and len(key) - len(hk) <= 2:
            return True
        # Same words in any order, or at most one word different on each side, as long as the
        # holder's first word is there ("RAMANA TRADERS CC" for "RAMANA TRADERS SILK")
        hwords = _words(holder)
        common = words & hwords
        first = (_words(holder.split()[0]) or {""}).pop() if holder.split() else ""
        if (len(common) >= 2 and first in common
                and len(words - hwords) <= 1 and len(hwords - words) <= 1):
            return True
    return False


ACCOUNT_THEN_NAME = re.compile(r"(\d{10,18})\s*-\s*([A-Za-z][A-Za-z .&]{2,40})")
MASKED_SIDE = re.compile(r"(DR|CR)\s*:\s*X+(\d{4})", re.I)


def assign_parties(transactions: list[Transaction], holders: list[str],
                   own_account_nos: list[str] | None = None) -> PartyIndex:
    holders = [h for h in holders if h]
    own_last4 = {a[-4:] for a in (own_account_nos or []) if a}

    # Account numbers named elsewhere ("FT - DR - 9999135000007830 - QX CHEMICALS")
    # let us name masked transfers ("MB-WITHIN-DR:XXXX0020- CR:XXXX7830").
    by_last4: dict[str, str] = {}
    for t in transactions:
        for acc, name in ACCOUNT_THEN_NAME.findall(t.description or ""):
            n = extract_name(name)
            if n:
                by_last4.setdefault(acc[-4:], n)

    for t in transactions:
        t.party_raw, special = "", None
        if t.mode == M.CASH:
            special = CASH
        elif t.mode == M.CHARGES:
            special = CHARGES
        elif t.mode == M.INTEREST:
            special = INTEREST
        elif t.mode == M.RETURN:
            special = RETURNS
        else:
            raw = extract_name(t.description)
            if not raw:
                sides = dict((s.upper(), d) for s, d in MASKED_SIDE.findall(t.description or ""))
                other = sides.get("CR") if t.debit else sides.get("DR")
                if (other and other in own_last4) or SELF_REMARK.search(t.description or ""):
                    special = SELF
                elif other and other in by_last4:
                    raw = by_last4[other]
            t.party_raw = raw
            if raw and _is_self(raw, holders):
                special = SELF
            elif not raw and special is None:
                special = UNKNOWN
        if special:
            t.party_key, t.party_clean = SPECIAL_KEYS[special], special
        else:
            t.party_key = name_key(t.party_raw)
            t.party_clean = t.party_raw

    return _group(transactions)


PREFIX_MERGE_MIN = 10  # a truncated name must keep at least this many characters to be merged
SIMILAR = 88


def _group(transactions: list[Transaction]) -> PartyIndex:
    variants: dict[str, Counter] = defaultdict(Counter)
    for t in transactions:
        if not t.party_key.startswith("_"):
            variants[t.party_key][t.party_raw] += 1

    # Truncated names join the longer name they are a prefix of (only if unambiguous)
    keys = sorted(variants, key=len, reverse=True)
    parent: dict[str, str] = {}
    for k in keys:
        if len(k) < PREFIX_MERGE_MIN:
            continue
        longer = [o for o in keys if len(o) > len(k) and o.startswith(k) and o not in parent]
        roots = {parent.get(o, o) for o in longer}
        if len(roots) == 1:
            parent[k] = roots.pop()

    groups: dict[str, PartyGroup] = {}
    for k, var in variants.items():
        root = parent.get(k, k)
        g = groups.setdefault(root, PartyGroup(key=root, name=""))
        g.variants.update(var)
    for g in groups.values():
        # Show a spelling with proper word breaks if there is one ("KALAI FINANCE", not
        # "KALAIFINANC"), then the most used, then the longest (least truncated)
        g.name = max(g.variants, key=lambda v: (" " in v.strip(), g.variants[v], len(name_key(v)), v))

    for t in transactions:
        if t.party_key in parent:
            t.party_key = parent[t.party_key]
            t.party_clean = groups[t.party_key].name
        elif t.party_key in groups:
            t.party_clean = groups[t.party_key].name

    # Look-alikes are only flagged, never merged. Every spelling is compared, so
    # "KALAJFINANCE" is caught against "KALAIFINANCE" even if that group shows a longer name.
    spellings = [(name_key(v), g.key) for g in groups.values() for v in g.variants]
    best: dict[tuple[str, str], int] = {}
    for i, (a, ga) in enumerate(spellings):
        for b, gb in spellings[i + 1:]:
            if ga == gb or min(len(a), len(b)) < 5:
                continue
            score = int(fuzz.ratio(a, b))
            pair = tuple(sorted((ga, gb)))
            if score >= SIMILAR and score > best.get(pair, 0):
                best[pair] = score
    possibly = sorted(((a, b, s) for (a, b), s in best.items()), key=lambda x: -x[2])
    return PartyIndex(groups=groups, possibly_same=possibly)
