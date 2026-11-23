"""Enrichment rules on made-up descriptions shaped like real bank formats (no real data)."""
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from analyser.enrich.cheques import assign_cheques
from analyser.enrich.lenders import identify
from analyser.enrich.modes import classify
from analyser.enrich.parties import _is_self, assign_parties, extract_name
from analyser.model import Transaction
from analyser.sections.modes import shares_to_100
from analyser.sections.recurring import interval_label


def T(desc, debit="0", credit="0", **kw):
    return Transaction(date=kw.pop("d", date(2026, 1, 5)), description=desc,
                       debit=D(debit), credit=D(credit), **kw)


@pytest.mark.parametrize("desc,mode", [
    ("MMT/IMPS/600011112222/Ramesh/INDB0000123", "IMPS"),
    ("UPI/111122223333/UPIPay/XX12-1@okhdfcb//ICI1a2b3c", "UPI"),
    ("UPI-DR-611122223333-ABC STORES- YESB-0022000000001", "UPI"),
    ("NEFT-HDFCH00711112222-ABC TRADERS-0001-5020", "NEFT"),
    ("RTGS CR-UTIB0001234-ABC TRAVELS-XYZ ENTERPRISES", "RTGS"),
    ("KVBLR52026111311112222-abc traders-920020000000", "RTGS"),
    ("KVBLH00271112222-abc traders 2-0502020000", "NEFT"),
    ("NFS/CASHWDL/600011112222/48500000/Town/03-01", "Cash"),
    ("CAM/01111ABC/CASHDEP-Self/05-02-26/1234", "Cash"),
    ("BY CASH BY CASH", "Cash"),
    ("CHQ PAID-SELF-SELF - BRANCH", "Cash"),
    ("CLG/ABC MOTORS/123456/KCU/30.12.2025", "Cheque"),
    ("To Clg:RAVI - SOME BANK", "Cheque"),
    ("To Clg:ECS SOMEFINANCEINVESTM - NACH", "ECS/NACH"),
    ("BDECS-ABC FINANCE LIMITE- IOBA0000000012345678", "ECS/NACH"),
    ("BIL/ONL/001100002222/Someloan", "Bill pay"),
    ("MPS/ABC SHOP/202601010101/123456/TOWN", "Card"),
    ("INF/INFT/045000001111/SELF", "Transfer"),
    ("FT - DR - 1278135000011111 - RAVI R", "Transfer"),
    ("Chq rtn ChgJan-26+GST", "Charges"),
    ("INWARD CHEQUE RETURN SC :000000000555", "Charges"),
    ("BRANCH RTGS CHARGES", "Charges"),
    ("RETURNED:900001:FUNDS INSUFFICIENT", "Return"),
    ("By Clg(Rej):RAVI-11NOV26- NO_FUNDS AVAILABL", "Return"),
    ("RTGS-RTN- KKBKR52026010100011111- INCORRECT ACCOUNT", "Return"),
    ("NFS/CASHWDL RVSL/600099990000/1111AB01/TOWN/", "Return"),
    ("SCHOOL FEES PAID", "Other"),
])
def test_modes(desc, mode):
    assert classify(T(desc, debit="100")) == mode


def test_bank_code_column_beats_weak_words():
    assert classify(T("TO K RAVI", debit="100", code="CSH", cheque_no="900003")) == "Cash"
    assert classify(T("R KUMAR", debit="100", code="TRF", cheque_no="900004")) == "Cheque"
    assert classify(T("SRI ABC CONSTRUCTIONS", credit="100", code="TRF")) == "Transfer"


@pytest.mark.parametrize("desc,name", [
    ("MMT/IMPS/600011112222/Ramesh/INDB0000123", "RAMESH"),
    ("UPI/RAMESH/XXab@okicici/UPI/SOME B/66206", "RAMESH"),
    ("UPI/611122223333/DR/ RAVI K/HDF/UPI", "RAVI K"),
    ("UPI-DR-611122223333-ABC STORES- YESB-0022000000001", "ABC STORES"),
    ("NEFT-SBIN00011112222-ANIL KUMAR--91100000000", "ANIL KUMAR"),
    ("RTGS CR-UTIB0001234-ABC TRAVELS-XYZ ENTERPRISES", "ABC TRAVELS"),
    ("FT - DR - 1278135000011111 - RAVI R", "RAVI R"),
    ("To Clg:RAVI - SOME FINANCE BANK", "RAVI"),
    ("CLG/AXIS CORPORATION/814943/SBI/19.01.2026", "AXIS CORPORATION"),
    ("BIL/ONL/001100002222/Someloan(R", "SOMELOAN"),
    ("900001:CTS-CHENNAI-IN10", ""),
    ("UPI/111122223333/UPIPay/XX12-1@okhdfcb//ICI1a2b3c", ""),
    ("UPI-DR-600044440000- ravikumar12345okicici-IOBA-145", "RAVIKUMAR"),
    ("MMT/IMPS/600088880000/ABC INDUSTICIC/ABC INDUST/Ci", "ABC INDUST"),
])
def test_names(desc, name):
    assert extract_name(desc) == name


