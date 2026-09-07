"""The commission engine, pinned to the REAL Prowizja.xlsx numbers.

Each fixture is a real employee-month from the spreadsheet. The engine must
reproduce the sheet's own computed commission (services + sales + hours) — with
two deliberate divergences per the owner's decision log:
  - Hania: the sheet's formula is buggy (shifted brackets → 234.85); the
    corrected FTE-scaled model gives 201.30. The engine implements the ruling.
  - Rounding: the sheet leaves grosze; the owner wants the TOTAL rounded up to
    the whole złoty, so total_payout is ceil(components).
"""

from decimal import Decimal

from app.commission import CommissionScheme, SettlementInput, compute_settlement, services_rate


def scheme(fte: str) -> CommissionScheme:
    return CommissionScheme(fte_factor=Decimal(fte))


# --- real employee-months (services base broken into Booksy/notebook/cash) ---
def test_klaudia_fulltime_top_bracket_plus_hours() -> None:
    # Booksy 10415 + zeszyt 400 + gotówka 3335 = 14150 services; 70 sales; 10h.
    inp = SettlementInput(
        booksy_services=Decimal("10415"),
        notebook_services=Decimal("400"),
        cash_services=Decimal("3335"),
        booksy_sales=Decimal("70"),
        hours=Decimal("10"),
    )
    r = compute_settlement(inp, scheme("1.0"))
    assert r.services_base == Decimal("14150")
    assert r.services_rate == Decimal("0.10")  # >= 10000
    assert r.services_commission == Decimal("1415.00")
    assert r.sales_commission == Decimal("0")  # 70 < 1500
    assert r.hours_pay == Decimal("314.00")  # 10 * 31.40
    assert r.total_payout == Decimal("1729")  # 1415 + 314, already whole


def test_karola_fulltime_rounds_up() -> None:
    inp = SettlementInput(
        booksy_services=Decimal("10400"),
        notebook_services=Decimal("180"),
        cash_services=Decimal("2569"),
        booksy_sales=Decimal("416"),
    )
    r = compute_settlement(inp, scheme("1.0"))
    assert r.services_base == Decimal("13149")
    assert r.services_commission == Decimal("1314.90")
    assert r.total_payout == Decimal("1315")  # ceil(1314.90) — the owner's example


def test_oliwia_crosses_into_the_new_12pct_bracket() -> None:
    # Same 15164 services the sheet computed at 10% (1516.40) — but under the
    # 2026-09 rule (>15000 → 12%) she now earns 12%. This is the rule change in
    # action, and exactly why closed periods freeze their scheme.
    inp = SettlementInput(
        booksy_services=Decimal("12584"),
        notebook_services=Decimal("360"),
        cash_services=Decimal("2220"),
        booksy_sales=Decimal("65"),
    )
    r = compute_settlement(inp, scheme("1.0"))
    assert r.services_base == Decimal("15164")
    assert r.services_rate == Decimal("0.12")  # >= 15000
    assert r.services_commission == Decimal("1819.68")  # was 1516.40 at 10%
    assert r.total_payout == Decimal("1820")


def test_julia_historical_075_scheme() -> None:
    # Julia was 0.75 FTE for this month (she has since moved to full time). The
    # engine reproduces the historical sheet: 5689 in [5250,6000)·0.75 → 7%.
    inp = SettlementInput(
        booksy_services=Decimal("4540"),
        notebook_services=Decimal("1149"),
        booksy_sales=Decimal("639"),
    )
    r = compute_settlement(inp, scheme("0.75"))
    assert r.services_base == Decimal("5689")
    assert r.services_rate == Decimal("0.07")
    assert r.services_commission == Decimal("398.23")
    assert r.total_payout == Decimal("399")  # ceil(398.23)


def test_hania_half_fte_corrected_not_the_sheet_bug() -> None:
    # fte 0.5 → boundaries 3000/3500/...; 3355 lands in [3000,3500) → 6%.
    # The sheet's buggy formula returned 7% (234.85); the ruling says the table
    # (FTE-scaled) wins → 6% → 201.30.
    inp = SettlementInput(
        booksy_services=Decimal("2410"),
        notebook_services=Decimal("310"),
        cash_services=Decimal("635"),
        booksy_sales=Decimal("105"),
    )
    r = compute_settlement(inp, scheme("0.5"))
    assert r.services_base == Decimal("3355")
    assert r.services_rate == Decimal("0.06")
    assert r.services_commission == Decimal("201.30")
    assert r.services_commission != Decimal("234.85")  # NOT the spreadsheet bug
    assert r.total_payout == Decimal("202")


# --- rules not exercised by these particular months, pinned synthetically ----
def test_sales_threshold_boundary() -> None:
    s = scheme("1.0")
    assert compute_settlement(
        SettlementInput(booksy_sales=Decimal("1499")), s
    ).sales_commission == Decimal("0")
    assert compute_settlement(
        SettlementInput(booksy_sales=Decimal("1499.99")), s
    ).sales_commission == Decimal("0")
    # 1500 → 10% of the whole; owner's example 1541 → 154.10
    assert compute_settlement(
        SettlementInput(booksy_sales=Decimal("1500")), s
    ).sales_commission == Decimal("150.00")
    assert compute_settlement(
        SettlementInput(booksy_sales=Decimal("1541")), s
    ).sales_commission == Decimal("154.10")


def test_below_floor_pays_zero_services() -> None:
    # Just under 6000 (full-time floor) → 0% services.
    r = compute_settlement(SettlementInput(booksy_services=Decimal("5999.99")), scheme("1.0"))
    assert r.services_rate == Decimal("0")
    assert r.services_commission == Decimal("0")
    assert r.total_payout == Decimal("0")


def test_services_rate_is_slab_on_whole_amount() -> None:
    # 9500 @ 9% applies to the WHOLE 9500, not just the slice above 9000.
    r = compute_settlement(SettlementInput(booksy_services=Decimal("9500")), scheme("1.0"))
    assert r.services_rate == Decimal("0.09")
    assert r.services_commission == Decimal("855.00")  # 9500 * 0.09, not (9500-9000)*...


def test_bracket_boundaries_are_inclusive_lower() -> None:
    s = scheme("1.0")
    assert services_rate(Decimal("6999.99"), s) == Decimal("0.06")
    assert services_rate(Decimal("7000"), s) == Decimal(
        "0.07"
    )  # exactly at boundary → next bracket
    assert services_rate(Decimal("10000"), s) == Decimal("0.10")
    assert services_rate(Decimal("14999.99"), s) == Decimal("0.10")
    assert services_rate(Decimal("15000"), s) == Decimal("0.12")  # new top bracket


def test_new_12pct_bracket_scales_with_fte() -> None:
    # For a half-timer the 12% floor is 15000·0.5 = 7500.
    half = scheme("0.5")
    assert services_rate(Decimal("7499.99"), half) == Decimal("0.10")
    assert services_rate(Decimal("7500"), half) == Decimal("0.12")


def test_prepaid_and_cash_join_services_base() -> None:
    # rulings #7/#8: cash + notebook both add to the SERVICES base.
    inp = SettlementInput(
        booksy_services=Decimal("5000"),
        notebook_services=Decimal("600"),  # pushes 5000 → 5600, still < 6000 → 0%
        cash_services=Decimal("500"),  # → 6100, now ≥ 6000 → 6%
    )
    r = compute_settlement(inp, scheme("1.0"))
    assert r.services_base == Decimal("6100")
    assert r.services_rate == Decimal("0.06")
    assert r.services_commission == Decimal("366.00")
