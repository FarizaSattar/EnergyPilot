"""
EnergyPilot Canadian electricity pricing configuration.

This module contains tariff DATA only.

Calculation logic belongs in:
    analytics.pricing

Current implementation:
    - Canada
    - Ontario
    - Ontario Energy Board (OEB)
    - Regulated Price Plan (RPP)
    - Residential customers
    - Small business customers

IMPORTANT
---------
Electricity prices change periodically.

The configured Ontario RPP rates below are the OEB-published rates
effective November 1, 2025 through October 31, 2026.

These values represent the electricity commodity/supply price only.

The following are intentionally NOT included:

    - Delivery charges
    - Regulatory charges
    - Ontario Electricity Rebate
    - HST
    - Fixed monthly charges
    - Global Adjustment
    - Utility-specific charges
    - Retailer contract charges

All electricity rates are expressed in CAD/kWh.

The pricing engine may use the latest configured rates as a fallback
for dates outside the configured effective period. That behavior belongs
to analytics.pricing, not this configuration module.
"""

from __future__ import annotations

from copy import deepcopy


# ============================================================================
# Application defaults
# ============================================================================

DEFAULT_COUNTRY = "CA"
DEFAULT_PROVINCE = "ON"
DEFAULT_CUSTOMER_TYPE = "residential"
DEFAULT_CURRENCY = "CAD"
DEFAULT_TIMEZONE = "America/Toronto"


# ============================================================================
# Supported customer types
# ============================================================================

CUSTOMER_TYPES = (
    "residential",
    "small_business",
)


# ============================================================================
# Supported Ontario pricing plans
# ============================================================================

ONTARIO_PLANS = (
    "tou",
    "ulo",
    "tiered",
)


# ============================================================================
# Ontario RPP effective period
# ============================================================================

# Latest configured OEB RPP period.
#
# Effective:
#     November 1, 2025
#
# Through:
#     October 31, 2026

ONTARIO_RPP_EFFECTIVE_FROM = "2025-11-01"
ONTARIO_RPP_EFFECTIVE_TO = "2026-10-31"


# ============================================================================
# Ontario RPP electricity rates
# ============================================================================
#
# Values are CAD/kWh.
#
# Equivalent published prices:
#
# TOU:
#     Off-peak   9.8 cents/kWh
#     Mid-peak  15.7 cents/kWh
#     On-peak   20.3 cents/kWh
#
# ULO:
#     Overnight          3.9 cents/kWh
#     Weekend Off-peak   9.8 cents/kWh
#     Mid-peak          15.7 cents/kWh
#     On-peak           39.1 cents/kWh
#
# Tiered:
#     Tier 1  12.0 cents/kWh
#     Tier 2  14.2 cents/kWh
#
# OEB source:
#     November 1, 2025 RPP prices
#
# ============================================================================

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


# ============================================================================
# Ontario Tiered thresholds
# ============================================================================
#
# Thresholds represent the amount of monthly electricity consumption
# eligible for the lower Tier 1 price.
#
# Residential:
#     Summer: 600 kWh/month
#     Winter: 1,000 kWh/month
#
# Small business / non-residential:
#     750 kWh/month year-round
#
# Season:
#     Summer = May 1 through October 31
#     Winter = November 1 through April 30
#
# ============================================================================

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


# ============================================================================
# Ontario TOU schedule
# ============================================================================
#
# TOU periods change between summer and winter.
#
# SUMMER
# -------
# May 1 - October 31
#
# Weekdays:
#     00:00 - 07:00  Off-peak
#     07:00 - 11:00  Mid-peak
#     11:00 - 17:00  On-peak
#     17:00 - 19:00  Mid-peak
#     19:00 - 24:00  Off-peak
#
# WINTER
# -------
# November 1 - April 30
#
# Weekdays:
#     00:00 - 07:00  Off-peak
#     07:00 - 11:00  On-peak
#     11:00 - 17:00  Mid-peak
#     17:00 - 19:00  On-peak
#     19:00 - 24:00  Off-peak
#
# Weekends and holidays:
#     Off-peak all day
#
# The tuples use:
#
#     (start_hour, end_hour, period)
#
# ============================================================================

ONTARIO_TOU_SCHEDULE = {
    "summer": {
        "weekday": (
            (0, 7, "off_peak"),
            (7, 11, "mid_peak"),
            (11, 17, "on_peak"),
            (17, 19, "mid_peak"),
            (19, 24, "off_peak"),
        ),
        "weekend": "off_peak",
        "holiday": "off_peak",
    },

    "winter": {
        "weekday": (
            (0, 7, "off_peak"),
            (7, 11, "on_peak"),
            (11, 17, "mid_peak"),
            (17, 19, "on_peak"),
            (19, 24, "off_peak"),
        ),
        "weekend": "off_peak",
        "holiday": "off_peak",
    },
}


# ============================================================================
# Ontario ULO schedule
# ============================================================================
#
# ULO is the same throughout summer and winter.
#
# Weekdays:
#     00:00 - 07:00  Ultra-Low Overnight
#     07:00 - 16:00  Mid-peak
#     16:00 - 21:00  On-peak
#     21:00 - 23:00  Mid-peak
#     23:00 - 24:00  Ultra-Low Overnight
#
# Weekends and holidays:
#     00:00 - 07:00  Ultra-Low Overnight
#     07:00 - 23:00  Weekend Off-peak
#     23:00 - 24:00  Ultra-Low Overnight
#
# OEB:
#     Overnight: every day 11 p.m. - 7 a.m.
#     Weekend Off-peak: weekends/holidays 7 a.m. - 11 p.m.
#     Mid-peak: weekdays 7 a.m. - 4 p.m. and 9 p.m. - 11 p.m.
#     On-peak: weekdays 4 p.m. - 9 p.m.
#
# ============================================================================

