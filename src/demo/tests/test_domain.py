"""VIN validation, finance math (known values + invariants), trade-in monotonicity, inventory."""

from __future__ import annotations

import json
import random
from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from chatbot.config import DATA_DIR
from chatbot.services.finance import (
    LeaseInput,
    PaymentInput,
    TradeInInput,
    estimate_lease,
    estimate_payment,
    estimate_trade_in,
)
from chatbot.services.inventory import InventoryRepository, SearchFilters
from chatbot.vin import find_vin, validate_vin

# --- VIN -----------------------------------------------------------------------------------


@pytest.mark.parametrize("vin", ["1HGCM82633A004352", "1M8GDM9AXKP042788", "11111111111111111"])
def test_valid_vins(vin):
    assert validate_vin(vin).valid


def test_vin_normalised():
    assert validate_vin(" 1hgcm8-2633a004352 ").vin == "1HGCM82633A004352"


@pytest.mark.parametrize(
    ("vin", "fragment"),
    [
        ("1HGCM82633A00435", "17 characters"),
        ("1HGCM82633A0043521", "17 characters"),
        ("1HGCM82633A00435O", "I, O or Q"),
        ("IHGCM82633A004352", "I, O or Q"),
        ("1HGCM82633A00435$", "I, O or Q"),
        ("1HGCM82643A004352", "check digit"),
    ],
)
def test_invalid_vins(vin, fragment):
    check = validate_vin(vin)
    assert not check.valid and fragment in check.reason


def test_find_vin_in_text():
    assert find_vin("my vin is 1hgcm82633a004352 thanks") == "1HGCM82633A004352"
    assert find_vin("no vin here, call 3345550142") is None


# --- payments ---------------------------------------------------------------------------------


def test_payment_known_value():
    out = estimate_payment(PaymentInput(price=30000, apr_percent=6, term_months=60))
    assert out["monthly_payment"] == "579.98"
    assert out["total_of_payments"] == "34798.80"


def test_zero_apr_is_straight_division():
    out = estimate_payment(PaymentInput(price=24000, apr_percent=0, term_months=48))
    assert out["monthly_payment"] == "500.00" and out["total_interest"] == "0.00"


def test_trade_in_credit_reduces_tax_and_principal():
    out = estimate_payment(PaymentInput(price=40000, trade_in_value=10000, trade_in_payoff=4000, down_payment=2000,
                                        apr_percent=5, term_months=60, sales_tax_percent=2))  # fmt: skip
    assert out["sales_tax"] == "600.00"  # 2% of (40000 - 10000)
    assert out["amount_financed"] == "32600.00"  # 40000 + 600 - 2000 - (10000 - 4000)


def test_fully_covered_purchase_finances_nothing():
    out = estimate_payment(PaymentInput(price=10000, down_payment=10000, apr_percent=5, term_months=36))
    assert out["monthly_payment"] == "0.00"


@pytest.mark.parametrize(
    "bad",
    [
        {"price": -1, "apr_percent": 5, "term_months": 60},
        {"price": 0, "apr_percent": 5, "term_months": 60},
        {"price": 30000, "apr_percent": 37, "term_months": 60},
        {"price": 30000, "apr_percent": 5, "term_months": 0},
        {"price": 30000, "apr_percent": 5, "term_months": 600},
        {"price": 30000, "apr_percent": 5, "term_months": 60, "down_payment": 50000},
        {"price": "1e400", "apr_percent": 5, "term_months": 60},
        {"price": "NaN", "apr_percent": 5, "term_months": 60},
    ],
)
def test_payment_rejects_absurd_input(bad):
    with pytest.raises(ValidationError):
        PaymentInput(**bad)


def test_payment_invariants_fuzz():
    rng = random.Random(7)
    for _ in range(300):
        price = Decimal(rng.randint(1000, 250000))
        data = PaymentInput(price=price, apr_percent=Decimal(rng.randint(0, 2400)) / 100, term_months=rng.randint(6, 96),
                            down_payment=Decimal(rng.randint(0, int(price))))  # fmt: skip
        out = estimate_payment(data)
        assert Decimal(out["monthly_payment"]) >= 0
        if "total_of_payments" in out:
            assert Decimal(out["total_of_payments"]) >= Decimal(out["amount_financed"]) - Decimal("1.00")


def test_lease_known_value():
    out = estimate_lease(LeaseInput(msrp=40000, selling_price=38000, residual_percent=60, money_factor=Decimal("0.0025"),
                                    term_months=36))  # fmt: skip
    assert out["depreciation_fee"] == "388.89"
    assert out["finance_fee"] == "155.00"
    assert out["monthly_payment"] == "543.89"


def test_lease_apr_converts_to_money_factor():
    out = estimate_lease(LeaseInput(msrp=40000, residual_percent=60, apr_percent=6, term_months=36))
    assert out["money_factor"] == "0.002500"


def test_lease_rejects_cap_below_residual_and_missing_rate():
    with pytest.raises(ValueError):
        estimate_lease(LeaseInput(msrp=40000, residual_percent=60, apr_percent=5, term_months=36, down_payment=20000))
    with pytest.raises(ValidationError):
        LeaseInput(msrp=40000, residual_percent=60, term_months=36)


# --- trade-in --------------------------------------------------------------------------------
TODAY = date(2026, 11, 5)


