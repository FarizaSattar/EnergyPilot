"""
Tests for Ontario electricity-rate calculations.

These tests focus on deterministic tariff behaviour rather than implementation
details. If Ontario Energy Board (OEB) rates change, the expected values in
these tests should be updated together with the rate configuration.

The tests intentionally use timezone-aware timestamps where possible because
TOU/ULO periods are based on Ontario local time.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tariffs.ontario_rates import (
    InvalidRateInputError,
    calculate_cost,
    estimate_plan_costs,
    estimate_tou,
    estimate_ulo,
    get_current_electricity_rates,
    get_rate,
    get_tou_rate,
    get_ulo_rate,
    is_ontario_holiday,
    season_for_timestamp,
    tier_threshold,
    tiered_cost,
    tou_cost,
    tou_period,
    ulo_cost,
    ulo_period,
)


ONTARIO = ZoneInfo("America/Toronto")


# =============================================================================
# Helpers
# =============================================================================

def ontario_datetime(
    year: int,
    month: int,
    day: int,
    hour: int,
) -> datetime:
    """Create a timezone-aware Ontario timestamp for tariff tests."""
    return datetime(
        year,
        month,
        day,
        hour,
        tzinfo=ONTARIO,
    )


# =============================================================================
# TOU period tests
# =============================================================================

def test_tou_summer_mid_peak_morning() -> None:
    """Summer weekdays from 07:00 to 11:00 should be mid-peak."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        10,
    )

    assert tou_period(ts) == "mid_peak"


def test_tou_summer_on_peak_afternoon() -> None:
    """Summer weekdays from 11:00 to 17:00 should be on-peak."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    assert tou_period(ts) == "on_peak"


def test_tou_summer_mid_peak_evening() -> None:
    """Summer weekdays from 17:00 to 19:00 should be mid-peak."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        18,
    )

    assert tou_period(ts) == "mid_peak"


def test_tou_summer_off_peak_overnight() -> None:
    """Summer weekdays before 07:00 and after 19:00 should be off-peak."""
    assert (
        tou_period(
            ontario_datetime(2026, 9, 2, 6)
        )
        == "off_peak"
    )

    assert (
        tou_period(
            ontario_datetime(2026, 9, 2, 22)
        )
        == "off_peak"
    )


def test_tou_winter_on_peak_morning() -> None:
    """Winter weekdays from 07:00 to 11:00 should be on-peak."""
    ts = ontario_datetime(
        2026,
        12,
        2,
        9,
    )

    assert tou_period(ts) == "on_peak"


def test_tou_winter_mid_peak_afternoon() -> None:
    """Winter weekdays from 11:00 to 17:00 should be mid-peak."""
    ts = ontario_datetime(
        2026,
        12,
        2,
        14,
    )

    assert tou_period(ts) == "mid_peak"


def test_tou_winter_on_peak_evening() -> None:
    """Winter weekdays from 17:00 to 19:00 should be on-peak."""
    ts = ontario_datetime(
        2026,
        12,
        2,
        18,
    )

    assert tou_period(ts) == "on_peak"


def test_tou_weekend_is_off_peak_all_day() -> None:
    """TOU weekends should be off-peak regardless of time."""
    saturday = ontario_datetime(
        2026,
        9,
        5,
        14,
    )

    sunday = ontario_datetime(
        2026,
        9,
        6,
        18,
    )

    assert tou_period(saturday) == "off_peak"
    assert tou_period(sunday) == "off_peak"


def test_tou_holiday_is_off_peak() -> None:
    """A configured Ontario holiday should be off-peak all day."""
    canada_day = ontario_datetime(
        2026,
        7,
        1,
        14,
    )

    assert is_ontario_holiday(canada_day)
    assert tou_period(canada_day) == "off_peak"


# =============================================================================
# TOU cost tests
# =============================================================================

def test_tou_cost_uses_correct_summer_on_peak_rate() -> None:
    """10 kWh during summer on-peak should use 20.3¢/kWh."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    assert tou_cost(
        10,
        ts,
    ) == pytest.approx(
        2.03
    )


def test_tou_cost_uses_correct_mid_peak_rate() -> None:
    """10 kWh during mid-peak should use 15.7¢/kWh."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        10,
    )

    assert tou_cost(
        10,
        ts,
    ) == pytest.approx(
        1.57
    )


def test_tou_cost_uses_correct_off_peak_rate() -> None:
    """10 kWh during off-peak should use 9.8¢/kWh."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        22,
    )

    assert tou_cost(
        10,
        ts,
    ) == pytest.approx(
        0.98
    )


def test_zero_energy_has_zero_cost() -> None:
    """Zero consumption should produce zero energy cost."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    assert tou_cost(
        0,
        ts,
    ) == pytest.approx(0.0)


# =============================================================================
# ULO tests
# =============================================================================

