"""The standard transaction: every bank's statement is read into this one shape.

Amounts are Decimal, never float, so totals are exact to the paisa.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal("0.00")


@dataclass
class Transaction:
    date: date
    description: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    balance: Decimal | None = None
    value_date: date | None = None
    ref_no: str = ""
    cheque_no: str = ""
    code: str = ""  # bank's own transaction code column, if any (e.g. IOB: CSH / CLR / TRF)
    # Filled in by the enrich step
    mode: str = ""  # NEFT, RTGS, IMPS, UPI, Cash, Cheque, ECS/NACH, Transfer, ...
    party_raw: str = ""  # name as found in the description
    party_clean: str = ""  # cleaned display name, or Cash / Self / Charges / Interest / ""
    party_key: str = ""  # grouping key: same key = same party
    lender: str = ""  # lender name when this entry is a loan payment or disbursement
    lender_type: str = ""
    # Where it came from, so any problem can be pointed at exactly
    bank: str = ""
    statement_no: int = 0
    page_no: int = 0

    @property
    def amount(self) -> Decimal:
        """Signed amount: credits positive, debits negative."""
        return self.credit - self.debit


@dataclass
class PrintedReturn:
    """One row of a bank's own "cheque return details" table."""

    date: date
    cheque_no: str
    amount: Decimal
    reason: str
    inward: bool  # True: the borrower's own cheque came back; False: a cheque they deposited


@dataclass
class Statement:
    """One uploaded statement after reading."""

    bank: str
    account_holder: str = ""
    account_no: str = ""
    period_from: date | None = None
    period_to: date | None = None
    opening_balance: Decimal | None = None
    transactions: list[Transaction] = field(default_factory=list)
    page_count: int = 0
    statement_no: int = 0
    merged_sections: int = 1  # how many separate statements the PDF holds, each with its own totals
    # Totals the bank itself prints (if any), used as an extra cross-check
    printed_total_debit: Decimal | None = None
    printed_total_credit: Decimal | None = None
    printed_opening: Decimal | None = None
    printed_closing: Decimal | None = None
    # Returned cheques the bank lists in a separate table (some banks, e.g. Axis, list
    # inward returns only there, not as transactions)
    # Amounts printed as negative figures (reversals). We count them on the opposite side;
    # some banks (HDFC) instead net them off in their own printed totals.
    reversal_total: Decimal = ZERO
    printed_returns: list[PrintedReturn] = field(default_factory=list)
    # Anything the reader could not read cleanly (shown in the report, never hidden)
    warnings: list[str] = field(default_factory=list)