def _value(**kw) -> int:
    base = {"year": 2021, "make": "Honda", "mileage": 60000, "condition": "good"}
    return int(estimate_trade_in(TradeInInput(**(base | kw)), today=TODAY)["estimated_high"])


def test_trade_in_monotonic_in_mileage_age_condition_accident():
    assert _value(mileage=30000) > _value(mileage=60000) > _value(mileage=120000)
    assert _value(year=2024) > _value(year=2021) > _value(year=2015)
    assert (
        _value(condition="excellent") > _value(condition="good") > _value(condition="fair") > _value(condition="poor")
    )
    assert _value(accident_history=False) > _value(accident_history=True)


def test_trade_in_range_floor_and_disclaimer():
    out = estimate_trade_in(TradeInInput(year=1995, make="Ford", mileage=400000, condition="poor"), today=TODAY)
    assert int(out["estimated_low"]) >= 450 and int(out["estimated_low"]) <= int(out["estimated_high"])
    assert "Not a KBB" in out["disclaimer"]


def test_trade_in_rejects_future_year():
    with pytest.raises(ValueError):
        estimate_trade_in(TradeInInput(year=2030, make="Audi", mileage=10), today=TODAY)


def test_trade_in_brand_aliases_use_same_base():
    a = estimate_trade_in(TradeInInput(year=2022, make="mercedes", mileage=36000), today=TODAY)
    b = estimate_trade_in(TradeInInput(year=2022, make="Mercedes-Benz", mileage=36000), today=TODAY)
    assert a["estimated_high"] == b["estimated_high"]


# --- inventory --------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def inventory():
    return InventoryRepository(DATA_DIR / "inventory_sample.json")


def test_sample_feed_is_labelled(inventory):
    result = inventory.search(SearchFilters(limit=1))
    assert result["is_sample"] and "Sample" in result["notice"]
    assert len(inventory.vehicles) >= 50 and inventory.skipped == 0


def test_sample_vins_are_valid(inventory):
    assert all(validate_vin(v.vin).valid for v in inventory.vehicles.values())


def test_filters_compose(inventory):
    result = inventory.search(SearchFilters(make="vw", body_style="suv", max_price=45000, sort="price_asc", limit=20))
    assert result["vehicles"]
    prices = [v["price"] for v in result["vehicles"]]
    assert prices == sorted(prices) and max(prices) <= 45000
    assert {v["make"] for v in result["vehicles"]} == {"Volkswagen"}
    assert {v["body_style"] for v in result["vehicles"]} == {"SUV"}


def test_condition_fuel_and_year_filters(inventory):
    evs = inventory.search(SearchFilters(fuel_type="electric", limit=20))["vehicles"]
    assert evs and all(v["fuel_type"] == "Electric" for v in evs)
    used = inventory.search(SearchFilters(condition="used", min_year=2022, limit=20))["vehicles"]
    assert all(v["condition"] == "used" and v["year"] >= 2022 for v in used)


def test_query_tokens_and_no_match(inventory):
    assert inventory.search(SearchFilters(query="panoramic roof", limit=20))["total"] > 0
    assert inventory.search(SearchFilters(query="zzzz-nothing"))["total"] == 0


def test_search_limit_capped():
    with pytest.raises(ValidationError):
        SearchFilters(limit=21)


def test_compare_rules(inventory):
    stocks = list(inventory.vehicles)[:3]
    result = inventory.compare(stocks)
    assert len(result["vehicles"]) == 3 and result["lowest_price"] in stocks
    for v in result["vehicles"]:
        ctx = v["price_context"]
        assert ctx["comparable_units"] >= 1
        if "percentile" in ctx:
            assert 0 <= ctx["percentile"] <= 100
    with pytest.raises(ValueError):
        inventory.compare([stocks[0], stocks[0].lower()])  # duplicates collapse to one
    with pytest.raises(ValueError, match="Unknown"):
        inventory.compare([stocks[0], "NOPE-0000"])
    with pytest.raises(ValueError):
        inventory.compare(list(inventory.vehicles)[:5])


def test_offers_expire(inventory):
    assert inventory.current_offers(today=date(2026, 11, 5))["offers"]
    assert inventory.current_offers(today=date(2030, 1, 1))["offers"] == []


def test_invalid_feed_rows_skipped_not_fatal(tmp_path):
    good = json.loads((DATA_DIR / "inventory_sample.json").read_text())["vehicles"][0]
    feed = {"_meta": {"sample": False}, "vehicles": [good, {"stock_number": "BAD", "price": -5}], "offers": []}
    path = tmp_path / "feed.json"
    path.write_text(json.dumps(feed))
    repo = InventoryRepository(path)
    assert len(repo.vehicles) == 1 and repo.skipped == 1 and not repo.is_sample


def test_inventory_api(client):
    ok = client.get("/api/inventory/search", params={"make": "nissan", "limit": 3})
    assert ok.status_code == 200 and all(v["make"] == "Nissan" for v in ok.json()["vehicles"])
    assert client.get("/api/inventory/NOPE-1").status_code == 404
    assert client.get("/api/inventory/search", params={"q": "x" * 101}).status_code == 422
    stocks = [v["stock_number"] for v in ok.json()["vehicles"][:2]]
    assert client.post("/api/inventory/compare", json={"stock_numbers": stocks}).status_code == 200
    assert client.post("/api/inventory/compare", json={"stock_numbers": [stocks[0], "ZZ99-9999"]}).status_code == 422
