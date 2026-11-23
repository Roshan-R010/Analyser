"""Enrich: add payment mode, cheque number, party and lender to every transaction."""
from __future__ import annotations

from analyser.combine import Account
from analyser.enrich.cheques import assign_cheques
from analyser.enrich.lenders import assign_lenders
from analyser.enrich.modes import assign_modes
from analyser.enrich.parties import PartyIndex, assign_parties


def enrich(accounts: list[Account]) -> PartyIndex:
    """Enrich all accounts of one borrower together, so a party is grouped the same way
    across accounts and transfers between the borrower's own accounts show as Self."""
    tx = [t for acc in accounts for t in acc.transactions]
    holders = sorted({acc.holder for acc in accounts if acc.holder})
    own_accounts = [acc.account_no for acc in accounts if acc.account_no]
    assign_modes(tx)
    assign_cheques(tx)
    index = assign_parties(tx, holders, own_accounts)
    assign_lenders(tx)
    return index
