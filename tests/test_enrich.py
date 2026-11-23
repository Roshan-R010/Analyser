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


@pytest.mark.parametrize("desc,name", [
    ("CLG/000111/011026/Hdfc Bank /ABC TRADERS", "ABC TRADERS"),  # drawee bank comes first
    ("CLG/000222/011026/South Indi/XYZ AGENCIES", "XYZ AGENCIES"),  # truncated bank name skipped
    ("UPI/P2A/100000000001/Bank Account XXXXXXXX/Paymen/ICICI Bank", ""),  # masked payee
    ("UPI/P2M/100000000002/SOME SHOP /Paymen/YES BANK LIMITED YBS", "SOME SHOP"),
    ("MOB/TPFT/RAVI KUMAR/9170200300000", "RAVI KUMAR"),
    ("ECOM PUR/SOMESHOP* CL/CITY/091126/12:32/243776", "SOMESHOP CL"),
    ("UPI/P2M/100000000003/ABC CHIT FUNDS PRIV /Paymen/KARUR VYSA", "ABC CHIT FUNDS PRIV"),
])
def test_names_axis_style(desc, name):
    assert extract_name(desc) == name


def test_auto_debit_to_a_bank_is_a_bank_loan():
    tx = [T("ACH-DR-HDFC BANK LTD-481200000- UTIB70200000000000", debit="5000", mode="ECS/NACH")]
    assign_parties(tx, ["SOMEONE"])
    assert tx[0].party_clean == "HDFC BANK LTD"
    assert identify(tx[0]) == ("HDFC BANK LTD", "Bank")


def test_counterpartys_bank_is_not_a_lender():
    t = T("UPI/P2A/100000000004/Ravi M /Rent/ESAF SMALL FINANCE B", debit="500", mode="UPI",
          party_clean="RAVI M", party_key="RAVIM")
    assert identify(t) == ("", "")


def test_more_modes():
    assert classify(T("Monthly Service Chrgs SEP-26", debit="150")) == "Charges"
    assert classify(T("MOB/TPFT/RAVI KUMAR/9170200300000", debit="1")) == "Transfer"
    assert classify(T("ATM-CASH- AXIS/ABCD100000/1111/201026/TOWN", debit="1")) == "Cash"


def test_outward_return_charge_with_gst_is_one_deposited_return():
    from analyser.sections.returns import build_returns
    tx = [T("Chq Rtn O/W Chrgs", debit="50", d=date(2026, 10, 17)),
          T("GST @18% on Chq Rtn O/W Chrgs", debit="9", d=date(2026, 10, 17))]
    for t in tx:
        t.mode = classify(t)
    [b] = build_returns(tx).bounces
    assert b.direction == "Deposited by borrower" and len(b.charges) == 2


def test_loans_without_a_lender_name():
    cases = [
        ("ABC012345678901_EMI_21-09-2026", "Axis Bank loan a/c …8901", "Bank"),
        ("ECS/UTIBDE01111110202606/RAZORPAY SOFTWARE LIMITE",
         "Auto-debit via Razorpay (mandate UTIBDE01111110202606)", "Lender not named"),
        ("ACH-DR-INSTALLMENT- 0000AAAA1111BBBB222233334444", "Auto-debit installment", "Lender not named"),
    ]
    for desc, lender, kind in cases:
        t = T(desc, debit="1000", bank="axis")
        t.mode = classify(t)
        assign_parties([t], ["SOMEONE"])
        assert t.mode == "ECS/NACH", desc
        assert identify(t) == (lender, kind), desc


def test_emi_collected_in_pieces():
    from analyser.sections.loans import usual_emi
    pays = [T("x", debit=a, d=d) for a, d in [
        ("36228", date(2026, 8, 20)), ("7631.25", date(2026, 9, 21)), ("11300", date(2026, 9, 22)),
        ("17886.75", date(2026, 9, 24)), ("1770.35", date(2026, 10, 21)), ("35047.65", date(2026, 10, 22)),
        ("36818", date(2026, 11, 21))]]
    assert usual_emi(pays) == D("36818.00")
    assert usual_emi([T("x", debit="500", d=date(2026, m, 5)) for m in (1, 2, 3)]) == D("500")


def test_self_transfer_in_description():
    tx = [T("INB/IFT/RAVI ./SELF TRANSFE", debit="1", mode="Transfer")]
    assign_parties(tx, ["XYZ TRADERS"])
    assert tx[0].party_clean == "Self"