def test_ulo_overnight_period() -> None:
    """ULO overnight should apply from 23:00 through 07:00."""
    assert (
        ulo_period(
            ontario_datetime(2026, 9, 2, 23)
        )
        == "overnight"
    )

    assert (
        ulo_period(
            ontario_datetime(2026, 9, 2, 3)
        )
        == "overnight"
    )


def test_ulo_weekday_on_peak() -> None:
    """ULO weekday 16:00–21:00 should be on-peak."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        18,
    )

    assert ulo_period(ts) == "on_peak"


def test_ulo_weekday_mid_peak() -> None:
    """ULO weekday daytime shoulder periods should be mid-peak."""
    assert (
        ulo_period(
            ontario_datetime(2026, 9, 2, 10)
        )
        == "mid_peak"
    )

    assert (
        ulo_period(
            ontario_datetime(2026, 9, 2, 22)
        )
        == "mid_peak"
    )


def test_ulo_weekend_daytime_is_weekend_off_peak() -> None:
    """ULO weekend daytime should use the weekend off-peak period."""
    ts = ontario_datetime(
        2026,
        9,
        5,
        14,
    )

    assert ulo_period(ts) == "weekend_off_peak"


def test_ulo_cost_uses_overnight_rate() -> None:
    """10 kWh overnight should use 3.9¢/kWh."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        2,
    )

    assert ulo_cost(
        10,
        ts,
    ) == pytest.approx(
        0.39
    )


# =============================================================================
# Tiered pricing tests
# =============================================================================

def test_residential_summer_tier_threshold() -> None:
    """Residential summer Tier 1 threshold should be 600 kWh."""
    ts = ontario_datetime(
        2026,
        7,
        1,
        12,
    )

    assert tier_threshold(ts) == pytest.approx(
        600.0
    )


def test_residential_winter_tier_threshold() -> None:
    """Residential winter Tier 1 threshold should be 1,000 kWh."""
    ts = ontario_datetime(
        2026,
        12,
        1,
        12,
    )

    assert tier_threshold(ts) == pytest.approx(
        1000.0
    )


def test_non_residential_tier_threshold() -> None:
    """Non-residential Tier 1 threshold should be 750 kWh."""
    ts = ontario_datetime(
        2026,
        7,
        1,
        12,
    )

    assert tier_threshold(
        ts,
        customer_type="non_residential",
    ) == pytest.approx(
        750.0
    )


def test_tiered_cost_within_first_tier() -> None:
    """Usage below the threshold should only use Tier 1."""
    ts = ontario_datetime(
        2026,
        7,
        1,
        12,
    )

    # 500 kWh × $0.120/kWh = $60.00
    assert tiered_cost(
        500,
        ts,
    ) == pytest.approx(
        60.00
    )


def test_tiered_cost_crosses_first_tier() -> None:
    """Usage above the threshold should split correctly between tiers."""
    ts = ontario_datetime(
        2026,
        7,
        1,
        12,
    )

    # 600 × $0.120 + 100 × $0.142 = $86.20
    assert tiered_cost(
        700,
        ts,
    ) == pytest.approx(
        86.20
    )


# =============================================================================
# Generic API tests
# =============================================================================

def test_get_rate_returns_tou_rate() -> None:
    """Generic rate lookup should dispatch to TOU pricing."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    rate = get_rate(
        "tou",
        ts,
    )

    assert rate.plan == "TOU"
    assert rate.period == "on_peak"
    assert rate.rate_cad_per_kwh == pytest.approx(
        0.203
    )


def test_get_rate_returns_ulo_rate() -> None:
    """Generic rate lookup should dispatch to ULO pricing."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        2,
    )

    rate = get_rate(
        "ulo",
        ts,
    )

    assert rate.plan == "ULO"
    assert rate.period == "overnight"
    assert rate.rate_cad_per_kwh == pytest.approx(
        0.039
    )


