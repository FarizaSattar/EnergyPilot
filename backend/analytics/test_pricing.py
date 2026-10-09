"""
EnergyPilot Canadian electricity pricing configuration.

This file contains tariff DATA only.

Calculation logic belongs in pricing.py.

Current implementation:
    - Canada
    - Ontario
    - Ontario Energy Board Regulated Price Plan (RPP)
    - Residential
    - Small business

Important:
    Electricity prices change periodically. These values represent the
    currently published Ontario RPP rates for the Nov. 1, 2025 to
    Oct. 31, 2026 period.

    Delivery charges, regulatory charges, taxes, rebates, fixed charges,
    and utility-specific charges are intentionally NOT included here.

All electricity rates are CAD/kWh.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


# ---------------------------------------------------------------------------
# Application defaults
# ---------------------------------------------------------------------------

DEFAULT_COUNTRY = "CA"
DEFAULT_PROVINCE = "ON"
DEFAULT_CUSTOMER_TYPE = "residential"

DEFAULT_CURRENCY = "CAD"
DEFAULT_TIMEZONE = "America/Toronto"


# ---------------------------------------------------------------------------
# Ontario RPP rate period
# ---------------------------------------------------------------------------

# These are the currently published Ontario RPP prices used by EnergyPilot.
#
# Effective:
#     November 1, 2025
#
# Published period:
#     November 1, 2025 - October 31, 2026
#
# The pricing engine will use these as the latest known rates for dates
# beyond the published period until a newer configuration is supplied.

ONTARIO_RPP_EFFECTIVE_FROM = "2025-11-01"
ONTARIO_RPP_EFFECTIVE_TO = "2026-10-31"


# ---------------------------------------------------------------------------
# Ontario electricity rates
# ---------------------------------------------------------------------------

ONTARIO_RPP_RATES = {
    "tou": {
        "off_peak": 0.098,
        "mid_peak": 0.157,
        "on_peak": 0.203,
    },
    "ulo": {
        "overnight": 0.039,
        "weekend_off_peak": 0.098,
        "mid_peak": 0.157,
        "on_peak": 0.391,
    },
    "tiered": {
        "tier_1": 0.120,
        "tier_2": 0.142,
    },
}


# ---------------------------------------------------------------------------
# Ontario Tiered thresholds
# ---------------------------------------------------------------------------

ONTARIO_TIER_THRESHOLDS = {
    "residential": {
        "summer": 600.0,
        "winter": 1000.0,
    },
    "small_business": {
        "summer": 750.0,
        "winter": 750.0,
    },
}


# ---------------------------------------------------------------------------
# Ontario TOU schedule
# ---------------------------------------------------------------------------

# Summer:
#     May 1 - October 31
#
# Weekdays:
#     07:00 - 11:00  Mid-peak
#     11:00 - 17:00  On-peak
#     17:00 - 19:00  Mid-peak
#     19:00 - 07:00  Off-peak
#
# Weekends / holidays:
#     All day Off-peak
#
# Winter:
#     November 1 - April 30
#
# Weekdays:
#     07:00 - 11:00  On-peak
#     11:00 - 17:00  Mid-peak
#     17:00 - 19:00  On-peak
#     19:00 - 07:00  Off-peak
#
# Weekends / holidays:
#     All day Off-peak

ONTARIO_TOU_SCHEDULE = {
    "summer": {
        "weekday": (
            (7, 11, "mid_peak"),
            (11, 17, "on_peak"),
            (17, 19, "mid_peak"),
            (19, 24, "off_peak"),
            (0, 7, "off_peak"),
        ),
        "weekend": "off_peak",
        "holiday": "off_peak",
    },
    "winter": {
        "weekday": (
            (7, 11, "on_peak"),
            (11, 17, "mid_peak"),
            (17, 19, "on_peak"),
            (19, 24, "off_peak"),
            (0, 7, "off_peak"),
        ),
        "weekend": "off_peak",
        "holiday": "off_peak",
    },
}


# ---------------------------------------------------------------------------
# Ontario ULO schedule
# ---------------------------------------------------------------------------

# ULO schedule is the same in summer and winter.
#
# Weekdays:
#     07:00 - 16:00  Mid-peak
#     16:00 - 21:00  On-peak
#     21:00 - 23:00  Mid-peak
#     23:00 - 07:00  Ultra-low overnight
#
# Weekends / holidays:
#     07:00 - 23:00  Weekend off-peak
#     23:00 - 07:00  Ultra-low overnight

ONTARIO_ULO_SCHEDULE = {
    "weekday": (
        (7, 16, "mid_peak"),
        (16, 21, "on_peak"),
        (21, 23, "mid_peak"),
        (23, 24, "overnight"),
        (0, 7, "overnight"),
    ),
    "weekend": (
        (7, 23, "weekend_off_peak"),
        (23, 24, "overnight"),
        (0, 7, "overnight"),
    ),
    "holiday": (
        (7, 23, "weekend_off_peak"),
        (23, 24, "overnight"),
        (0, 7, "overnight"),
    ),
}


# ---------------------------------------------------------------------------
# 2026 Ontario TOU / ULO holidays
# ---------------------------------------------------------------------------

# OEB-published 2026 holiday dates.

ONTARIO_HOLIDAYS_2026 = {
    "2026-01-01": "New Year's Day",
    "2026-02-16": "Family Day",
    "2026-04-03": "Good Friday",
    "2026-05-18": "Victoria Day",
    "2026-07-01": "Canada Day",
    "2026-08-03": "Civic Holiday",
    "2026-09-07": "Labour Day",
    "2026-10-12": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
    "2026-12-28": "Boxing Day",
}


# ---------------------------------------------------------------------------
# Canadian province registry
# ---------------------------------------------------------------------------

# These provinces are registered so the pricing engine can evolve into a
# multi-province Canadian pricing system without pretending that Ontario
# rates apply everywhere.

CANADIAN_PROVINCES = {
    "AB": "Alberta",
    "BC": "British Columbia",
    "MB": "Manitoba",
    "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador",
    "NS": "Nova Scotia",
    "NT": "Northwest Territories",
    "NU": "Nunavut",
    "ON": "Ontario",
    "PE": "Prince Edward Island",
    "QC": "Quebec",
    "SK": "Saskatchewan",
    "YT": "Yukon",
}


# ---------------------------------------------------------------------------
# Province tariff registry
# ---------------------------------------------------------------------------

# Only Ontario has a verified RPP implementation in this project.
#
# Other provinces are deliberately marked as unsupported rather than using
# Ontario rates incorrectly.

PROVINCE_TARIFFS = {
    "ON": {
        "country": "CA",
        "province": "ON",
        "province_name": "Ontario",
        "market": "Ontario Energy Board",
        "program": "Regulated Price Plan",
        "currency": "CAD",
        "timezone": "America/Toronto",
        "supported": True,
        "plans": ("tou", "ulo", "tiered"),
        "rates": ONTARIO_RPP_RATES,
        "tier_thresholds": ONTARIO_TIER_THRESHOLDS,
        "effective_from": ONTARIO_RPP_EFFECTIVE_FROM,
        "effective_to": ONTARIO_RPP_EFFECTIVE_TO,
    }
}


# ---------------------------------------------------------------------------
# Backwards-compatible PRICING object
# ---------------------------------------------------------------------------

# Your original pricing.py expects:
#
#     from config import PRICING
#
# The new pricing.py does not require that anymore, but this object is kept
# available so it can be imported elsewhere if needed.

PRICING = {
    "tou": {
        "rates": deepcopy(ONTARIO_RPP_RATES["tou"]),
        "province": "ON",
        "country": "CA",
        "currency": "CAD",
        "timezone": DEFAULT_TIMEZONE,
    },
    "ulo": {
        "rates": deepcopy(ONTARIO_RPP_RATES["ulo"]),
        "province": "ON",
        "country": "CA",
        "currency": "CAD",
        "timezone": DEFAULT_TIMEZONE,
    },
    "tiered": {
        "rates": deepcopy(ONTARIO_RPP_RATES["tiered"]),
        "province": "ON",
        "country": "CA",
        "currency": "CAD",
        "timezone": DEFAULT_TIMEZONE,
        "thresholds": deepcopy(ONTARIO_TIER_THRESHOLDS),
    },
}


# ---------------------------------------------------------------------------
# Public configuration object
# ---------------------------------------------------------------------------

CANADIAN_PRICING = {
    "default_country": DEFAULT_COUNTRY,
    "default_province": DEFAULT_PROVINCE,
    "default_customer_type": DEFAULT_CUSTOMER_TYPE,
    "default_currency": DEFAULT_CURRENCY,
    "default_timezone": DEFAULT_TIMEZONE,
    "provinces": CANADIAN_PROVINCES,
    "tariffs": PROVINCE_TARIFFS,
}


__all__ = [
    "DEFAULT_COUNTRY",
    "DEFAULT_PROVINCE",
    "DEFAULT_CUSTOMER_TYPE",
    "DEFAULT_CURRENCY",
    "DEFAULT_TIMEZONE",
    "ONTARIO_RPP_EFFECTIVE_FROM",
    "ONTARIO_RPP_EFFECTIVE_TO",
    "ONTARIO_RPP_RATES",
    "ONTARIO_TIER_THRESHOLDS",
    "ONTARIO_TOU_SCHEDULE",
    "ONTARIO_ULO_SCHEDULE",
    "ONTARIO_HOLIDAYS_2026",
    "CANADIAN_PROVINCES",
    "PROVINCE_TARIFFS",
    "PRICING",
    "CANADIAN_PRICING",
]