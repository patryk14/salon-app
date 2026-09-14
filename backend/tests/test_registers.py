"""Booksy cash-registers TRANSACTIONS parser: derive daily gotówka + kasa
fiskalna by payment method; flag package redemptions; skip the total row."""

from datetime import date
from decimal import Decimal

from app.registers import parse_cash_transactions

_HDR = [
    "",
    "",
    "Data transakcji",
    "Numer dokumentu",
    "Numer rejestru",
    "Klient",
    "Pracownik",
    "Wpływy",
    "Wydatki",
    "Metoda płatności",
]


def _tx(idx, dt, client, inflow, method):
    return ["", idx, dt, "doc", "reg", client, "Karolina Sobas", inflow, "0", method]


def test_parse_cash_transactions_by_method() -> None:
    grid = [
        ["", "Transakcje z rejestrów kasowych"],
        _HDR,
        _tx("1", "12.09.2026 13:05", "A", "75", "Terminal płatniczy"),
        _tx("2", "12.09.2026 10:00", "B", "0", "Pakiet"),  # package redemption
        _tx("3", "11.09.2026 14:00", "C", "105", "Gotówka"),
        _tx("4", "11.09.2026 15:00", "D", "150", "Terminal płatniczy"),
        ["", "", "", "", "", "", "Razem", "330", "0", ""],  # total row → skipped (no date)
    ]
    p = parse_cash_transactions(grid)
    assert p.transactions == 4
    assert p.package_redemptions == 1
    assert len(p.package_txs) == 1
    assert p.package_txs[0][1] == "B"  # (date, client, doc) of the Pakiet row

    d12, d11 = date(2026, 9, 12), date(2026, 9, 11)
    assert p.by_day[d12]["booksy_cash"] == Decimal("0")  # only card + package that day
    assert p.by_day[d12]["fiscal_register"] == Decimal("75")
    assert p.by_day[d11]["booksy_cash"] == Decimal("105")  # cash
    assert p.by_day[d11]["fiscal_register"] == Decimal("255")  # 105 cash + 150 card


def test_parse_cash_transactions_empty_when_no_header() -> None:
    assert parse_cash_transactions([["", "nic"], ["", "tu"]]).by_day == {}