def test_calculate_cost_dispatches_to_tou() -> None:
    """Generic cost calculation should use the requested plan."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    assert calculate_cost(
        10,
        ts,
        plan="tou",
    ) == pytest.approx(
        2.03
    )


# =============================================================================
# Reading-based estimates
# =============================================================================

def test_estimate_tou() -> None:
    """TOU estimate should sum the cost of individual readings."""
    readings = [
        {
            "timestamp": ontario_datetime(
                2026,
                9,
                2,
                14,
            ),
            "energy_kwh": 10,
        },
        {
            "timestamp": ontario_datetime(
                2026,
                9,
                2,
                22,
            ),
            "energy_kwh": 10,
        },
    ]

    # $2.03 on-peak + $0.98 off-peak
    assert estimate_tou(
        readings
    ) == pytest.approx(
        3.01
    )


def test_estimate_ulo() -> None:
    """ULO estimate should sum the cost of individual readings."""
    readings = [
        {
            "timestamp": ontario_datetime(
                2026,
                9,
                2,
                2,
            ),
            "energy_kwh": 10,
        },
        {
            "timestamp": ontario_datetime(
                2026,
                9,
                2,
                18,
            ),
            "energy_kwh": 10,
        },
    ]

    # $0.39 overnight + $3.91 on-peak
    assert estimate_ulo(
        readings
    ) == pytest.approx(
        4.30
    )


def test_estimate_accepts_ts_alias() -> None:
    """Database-style `ts` timestamps should remain supported."""
    readings = [
        {
            "ts": ontario_datetime(
                2026,
                9,
                2,
                22,
            ),
            "energy_kwh": 5,
        }
    ]

    assert estimate_tou(
        readings
    ) == pytest.approx(
        0.49
    )


def test_estimate_plan_costs_groups_tiered_usage_by_month() -> None:
    """
    Tiered pricing must reset its threshold for each calendar month.

    This catches a subtle bug where a multi-month dataset is incorrectly
    treated as one continuous monthly consumption total.
    """
    readings = [
        {
            "timestamp": ontario_datetime(
                2026,
                7,
                15,
                12,
            ),
            "energy_kwh": 500,
        },
        {
            "timestamp": ontario_datetime(
                2026,
                8,
                15,
                12,
            ),
            "energy_kwh": 500,
        },
    ]

    costs = estimate_plan_costs(
        readings
    )

    # Each month is independently below the 600 kWh summer threshold:
    # 500 × $0.120 × 2 = $120.
    assert costs["tiered"] == pytest.approx(
        120.00
    )


# =============================================================================
# Rate metadata
# =============================================================================

def test_rate_snapshot_contains_required_metadata() -> None:
    """The API-facing rate snapshot should expose its effective date/source."""
    snapshot = get_current_electricity_rates()

    assert snapshot["source"]
    assert snapshot["effective_date"]
    assert snapshot["timezone"] == "America/Toronto"
    assert snapshot["unit"] == "¢/kWh"

    assert "tou" in snapshot["plans"]
    assert "ulo" in snapshot["plans"]
    assert "tiered" in snapshot["plans"]


def test_season_for_timestamp() -> None:
    """Season classification should change at the May/November boundary."""
    assert (
        season_for_timestamp(
            ontario_datetime(2026, 4, 30, 12)
        )
        == "winter"
    )

    assert (
        season_for_timestamp(
            ontario_datetime(2026, 5, 1, 12)
        )
        == "summer"
    )

    assert (
        season_for_timestamp(
            ontario_datetime(2026, 10, 31, 12)
        )
        == "summer"
    )

    assert (
        season_for_timestamp(
            ontario_datetime(2026, 11, 1, 12)
        )
        == "winter"
    )


# =============================================================================
# Validation / failure tests
# =============================================================================

@pytest.mark.parametrize(
    "bad_energy",
    [
        -1,
        float("nan"),
        float("inf"),
        -float("inf"),
        "not-a-number",
        None,
    ],
)
def test_negative_or_invalid_energy_is_rejected(
    bad_energy,
) -> None:
    """Invalid energy values should never silently become valid costs."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    with pytest.raises(
        InvalidRateInputError
    ):
        tou_cost(
            bad_energy,
            ts,
        )


def test_invalid_plan_is_rejected() -> None:
    """Unknown pricing plans should fail explicitly."""
    ts = ontario_datetime(
        2026,
        9,
        2,
        14,
    )

    with pytest.raises(
        InvalidRateInputError
    ):
        get_rate(
            "made_up_plan",
            ts,
        )


def test_tiered_cost_rejects_negative_usage() -> None:
    """Negative monthly consumption should never be accepted."""
    ts = ontario_datetime(
        2026,
        7,
        1,
        12,
    )

    with pytest.raises(
        InvalidRateInputError
    ):
        tiered_cost(
            -100,
            ts,
        )


def test_invalid_reading_is_rejected() -> None:
    """Missing energy data should fail instead of silently producing a cost."""
    readings = [
        {
            "timestamp": ontario_datetime(
                2026,
                9,
                2,
                14,
            )
        }
    ]

    with pytest.raises(
        InvalidRateInputError
    ):
        estimate_tou(readings)


# =============================================================================
# Timestamp compatibility
# =============================================================================

def test_iso_timestamp_is_supported() -> None:
    """API/database ISO timestamps should be accepted."""
    timestamp = "2026-09-02T14:00:00-04:00"

    assert tou_period(timestamp) == "on_peak"


def test_naive_timestamp_is_interpreted_as_ontario_time() -> None:
    """
    Naive timestamps should be interpreted as Ontario local time.

    This prevents an accidental UTC conversion from moving a reading into
    the wrong TOU period.
    """
    timestamp = datetime(
        2026,
        9,
        2,
        14,
    )

    assert tou_period(timestamp) == "on_peak"