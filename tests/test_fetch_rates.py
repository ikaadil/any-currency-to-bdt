"""Tests for fetch_rates: schema validation and plausible rate ranges."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
RATES_JSON = ROOT / "rates.json"

# Expected structure from fetch_rates
REQUIRED_TOP_KEYS = {"updated_at", "target", "rates"}
REQUIRED_RATE_KEYS = {"provider", "url", "rate", "delivery", "fee"}
TARGET = "BDT"

# Plausible BDT per 1 unit (loose bounds to allow market moves)
PLAUSIBLE_RANGES = {
    "USD": (80, 150),
    "GBP": (140, 200),
    "EUR": (120, 170),
    "CAD": (75, 110),
    "AUD": (75, 110),
    "SGD": (85, 110),
    "AED": (25, 45),
    "MYR": (25, 40),
    "SAR": (28, 45),
    "KWD": (350, 450),
    "QAR": (28, 45),
    "JPY": (0.5, 2.0),
}


def load_rates() -> dict:
    """Load rates.json; raise if missing or invalid JSON."""
    if not RATES_JSON.exists():
        pytest.skip(f"{RATES_JSON} not found (run fetch_rates.py first)")
    return json.loads(RATES_JSON.read_text(encoding="utf-8"))


def test_rates_json_schema():
    """rates.json has required top-level keys and structure."""
    data = load_rates()
    assert set(data.keys()) >= REQUIRED_TOP_KEYS, "Missing required top-level keys"
    assert data["target"] == TARGET
    assert isinstance(data["rates"], dict)
    for code, entries in data["rates"].items():
        assert isinstance(entries, list), f"rates.{code} must be a list"
        for i, r in enumerate(entries):
            assert isinstance(r, dict), f"rates.{code}[{i}] must be a dict"
            assert set(r.keys()) >= REQUIRED_RATE_KEYS, f"rates.{code}[{i}] missing keys"
            assert isinstance(r["provider"], str)
            assert isinstance(r["url"], str)
            assert isinstance(r["rate"], (int, float))
            assert isinstance(r["delivery"], str)
            assert r["fee"] is None or isinstance(r["fee"], (int, float))


def test_rates_json_updated_at_format():
    """updated_at is ISO format with timezone."""
    data = load_rates()
    raw = data["updated_at"]
    assert "T" in raw and "Z" in raw or "+" in raw or "-" in raw[-6:]


def test_rates_plausible_ranges():
    """Each currency's rates fall in plausible BDT-per-unit ranges."""
    data = load_rates()
    for code, (low, high) in PLAUSIBLE_RANGES.items():
        entries = data["rates"].get(code, [])
        for r in entries:
            rate = r["rate"]
            assert low <= rate <= high, (
                f"{r['provider']} {code}->BDT rate {rate} outside [{low}, {high}]"
            )


def test_rates_sorted_descending():
    """Rates per currency are sorted by rate descending (best first)."""
    data = load_rates()
    for code, entries in data["rates"].items():
        rates = [r["rate"] for r in entries]
        assert rates == sorted(rates, reverse=True), (
            f"rates.{code} not sorted by rate descending"
        )


def test_at_least_some_providers_for_usd():
    """USD has at least a few providers (Wise, Xe, etc.) so the pipeline is working."""
    data = load_rates()
    usd = data["rates"].get("USD", [])
    providers = {r["provider"] for r in usd}
    # Expect at least Wise and one of Xe/Remitly/SendWave
    assert "Wise" in providers, "USD should include Wise"
    assert len(providers) >= 3, "USD should have at least 3 providers"


def test_total_rates_reasonable():
    """Total number of rates is in a reasonable range (not empty, not tiny)."""
    data = load_rates()
    total = sum(len(v) for v in data["rates"].values())
    assert total >= 20, "Expected at least 20 rates across all currencies"
    assert total <= 500, "Unexpectedly high rate count"


def test_fee_field_present_on_all_entries():
    """Every rate entry has a 'fee' key (null or number)."""
    data = load_rates()
    for code, entries in data["rates"].items():
        for i, r in enumerate(entries):
            assert "fee" in r, f"rates.{code}[{i}] missing 'fee' key"
            assert r["fee"] is None or isinstance(
                r["fee"], (int, float)
            ), f"rates.{code}[{i}].fee must be null or number"


def test_at_least_one_provider_has_fees():
    """At least one provider reports fees (SendWave API provides baseFeeAmount)."""
    data = load_rates()
    with_fee = [
        (code, r["provider"], r["fee"])
        for code, entries in data["rates"].items()
        for r in entries
        if r.get("fee") is not None
    ]
    assert len(with_fee) >= 1, (
        "Expected at least one rate with fee (e.g. SendWave). "
        "Fee pipeline may be broken or no fee-returning provider succeeded."
    )


def test_sendwave_entries_have_fee_when_present():
    """SendWave uses an API that returns baseFeeAmount; their entries should have fee set."""
    data = load_rates()
    sendwave_entries = [
        r for entries in data["rates"].values() for r in entries if r["provider"] == "SendWave"
    ]
    if not sendwave_entries:
        pytest.skip("No SendWave rates in this run")
    missing_fee = [r for r in sendwave_entries if r.get("fee") is None]
    assert not missing_fee, (
        f"SendWave entries should have fee (API returns baseFeeAmount): {len(missing_fee)} missing"
    )


def test_fetch_all_produces_valid_structure():
    """Integration: fetch_all() returns the same structure we expect in rates.json."""
    from fetch_rates import fetch_all, CURRENCIES, TARGET
    import asyncio

    data = asyncio.run(fetch_all())
    assert set(data.keys()) >= REQUIRED_TOP_KEYS
    assert data["target"] == TARGET
    assert "rates" in data
    currency_codes = {c[0] for c in CURRENCIES}
    assert set(data["rates"].keys()) == currency_codes
    for code, entries in data["rates"].items():
        for r in entries:
            assert set(r.keys()) >= {"provider", "url", "rate", "delivery", "fee"}
            assert isinstance(r["rate"], (int, float))
    total = sum(len(v) for v in data["rates"].values())
    assert total >= 20, "fetch_all() should return at least 20 rates"