ONTARIO_ULO_SCHEDULE = {
    "weekday": (
        (0, 7, "overnight"),
        (7, 16, "mid_peak"),
        (16, 21, "on_peak"),
        (21, 23, "mid_peak"),
        (23, 24, "overnight"),
    ),

    "weekend": (
        (0, 7, "overnight"),
        (7, 23, "weekend_off_peak"),
        (23, 24, "overnight"),
    ),

    "holiday": (
        (0, 7, "overnight"),
        (7, 23, "weekend_off_peak"),
        (23, 24, "overnight"),
    ),
}


# ============================================================================
# Ontario 2026 TOU / ULO holidays
# ============================================================================
#
# These are the OEB-published 2026 dates on which the lowest TOU/ULO
# prices apply all day.
#
# TOU:
#     Off-peak all day
#
# ULO:
#     Weekend Off-peak from 07:00-23:00
#     Ultra-Low Overnight from 23:00-07:00
#
# ============================================================================

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


# ============================================================================
# Canadian province registry
# ============================================================================
#
# This registry identifies Canadian provinces/territories supported by the
# application as geographic entities.
#
# It does NOT imply that EnergyPilot currently has pricing calculations for
# every province.
#
# ============================================================================

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


# ============================================================================
# Province tariff registry
# ============================================================================
#
# Only Ontario has an implemented and verified RPP pricing model.
#
# Other provinces are intentionally NOT added to this registry.
#
# This prevents EnergyPilot from accidentally applying Ontario prices
# to another Canadian province.
#
# ============================================================================

PROVINCE_TARIFFS = {
    "ON": {
        "country": DEFAULT_COUNTRY,
        "province": DEFAULT_PROVINCE,
        "province_name": "Ontario",

        "regulator": "Ontario Energy Board",
        "market": "Ontario",
        "program": "Regulated Price Plan",

        "currency": DEFAULT_CURRENCY,
        "timezone": DEFAULT_TIMEZONE,

        "supported": True,

        "customer_types": CUSTOMER_TYPES,
        "plans": ONTARIO_PLANS,

        "rates": ONTARIO_RPP_RATES,
        "tier_thresholds": ONTARIO_TIER_THRESHOLDS,

        "tou_schedule": ONTARIO_TOU_SCHEDULE,
        "ulo_schedule": ONTARIO_ULO_SCHEDULE,

        "holidays": ONTARIO_HOLIDAYS_2026,

        "effective_from": ONTARIO_RPP_EFFECTIVE_FROM,
        "effective_to": ONTARIO_RPP_EFFECTIVE_TO,
    },
}


# ============================================================================
# Backwards-compatible PRICING object
# ============================================================================
#
# Some older EnergyPilot modules may import:
#
#     from pricing_config import PRICING
#
# Keep this object for compatibility.
#
# The values are deep-copied so callers modifying PRICING do not accidentally
# mutate the canonical tariff configuration above.
#
# ============================================================================

PRICING = {
    "tou": {
        "rates": deepcopy(ONTARIO_RPP_RATES["tou"]),
        "province": DEFAULT_PROVINCE,
        "country": DEFAULT_COUNTRY,
        "currency": DEFAULT_CURRENCY,
        "timezone": DEFAULT_TIMEZONE,
        "effective_from": ONTARIO_RPP_EFFECTIVE_FROM,
        "effective_to": ONTARIO_RPP_EFFECTIVE_TO,
    },

    "ulo": {
        "rates": deepcopy(ONTARIO_RPP_RATES["ulo"]),
        "province": DEFAULT_PROVINCE,
        "country": DEFAULT_COUNTRY,
        "currency": DEFAULT_CURRENCY,
        "timezone": DEFAULT_TIMEZONE,
        "effective_from": ONTARIO_RPP_EFFECTIVE_FROM,
        "effective_to": ONTARIO_RPP_EFFECTIVE_TO,
    },

    "tiered": {
        "rates": deepcopy(ONTARIO_RPP_RATES["tiered"]),
        "province": DEFAULT_PROVINCE,
        "country": DEFAULT_COUNTRY,
        "currency": DEFAULT_CURRENCY,
        "timezone": DEFAULT_TIMEZONE,
        "thresholds": deepcopy(ONTARIO_TIER_THRESHOLDS),
        "effective_from": ONTARIO_RPP_EFFECTIVE_FROM,
        "effective_to": ONTARIO_RPP_EFFECTIVE_TO,
    },
}


# ============================================================================
# Public application-level pricing configuration
# ============================================================================
#
# This is useful for APIs and frontend metadata.
#
# Example:
#
#     CANADIAN_PRICING["tariffs"]["ON"]["plans"]
#
# ============================================================================

CANADIAN_PRICING = {
    "default_country": DEFAULT_COUNTRY,
    "default_province": DEFAULT_PROVINCE,
    "default_customer_type": DEFAULT_CUSTOMER_TYPE,
    "default_currency": DEFAULT_CURRENCY,
    "default_timezone": DEFAULT_TIMEZONE,

    "supported_customer_types": CUSTOMER_TYPES,

    "supported_plans": ONTARIO_PLANS,

    "provinces": CANADIAN_PROVINCES,

    "tariffs": PROVINCE_TARIFFS,
}


# ============================================================================
# Public exports
# ============================================================================

__all__ = [
    "DEFAULT_COUNTRY",
    "DEFAULT_PROVINCE",
    "DEFAULT_CUSTOMER_TYPE",
    "DEFAULT_CURRENCY",
    "DEFAULT_TIMEZONE",

    "CUSTOMER_TYPES",
    "ONTARIO_PLANS",

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