def test_printed_returns_become_bounces_and_take_late_charges():
    from analyser.model import PrintedReturn
    from analyser.sections.returns import build_returns
    printed = [PrintedReturn(date=date(2026, 8, 12), cheque_no="100001", amount=D("62500"),
                             reason="Funds insufficient", inward=True)]
    tx = [T("Chq Rtn I/W Chrgs", debit="1850", d=date(2026, 9, 19)),
          T("GST @18% on Chq Rtn I/W Chrgs", debit="333", d=date(2026, 9, 19))]
    for t in tx:
        t.mode = classify(t)
    [b] = build_returns(tx, printed).bounces
    assert b.kind == "Funds" and b.direction == "Issued by borrower" and b.charge_total == D("2183")


def test_recurring_patterns():
    from analyser.sections.recurring import pattern_label
    d = date
    assert pattern_label([d(2026, m, 5) for m in (8, 9, 10, 11)], True) == "Monthly · 5th"
    assert pattern_label([d(2026, 8, 5), d(2026, 9, 7), d(2026, 10, 5)], True) == "Monthly · 5th"  # holiday shift
    assert pattern_label([d(2026, 8, 13), d(2026, 9, 15), d(2026, 10, 14)], True) == "About monthly"
    assert pattern_label([d(2026, 9, 25), d(2026, 10, 8), d(2026, 10, 22)], True) == "About fortnightly"
    assert pattern_label([d(2026, 8, 7), d(2026, 8, 8), d(2026, 9, 20)], True) == "Variable dates"
    assert pattern_label([d(2026, 8, 7), d(2026, 8, 8), d(2026, 9, 20)], False) == "Irregular"
    assert pattern_label([d(2026, 8, 1)], True) == "Additional payment"


def test_recurring_amount_lines():
    from analyser.sections.recurring import amount_lines
    def P(day, month, amt, lender=""):
        return T("x", debit=amt, d=date(2026, month, day), lender=lender)
    # Repeated amounts get a line each; a near-equal amount joins with its date listed
    lines = amount_lines([P(13, 8, "30000"), P(15, 9, "30000"), P(14, 10, "30005.90"), P(14, 11, "30000")], "A")
    assert len(lines) == 1 and lines[0].count == 4 and lines[0].main_count == 3
    assert lines[0].odd == [(D("30005.90"), date(2026, 10, 14))]
    # Different mandates stay apart; a one-off is an additional payment with its mandate
    m1, m2 = "Auto-debit via X (mandate UTIBDE0000111122223333)", "Auto-debit via X (mandate UTIBDE0000444455556666)"
    lines = amount_lines([P(5, 8, "100", m1), P(5, 9, "100", m1), P(5, 8, "100", m2), P(5, 9, "100", m2),
                          P(30, 9, "500", m1)], "X")
    assert [(ln.amount, ln.count, ln.pattern) for ln in lines][-1] == (D("500"), 1, "Additional payment")
    assert lines[0].note == "Mandate · …111122223333" and lines[1].note == "Mandate · …444455556666"
    # All different amounts: one "Variable amounts" line
    lines = amount_lines([P(1, 8, "100"), P(9, 8, "250"), P(3, 10, "900")], "B")
    assert len(lines) == 1 and lines[0].amount is None and lines[0].count == 3
    # Bank loan account shown under the amount
    loan = "Axis Bank loan a/c …1234"
    lines = amount_lines([P(5, 8, "16170", loan), P(5, 9, "16170", loan)], "C")
    assert lines[0].note == "Axis Bank loan · a/c …1234"


def test_loan_page_wording():
    from analyser.sections.loans import _short_refs, build_loans, loan_blocks
    from analyser.sections.returns import build_returns
    # Mandates that end alike are told apart by the digits before the shared tail
    assert _short_refs(["UTIBDE01111111202606", "UTIBDE02222222202606"]) == {
        "UTIBDE01111111202606": "1111", "UTIBDE02222222202606": "2222"}
    assert _short_refs(["ABCD12345678"]) == {"ABCD12345678": "5678"}
    m = "Auto-debit via X (mandate UTIBDE01111111202606)"
    tx = [T("ECS/a", debit=a, d=date(2026, mo, dy), lender=m, lender_type="Lender not named", mode="ECS/NACH")
          for a, mo, dy in [("100", 8, 5), ("100", 9, 5), ("500", 9, 30), ("100", 10, 5)]]
    tx.append(T("NEFT/loan", credit="9000", d=date(2026, 8, 1), lender=m, lender_type="Lender not named"))
    tx.sort(key=lambda t: t.date)
    (b,) = loan_blocks(build_loans(tx, build_returns(tx)))
    assert b.title == "Auto-debit via X · mandate …2606"  # one mandate: plain last 4
    assert "4 payments · monthly auto-debit and one additional debit" in b.subline
    assert "received" in b.subline
    assert [w for _, w in b.rows] == ["Loan amount received", "Monthly auto-debit", "Monthly auto-debit",
                                      "Additional auto-debit", "Monthly auto-debit"]
