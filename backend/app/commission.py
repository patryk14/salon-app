"""Commission & payout engine — a pure function over an explicit input snapshot.

This is the core the whole portal grows around, so it is deliberately
DB-free and side-effect-free: it takes numbers, returns numbers, and every
rule is traceable to the owner's decision log (PORTAL-PLAN.md §"Decision log").

The model, reverse-engineered from the real Prowizja.xlsx formulas and then
corrected per the owner's rulings:

Services commission — a SLAB, not a marginal/tiered rate. The ENTIRE services
revenue is multiplied by the single rate of the bracket it lands in. Base
bracket boundaries (full-time) step by 1000; each employee's boundaries are the
base × their FTE factor (Hania 0.5, Julia 0.75, full-timers 1.0):

    revenue < 6000·f           → 0%
    6000·f  ≤ revenue < 7000·f  → 6%
    7000·f  ≤ revenue < 8000·f  → 7%
    8000·f  ≤ revenue < 9000·f  → 8%
    9000·f  ≤ revenue < 10000·f → 9%
    10000·f ≤ revenue < 15000·f → 10%
    revenue ≥ 15000·f           → 12%   (owner addition, 2026-09)

Sales commission: revenue ≥ 1500 PLN → 10% of the whole amount, else 0.
Hours pay: logged_hours × 31.40 PLN/h (for Klaudia, only her extra hours; her
UoP base salary is the accountant's, outside this app).
Payout = ceil(services + sales + hours) to the whole złoty (always rounded up).
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

# Base services brackets (FTE 1.0): (lower_bound, rate), ascending. Boundaries
# scale by the employee's FTE factor at compute time — change this one table and
# every scheme follows (owner ruling #6). The <6000 floor (0%) is implicit.
BASE_SERVICES_BRACKETS: list[tuple[Decimal, Decimal]] = [
    (Decimal("6000"), Decimal("0.06")),
    (Decimal("7000"), Decimal("0.07")),
    (Decimal("8000"), Decimal("0.08")),
    (Decimal("9000"), Decimal("0.09")),
    (Decimal("10000"), Decimal("0.10")),
    (Decimal("15000"), Decimal("0.12")),  # owner addition 2026-09: >15000 → 12%
]
SALES_THRESHOLD = Decimal("1500")  # owner ruling #2: >= 1500 → 10% of the whole
SALES_RATE = Decimal("0.10")
DEFAULT_HOURLY_RATE = Decimal("31.40")


def _d(value) -> Decimal:
    """Money in as Decimal, never float (0.1 is not 0.1 in binary)."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


@dataclass(frozen=True)
class CommissionScheme:
    """What an employee is paid ON — effective-dated in the DB, frozen into each
    settlement_line at close so a later rule change never rewrites history."""

    fte_factor: Decimal = Decimal("1.0")
    # Base (full-time) brackets; scaled by fte_factor at compute.
    services_brackets: tuple[tuple[Decimal, Decimal], ...] = tuple(BASE_SERVICES_BRACKETS)
    sales_threshold: Decimal = SALES_THRESHOLD
    sales_rate: Decimal = SALES_RATE
    hourly_rate: Decimal = DEFAULT_HOURLY_RATE


@dataclass(frozen=True)
class SettlementInput:
    """One employee's numbers for one period. Services/sales bases are summed
    across the three revenue sources (Booksy + prepaid notebook + cash) —
    prepaid packages and cash both count toward the SERVICES base (rulings
    #7, #8), packages at their discounted price (#9)."""

    booksy_services: Decimal = Decimal("0")
    booksy_sales: Decimal = Decimal("0")
    notebook_services: Decimal = Decimal("0")  # "Pakiety - zeszyt"
    cash_services: Decimal = Decimal("0")  # "Gotówka"
    notebook_sales: Decimal = Decimal("0")
    cash_sales: Decimal = Decimal("0")
    hours: Decimal = Decimal("0")

    @property
    def services_base(self) -> Decimal:
        return _d(self.booksy_services) + _d(self.notebook_services) + _d(self.cash_services)

    @property
    def sales_base(self) -> Decimal:
        return _d(self.booksy_sales) + _d(self.notebook_sales) + _d(self.cash_sales)


@dataclass(frozen=True)
class SettlementResult:
    services_base: Decimal
    sales_base: Decimal
    services_rate: Decimal
    services_commission: Decimal
    sales_commission: Decimal
    hours_pay: Decimal
    total_payout: Decimal  # rounded up to the whole złoty


def services_rate(services_base: Decimal, scheme: CommissionScheme) -> Decimal:
    """The single slab rate for this revenue — highest bracket whose FTE-scaled
    lower bound is reached; 0 below the first bracket."""
    base = _d(services_base)
    fte = _d(scheme.fte_factor)
    rate = Decimal("0")
    for boundary, r in scheme.services_brackets:
        if base >= _d(boundary) * fte:
            rate = _d(r)
    return rate


def compute_settlement(inp: SettlementInput, scheme: CommissionScheme) -> SettlementResult:
    services_base = inp.services_base
    sales_base = inp.sales_base

    rate = services_rate(services_base, scheme)
    services_commission = services_base * rate

    sales_commission = (
        sales_base * _d(scheme.sales_rate)
        if sales_base >= _d(scheme.sales_threshold)
        else Decimal("0")
    )
    hours_pay = _d(inp.hours) * _d(scheme.hourly_rate)

    raw_total = services_commission + sales_commission + hours_pay
    # Owner ruling #4: always round UP to the full złoty.
    total_payout = raw_total.quantize(Decimal("1"), rounding=ROUND_CEILING)

    return SettlementResult(
        services_base=services_base,
        sales_base=sales_base,
        services_rate=rate,
        services_commission=services_commission,
        sales_commission=sales_commission,
        hours_pay=hours_pay,
        total_payout=total_payout,
    )
