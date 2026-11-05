"""Payment, lease and trade-in estimators (Decimal arithmetic, cent-exact rounding).

These are planning estimates, not offers of credit. The trade-in model is a transparent
depreciation heuristic, NOT a Kelley Blue Book / Black Book / J.D. Power valuation; swap in a
licensed valuation API for production quotes.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from ..knowledge import canonical_brand

CENT = Decimal("0.01")
PAYMENT_DISCLAIMER = (
    "Estimate only. Excludes title, registration and dealer fees unless included above; sales tax is included only"
    " if a rate was provided. Actual APR and terms depend on credit approval."
)
TRADE_DISCLAIMER = (
    "Heuristic planning estimate based on age, mileage and condition. Not a KBB, Black Book or J.D. Power value;"
    " the final offer requires an in-person appraisal."
)


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def amortized_payment(principal: Decimal, apr_percent: Decimal, months: int) -> Decimal:
    if principal <= 0:
        return Decimal("0.00")
    rate = apr_percent / Decimal(1200)
    if rate == 0:
        return _money(principal / months)
    factor = (1 + rate) ** months
    return _money(principal * rate * factor / (factor - 1))


class PaymentInput(BaseModel):
    price: Decimal = Field(gt=0, le=2_000_000)
    down_payment: Decimal = Field(default=Decimal(0), ge=0)
    trade_in_value: Decimal = Field(default=Decimal(0), ge=0)
    trade_in_payoff: Decimal = Field(default=Decimal(0), ge=0)
    apr_percent: Decimal = Field(ge=0, le=36)
    term_months: int = Field(ge=6, le=96)
    sales_tax_percent: Decimal = Field(default=Decimal(0), ge=0, le=15)
    fees: Decimal = Field(default=Decimal(0), ge=0, le=20_000)

    @model_validator(mode="after")
    def _sane(self) -> PaymentInput:
        if self.down_payment > self.price + self.fees:
            raise ValueError("down payment is larger than the purchase price")
        if self.trade_in_payoff > 2_000_000 or self.trade_in_value > 2_000_000:
            raise ValueError("trade-in amounts out of range")
        return self


def estimate_payment(data: PaymentInput) -> dict[str, Any]:
    net_trade = data.trade_in_value - data.trade_in_payoff
    taxable = max(Decimal(0), data.price - data.trade_in_value)  # trade-in credit reduces taxable amount
    tax = _money(taxable * data.sales_tax_percent / 100)
    financed = _money(data.price + tax + data.fees - data.down_payment - net_trade)
    if financed <= 0:
        return {
            "amount_financed": "0.00",
            "monthly_payment": "0.00",
            "note": "Down payment and trade-in cover the full amount; nothing to finance.",
            "disclaimer": PAYMENT_DISCLAIMER,
        }
    payment = amortized_payment(financed, data.apr_percent, data.term_months)
    total = _money(payment * data.term_months)
    return {
        "amount_financed": str(financed),
        "sales_tax": str(tax),
        "monthly_payment": str(payment),
        "term_months": data.term_months,
        "apr_percent": str(data.apr_percent),
        "total_of_payments": str(total),
        "total_interest": str(_money(total - financed)),
        "disclaimer": PAYMENT_DISCLAIMER,
    }


class LeaseInput(BaseModel):
    msrp: Decimal = Field(gt=0, le=2_000_000)
    selling_price: Decimal | None = Field(default=None, gt=0)
    residual_percent: Decimal = Field(ge=20, le=90)
    money_factor: Decimal | None = Field(default=None, ge=0, le=Decimal("0.01"))
    apr_percent: Decimal | None = Field(default=None, ge=0, le=24)
    term_months: int = Field(ge=12, le=60)
    down_payment: Decimal = Field(default=Decimal(0), ge=0)
    trade_in_value: Decimal = Field(default=Decimal(0), ge=0)
    acquisition_fee: Decimal = Field(default=Decimal(0), ge=0, le=5_000)
    sales_tax_percent: Decimal = Field(default=Decimal(0), ge=0, le=15)

    @model_validator(mode="after")
    def _rate(self) -> LeaseInput:
        if self.money_factor is None and self.apr_percent is None:
            raise ValueError("provide money_factor or apr_percent")
        return self


def estimate_lease(data: LeaseInput) -> dict[str, Any]:
    money_factor = data.money_factor if data.money_factor is not None else data.apr_percent / Decimal(2400)
    gross_cap = (data.selling_price or data.msrp) + data.acquisition_fee
    cap_cost = gross_cap - data.down_payment - data.trade_in_value
    residual = _money(data.msrp * data.residual_percent / 100)
    if cap_cost <= residual:
        raise ValueError("capitalized cost after down payment is below the residual value")
    depreciation = _money((cap_cost - residual) / data.term_months)
    finance_charge = _money((cap_cost + residual) * money_factor)
    base = depreciation + finance_charge
    tax = _money(base * data.sales_tax_percent / 100)
    return {
        "monthly_payment": str(_money(base + tax)),
        "depreciation_fee": str(depreciation),
        "finance_fee": str(finance_charge),
        "monthly_tax": str(tax),
        "residual_value": str(residual),
        "adjusted_cap_cost": str(_money(cap_cost)),
        "money_factor": str(money_factor.quantize(Decimal("0.000001"))),
        "approx_apr_percent": str((money_factor * 2400).quantize(Decimal("0.01"))),
        "term_months": data.term_months,
        "disclaimer": PAYMENT_DISCLAIMER
        + " Lease terms (residual, money factor, mileage allowance) come from the lender.",
    }


# --- trade-in heuristic ----------------------------------------------------------------------
TYPICAL_NEW_PRICE = {
    "nissan": 33000, "volkswagen": 36000, "volvo": 55000, "audi": 56000, "mercedes-benz": 66000,
    "porsche": 110000, "toyota": 36000, "honda": 34000, "ford": 46000, "chevrolet": 44000,
    "gmc": 55000, "ram": 52000, "jeep": 45000, "hyundai": 33000, "kia": 32000, "subaru": 34000,
    "mazda": 33000, "bmw": 64000, "lexus": 58000, "tesla": 52000,
}  # fmt: skip
DEFAULT_NEW_PRICE = 40000
CONDITION_FACTOR = {
    "excellent": Decimal("1.05"),
    "good": Decimal("1.00"),
    "fair": Decimal("0.87"),
    "poor": Decimal("0.70"),
}


class TradeInInput(BaseModel):
    year: int = Field(ge=1990, le=2100)
    make: str = Field(min_length=2, max_length=40)
    model: str | None = Field(default=None, max_length=40)
    mileage: int = Field(ge=0, le=500_000)
    condition: Literal["excellent", "good", "fair", "poor"] = "good"
    accident_history: bool = False
    original_msrp: Decimal | None = Field(default=None, gt=1000, le=2_000_000)


def estimate_trade_in(data: TradeInInput, *, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    if data.year > today.year + 1:
        raise ValueError("model year is in the future")
    age = max(0, today.year - data.year)
    make_key = (canonical_brand(data.make) or data.make).strip().lower()
    base = data.original_msrp or Decimal(TYPICAL_NEW_PRICE.get(make_key, DEFAULT_NEW_PRICE))
    value = Decimal(base)
    for year_index in range(age):  # ~20% year one, ~15%/yr to year five, ~10%/yr after
        value *= Decimal("0.80") if year_index == 0 else (Decimal("0.85") if year_index < 5 else Decimal("0.90"))
    expected_miles = 12000 * max(age, 1)
    mileage_delta = Decimal(data.mileage - expected_miles) / Decimal(12000)
    mileage_adj = max(Decimal("-0.35"), min(Decimal("0.10"), -mileage_delta * Decimal("0.03")))
    value *= 1 + mileage_adj
    value *= CONDITION_FACTOR[data.condition]
    if data.accident_history:
        value *= Decimal("0.88")
    trade = max(Decimal(500), value * Decimal("0.88"))  # wholesale vs retail spread
    low, high = _money(trade * Decimal("0.92")), _money(trade * Decimal("1.08"))
    return {
        "estimated_low": str(low.quantize(Decimal(1))),
        "estimated_high": str(high.quantize(Decimal(1))),
        "basis": {
            "age_years": age,
            "assumed_new_price": str(Decimal(base).quantize(Decimal(1))),
            "msrp_source": "customer" if data.original_msrp else "typical price for make (approximate)",
            "mileage_vs_expected": data.mileage - expected_miles,
            "condition": data.condition,
            "accident_history": data.accident_history,
        },
        "disclaimer": TRADE_DISCLAIMER,
    }
