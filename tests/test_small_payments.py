"""Small payments are left out of the Recurring and Loan lists, but still counted in every total."""
from datetime import date
from decimal import Decimal as D

from analyser.model import Transaction
from analyser.sections.loans import build_loans, loan_blocks
from analyser.sections.recurring import build_recurring
from analyser.sections.returns import ReturnsSection


def _pay(amount, month=1, party="ABC TRADERS", lender="", credit="0"):
    return Transaction(date=date(2026, month, 5), description="x", debit=D(amount), credit=D(credit),
                       party_key=party.replace(" ", ""), party_clean=party, lender=lender,
                       lender_type="NBFC" if lender else "")


def _listed(row):
    return sum(ln.count for ln in row.lines)


def test_recurring_lists_only_payments_of_9000_or_more_but_totals_all():
    [row] = build_recurring([_pay("8999.99", 1), _pay("9000", 2), _pay("20000", 3), _pay("500", 4)])
    assert (_listed(row), row.hidden) == (2, 2)
    assert (row.total, row.entries) == (D("38499.99"), 4)


def test_a_party_paid_only_small_amounts_is_not_listed_as_recurring():
    assert build_recurring([_pay("4000", m) for m in (1, 2, 3, 4)]) == []


def test_a_lender_in_recurring_uses_the_5000_limit():
    [row] = build_recurring([_pay("4999", 1, lender="X Fin"), _pay("5000", 2, lender="X Fin"),
                             _pay("6000", 3, lender="X Fin")])
    assert (_listed(row), row.hidden) == (2, 1)


def test_loan_page_lists_payments_of_5000_or_more_and_all_money_received():
    tx = [_pay("4999", 1, lender="X Fin"), _pay("5000", 2, lender="X Fin"),
          _pay("0", 3, lender="X Fin", credit="1000")]
    [loan] = build_loans(tx, ReturnsSection(bounces=[], transfer_returns=[]))
    [block] = loan_blocks([loan])
    assert [t.debit or t.credit for t, _ in block.rows] == [D("5000"), D("1000")]
    assert (loan.paid_total, loan.payments, block.paid) == (D("9999"), 2, D("9999"))
    assert "1 under ₹5,000 not listed" in block.subline
