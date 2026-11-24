import copy

from analyser.combine import combine

from analyser.model import Statement
from analyser.verify import verify
from conftest import load


def _part(st, txns, no):
    p = copy.copy(st)
    p.transactions = txns
    p.statement_no = no
    p.period_from, p.period_to = txns[0].date, txns[-1].date
    first = txns[0]
    p.opening_balance = first.balance - first.amount
    return p


def _as_statement(acc):
    return Statement(bank=acc.bank, opening_balance=acc.opening_balance, transactions=acc.transactions)


def test_overlapping_statements_count_each_entry_once():
    st = load("icic.pdf").statement
    tx = st.transactions
    # Part 1: Jan to end of June. Part 2: from 1 June (one month of overlap) to Oct.
    june = next(i for i, t in enumerate(tx) if t.date.month == 6)
    july = next(i for i, t in enumerate(tx) if t.date.month == 7)
    a, b = _part(st, tx[:july], 1), _part(st, tx[june:], 2)
    [acc] = combine([b, a])  # order given doesn't matter
    assert acc.transactions == tx
    assert verify(_as_statement(acc)).ok
    assert any("overlaps" in n for n in acc.notes)


def test_gap_between_statements_is_reported():
    st = load("icic.pdf").statement
    tx = st.transactions
    april = next(i for i, t in enumerate(tx) if t.date.month == 4)
    may = next(i for i, t in enumerate(tx) if t.date.month == 5)
    a, b = _part(st, tx[:april], 1), _part(st, tx[may:], 2)
    [acc] = combine([a, b])
    assert any(n.startswith("Gap") for n in acc.notes)
    assert not verify(_as_statement(acc)).ok  # the missing April shows as a balance break


def test_different_accounts_stay_separate(passwords):
    a = load("icic.pdf").statement
    b = load("KVB.pdf").statement
    assert len(combine([a, b])) == 2
