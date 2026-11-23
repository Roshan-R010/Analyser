from datetime import date
from decimal import Decimal as D

import pytest

from analyser.readers.parse import amount_side, parse_amount, parse_date


@pytest.mark.parametrize("text,expected", [
    ("01-OCT-2026", date(2026, 10, 1)),
    ("02-Jan-2026", date(2026, 1, 2)),
    ("02-Jan-26", date(2026, 1, 2)),
    ("02 Jan 2026", date(2026, 1, 2)),
    ("5 Sept 2026", date(2026, 9, 5)),
    ("01/07/2026", date(2026, 7, 1)),
    ("01-07-26", date(2026, 7, 1)),
    ("01.07.2026", date(2026, 7, 1)),
    ("2026-07-01", date(2026, 7, 1)),
    ("02-OCT-2026 03:58:30", date(2026, 10, 2)),
])
def test_dates(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["", "S6339832", "600066660000", "31-02-2026", "B/F..."])
def test_not_dates(text):
    assert parse_date(text) is None


@pytest.mark.parametrize("text,expected", [
    ("1,00,000.00", D("100000.00")),
    ("18,40,220.66", D("1840220.66")),
    ("49452.00", D("49452.00")),
    ("0.00", D("0.00")),
    ("-", D("0.00")),
    ("", D("0.00")),
    ("₹ 67058.89", D("67058.89")),
    ("1,234.50 Cr", D("1234.50")),
    ("1,234.50 Dr", D("-1234.50")),
    ("1,234.50Dr", D("-1234.50")),
    ("(500.00)", D("-500.00")),
    ("-500.00", D("-500.00")),
    ("100", D("100.00")),
])
def test_amounts(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["UPI", "1.2.3", "TRF", "02-OCT-2026"])
def test_not_amounts(text):
    assert parse_amount(text) is None


def test_amount_side():
    assert amount_side("Dr") == "dr"
    assert amount_side("CR") == "cr"
    assert amount_side("") == ""