def test_self_is_strict():
    holders = ["RAMANA TRADERS SILK"]
    assert _is_self("RAMANA TRADERS CC", holders)
    assert _is_self("RAMANA SILK TRADERS", holders)
    assert not _is_self("RAMANAN", holders)
    assert not _is_self("RAMANAN K", holders)
    assert _is_self("ZEN INDUST", ["ZEN INDUSTRIES"])  # truncated holder name


def test_truncated_names_merge_lookalikes_only_flagged():
    tx = [T("CLG/KALAI FINANCES/KCU", debit="1", mode="Cheque"),
          T("MMT/IMPS/600011112222/kalaifinanc/CIUB0000211", debit="1", mode="IMPS"),
          T("CLG/KALAJ FINANCE/KCU", debit="1", mode="Cheque")]
    idx = assign_parties(tx, ["SOMEONE ELSE"])
    assert tx[0].party_key == tx[1].party_key
    assert tx[2].party_key != tx[0].party_key
    assert idx.possibly_same


def test_masked_transfer_named_from_other_entry():
    tx = [T("FT - DR - 9999135000007830 - QX CHEMICALS", debit="1", mode="Transfer"),
          T("MB-WITHIN-DR:XXXX0020- CR:XXXX7830-1234990110260258", debit="1", mode="Transfer")]
    assign_parties(tx, ["XYZ"], ["9999011000000020"])
    assert tx[1].party_clean == "QX CHEMICALS"


def test_imps_remark_self():
    tx = [T("IMPS-600055550000-IMPSP2A-HDFC- xxxxxxxxxx4612-self", debit="1", mode="IMPS")]
    assign_parties(tx, ["XYZ"])
    assert tx[0].party_clean == "Self"


def test_cheque_numbers_from_reference_and_text():
    tx = [T("To Clg:RAVI - SOME BANK", debit="1", mode="Cheque", ref_no="000000000777"),
          T("RETURNED:900001:FUNDS INSUFFICIENT", credit="1", mode="Return"),
          T("UPI-DR-600077770000-SHOP", debit="1", mode="UPI", ref_no="600077770000")]
    assign_cheques(tx)
    assert [t.cheque_no for t in tx] == ["777", "900001", ""]


def test_lenders():
    t = T("BIL/ONL/001100003333/Lendingkar", debit="42432", mode="Bill pay",
          party_clean="LENDINGKAR", party_key="LENDINGKAR")
    assert identify(t) == ("Lendingkart", "Fintech")
    t = T("CLG/SOME FINANCE/KCU", debit="1", mode="Cheque", party_clean="SOME FINANCE", party_key="SOMEFINANCE")
    assert identify(t) == ("SOME FINANCE", "Private finance")
    t = T("UPI-DR-1-SAFE GOLD-YESB", debit="1", mode="UPI", party_clean="SAFE GOLD", party_key="SAFEGOLD")
    assert identify(t) == ("", "")
    t = T("HANDLOANRETURN RTGS DR", debit="1", mode="RTGS", party_clean="ABC CO", party_key="ABC")
    assert identify(t) == ("ABC CO", "Hand loan")


def test_percentages_always_total_100():
    assert sum(shares_to_100({"A": D("1"), "B": D("1"), "C": D("1")}).values()) == D("100.0")
    assert sum(shares_to_100({"A": D("44.64"), "B": D("15.93"), "C": D("39.43")}).values()) == D("100.0")


def test_interval_labels():
    d = date(2026, 1, 5)
    assert interval_label([d + timedelta(days=30 * i) for i in range(5)]) == "Monthly"
    assert interval_label([d + timedelta(days=14 * i) for i in range(5)]) == "Fortnightly"
    assert interval_label([d + timedelta(days=i) for i in range(20)]).startswith("Frequent")
