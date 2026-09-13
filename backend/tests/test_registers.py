"""Booksy cash-registers parser: derive daily gotówka + kasa fiskalna from
closed till sessions (by closing date; open sessions ignored)."""

from datetime import date
from decimal import Decimal

from app.registers import parse_cash_registers

_HDR = [
    "",
    "",
    "Status",
    "Otwarty",
    "Zamknięty",
    "Kasjer",
    "Gotówka przy otwarciu",
    "Stan oczek (got)",
    "Stan rzecz (got)",
    "Różnica",
    "Stan oczek (inne)",
    "Stan rzecz (inne)",
    "Różnica",
    "Razem",
]


def _row(idx, status, closed, open_cash, close_cash, other, total):
    return [
        "",
        idx,
        status,
        "x",
        closed,
        "K",
        open_cash,
        close_cash,
        close_cash,
        "0",
        other,
        other,
        "0",
        total,
    ]


def test_parse_cash_registers_derives_cash_and_fiscal() -> None:
    grid = [
        ["", "Zestawienie rejestrów kasowych"],
        _HDR,
        _row("1", "Zamknięty", "3.09.2026 19:00", "177.20", "252.20", "880", "1132.20"),
        _row(
            "2", "Zamknięty", "3.09.2026 20:30", "252.20", "252.20", "120", "372.20"
        ),  # 2nd session same day
        _row("3", "Otwarty", "", "100", "", "", ""),  # open → skipped
    ]
    p = parse_cash_registers(grid)
    assert p.sessions == 2
    d = date(2026, 9, 3)
    # session1 cash 75 (252.20-177.20) + session2 cash 0 → 75
    assert p.by_day[d]["booksy_cash"] == Decimal("75.00")
    # session1 fiscal 955 (1132.20-177.20) + session2 fiscal 120 (372.20-252.20) → 1075
    assert p.by_day[d]["fiscal_register"] == Decimal("1075.00")


def test_parse_cash_registers_empty_when_no_header() -> None:
    assert parse_cash_registers([["", "nic"], ["", "tu"]]).by_day == {}
