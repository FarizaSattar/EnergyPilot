"""
EnergyPilot recommendation service.

This module orchestrates the recommendation pipeline.

Architecture:

    PostgreSQL
        |
        v
    db.py
        |
        +-------------------+
        |                   |
        v                   v
    analytics.py       forecasting/
        |                   |
        +---------+---------+
                  |
                  v
             context.py
                  |
                  v
       recommendation_service.py
                  |
          +-------+-------+
          |               |
          v               v
 recommendations.py     llm.py
 deterministic facts    explanation
          |               |
          +-------+-------+
                  |
                  v
              app.py
                  |
                  v
             React frontend

Design principles
-----------------
1. Deterministic recommendation logic remains the source of truth.
2. The LLM is optional and is used only for explanation/enrichment.
3. Savings estimates come from deterministic code, not the LLM.
4. Weather, pricing, forecasting, and database access remain separate services.
5. This module owns orchestration, not business calculations.
6. The returned structure is JSON-safe and stable for Flask/API consumers.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from context import build_energy_context
from recommendations import (
    analyze_usage,
    summarize_recommendations,
)

try:
    from llm import (
        LLMError,
        generate_energy_recommendations,
        is_llm_configured,
    )
except ImportError:  # pragma: no cover - supports deterministic-only installs
    LLMError = Exception  # type: ignore[misc, assignment]
    generate_energy_recommendations = None
    is_llm_configured = lambda: False


LOGGER = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_MAX_RECOMMENDATIONS = 10

VALID_RECOMMENDATION_PRIORITIES = {
    "low",
    "medium",
    "high",
    "critical",
}

PRIORITY_ORDER = {
    "critical": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


# =============================================================================
# Exceptions
# =============================================================================

class RecommendationServiceError(Exception):
    """Base exception for recommendation-service failures."""


class RecommendationInputError(
    RecommendationServiceError
):
    """Raised when recommendation inputs are invalid."""


class RecommendationLLMError(
    RecommendationServiceError
):
    """Raised when optional LLM processing fails."""


# =============================================================================
# Generic helpers
# =============================================================================

def _clean_mapping(
    value: Any,
    *,
    name: str,
) -> dict[str, Any]:
    """Validate and copy an optional mapping."""
    if value is None:
        return {}

    if not isinstance(value, Mapping):
        raise RecommendationInputError(
            f"{name} must be a dictionary/mapping."
        )

    return dict(value)


def _clean_sequence(
    value: Any,
    *,
    name: str,
) -> list[Any]:
    """Validate an iterable of records."""
    if value is None:
        return []

    if isinstance(
        value,
        (str, bytes, bytearray),
    ):
        raise RecommendationInputError(
            f"{name} must be a sequence of records."
        )

    try:
        return list(value)
    except TypeError as exc:
        raise RecommendationInputError(
            f"{name} must be iterable."
        ) from exc


def _safe_float(
    value: Any,
) -> float | None:
    """Convert a value to a finite float."""
    if value is None or isinstance(value, bool):
        return None

    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if number != number:
        return None

    if number in (
        float("inf"),
        float("-inf"),
    ):
        return None

    return number


def _safe_non_negative_float(
    value: Any,
) -> float | None:
    """Convert a value to a finite non-negative float."""
    number = _safe_float(value)

    if number is None or number < 0:
        return None

    return number


# =============================================================================
# Recommendation normalization
# =============================================================================

def _normalize_priority(
    value: Any,
) -> str:
    """Normalize recommendation priority."""
    if not isinstance(value, str):
        return "medium"

    priority = value.strip().lower()

    if priority not in VALID_RECOMMENDATION_PRIORITIES:
        return "medium"

    return priority


def _normalize_recommendation(
    recommendation: Mapping[str, Any],
    *,
    index: int,
) -> dict[str, Any]:
    """
    Normalize one deterministic recommendation.

    Missing financial information remains None. In particular, this function
    never converts missing savings into $0 because zero and unknown mean
    different things.
    """
    title = recommendation.get(
        "title"
    )

    category = recommendation.get(
        "category",
        "general",
    )

    description = recommendation.get(
        "description",
        "",
    )

    if not isinstance(title, str) or not title.strip():
        title = "Energy opportunity"

    if not isinstance(category, str):
        category = "general"

    if not isinstance(description, str):
        description = ""

    priority = _normalize_priority(
        recommendation.get(
            "priority",
            "medium",
        )
    )

    savings = (
        recommendation.get(
            "estimated_savings"
        )
    )

    savings = _safe_non_negative_float(
        savings
    )

    confidence = _safe_float(
        recommendation.get(
            "confidence"
        )
    )

    if confidence is not None:
        # Accept either 0.92 or 92 as input.
        if confidence > 1:
            confidence /= 100

        confidence = min(
            max(confidence, 0.0),
            1.0,
        )

    tags = recommendation.get(
        "tags",
        [],
    )

    if not isinstance(tags, Sequence) or isinstance(
        tags,
        (str, bytes, bytearray),
    ):
        tags = []

    normalized_tags: list[str] = []

    for tag in tags:
        if not isinstance(tag, str):
            continue

        clean_tag = tag.strip()

        if (
            clean_tag
            and clean_tag not in normalized_tags
        ):
            normalized_tags.append(
                clean_tag
            )

    result: dict[str, Any] = {
        "title": title.strip(),
        "category": category.strip(),
        "description": description.strip(),
        "estimated_savings": (
            round(savings, 2)
            if savings is not None
            else None
        ),
        "priority": priority,
        "confidence": (
            round(confidence, 3)
            if confidence is not None
            else None
        ),
        "tags": normalized_tags[:10],
        "_index": index,
    }

    # Preserve an optional action without requiring it.
    action = recommendation.get(
        "action"
    )

    if isinstance(action, str) and action.strip():
        result["action"] = action.strip()

    # Preserve deterministic monthly/annual fields when the recommendation
    # engine explicitly provides them. The service never calculates these
    # from an LLM response.
    monthly_savings = _safe_non_negative_float(
        recommendation.get(
            "estimated_monthly_savings"
        )
    )

    annual_savings = _safe_non_negative_float(
        recommendation.get(
            "estimated_annual_savings"
        )
    )

    if monthly_savings is not None:
        result["estimated_monthly_savings"] = round(
            monthly_savings,
            2,
        )

    if annual_savings is not None:
        result["estimated_annual_savings"] = round(
            annual_savings,
            2,
        )

    return result


def _normalize_recommendations(
    recommendations: Any,
    *,
    max_recommendations: int,
) -> list[dict[str, Any]]:
    """Normalize, sort, and bound recommendation output."""
    if recommendations is None:
        return []

    if not isinstance(
        recommendations,
        Sequence,
    ):
        raise RecommendationServiceError(
            "Recommendation engine returned an invalid result."
        )

    normalized: list[dict[str, Any]] = []

    for index, recommendation in enumerate(
        recommendations
    ):
        if not isinstance(
            recommendation,
            Mapping,
        ):
            LOGGER.warning(
                "Ignoring malformed recommendation at index %d.",
                index,
            )
            continue

        normalized.append(
            _normalize_recommendation(
                recommendation,
                index=index,
            )
        )

    # Deterministic ordering:
    #   1. priority
    #   2. estimated monthly savings
    #   3. original order
    #
    # This is an ordering mechanism for stable UI output, not a statement
    # that one recommendation is universally better than another.
    normalized.sort(
        key=lambda item: (
            -PRIORITY_ORDER.get(
                item["priority"],
                2,
            ),
            -(
                item.get(
                    "estimated_monthly_savings"
                )
                or item.get(
                    "estimated_savings"
                )
                or 0.0
            ),
            item["_index"],
        )
    )

    normalized = normalized[
        :max_recommendations
    ]

    for recommendation in normalized:
        recommendation.pop(
            "_index",
            None,
        )

    return normalized


# =============================================================================
# Deterministic recommendation pipeline
# =============================================================================

def _run_deterministic_engine(
    readings: Sequence[Any],
    household: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """
    Run the deterministic recommendation engine.

    This function deliberately contains no LLM calls.
    """
    try:
        recommendations = analyze_usage(
            readings,
            household=household,
        )
    except TypeError:
        # Backward compatibility with recommendation implementations that
        # expose analyze_usage(readings, household) positionally.
        recommendations = analyze_usage(
            readings,
            household,
        )

    return _normalize_recommendations(
        recommendations,
        max_recommendations=DEFAULT_MAX_RECOMMENDATIONS,
    )


# =============================================================================
# LLM integration
# =============================================================================

def _build_llm_context(
    context: Mapping[str, Any],
    recommendations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Build the context supplied to the LLM.

    Only deterministic facts and deterministic recommendations are passed
    through. The model is explicitly not given authority over the numerical
    source of truth.
    """
    return {
        "energy_context": dict(
            context
        ),

        "deterministic_recommendations": [
            dict(recommendation)
            for recommendation in recommendations
        ],

        "instructions": {
            "role": (
                "Explain the supplied energy findings "
                "using only the provided facts."
            ),

            "do_not_recalculate_savings": True,

            "do_not_invent_measurements": True,

            "do_not_invent_prices": True,

            "do_not_change_recommendation_priority": True,
        },
    }


def _merge_llm_explanations(
    recommendations: list[dict[str, Any]],
    llm_result: Any,
) -> list[dict[str, Any]]:
    """
    Merge LLM-generated explanations without allowing the LLM to overwrite
    deterministic numerical fields.

    The deterministic recommendation remains authoritative for:
        - title
        - category
        - priority
        - savings
        - confidence
        - tags

    The LLM may enrich the user-facing explanation/action fields.
    """
    if not isinstance(
        llm_result,
        Mapping,
    ):
        return recommendations

    llm_recommendations = llm_result.get(
        "recommendations",
        [],
    )

    if not isinstance(
        llm_recommendations,
        Sequence,
    ):
        return recommendations

    enriched = [
        dict(recommendation)
        for recommendation in recommendations
    ]

    # Match by stable title/category rather than array position where possible.
    lookup: dict[tuple[str, str], dict[str, Any]] = {}

    for recommendation in llm_recommendations:
        if not isinstance(
            recommendation,
            Mapping,
        ):
            continue

        title = recommendation.get(
            "title"
        )

        category = recommendation.get(
            "category",
            "general",
        )

        if not isinstance(title, str):
            continue

        if not isinstance(category, str):
            category = "general"

        lookup[
            (
                title.strip().lower(),
                category.strip().lower(),
            )
        ] = dict(
            recommendation
        )

    for recommendation in enriched:
        key = (
            recommendation["title"].strip().lower(),
            recommendation["category"].strip().lower(),
        )

        llm_item = lookup.get(key)

        if llm_item is None:
            continue

        # These are explanation fields, not sources of truth.
        explanation = llm_item.get(
            "explanation"
        )

        if isinstance(
            explanation,
            str,
        ) and explanation.strip():
            recommendation[
                "explanation"
            ] = explanation.strip()

        action = llm_item.get(
            "action"
        )

        if isinstance(
            action,
            str,
        ) and action.strip():
            recommendation[
                "action"
            ] = action.strip()

        rationale = llm_item.get(
            "rationale"
        )

        if isinstance(
            rationale,
            str,
        ) and rationale.strip():
            recommendation[
                "rationale"
            ] = rationale.strip()

    return enriched


def _maybe_generate_llm_enrichment(
    context: Mapping[str, Any],
    recommendations: list[dict[str, Any]],
    *,
    use_llm: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Optionally enrich recommendations with LLM-generated explanations.

    LLM failures do not invalidate deterministic recommendations. This is an
    intentional resilience boundary: EnergyPilot should still work when the
    external LLM provider is unavailable.
    """
    if not use_llm:
        return recommendations, {
            "enabled": False,
            "configured": False,
            "used": False,
        }

    if generate_energy_recommendations is None:
        return recommendations, {
            "enabled": True,
            "configured": False,
            "used": False,
            "reason": "LLM integration unavailable.",
        }

    try:
        configured = bool(
            is_llm_configured()
        )
    except Exception:
        configured = False

    if not configured:
        return recommendations, {
            "enabled": True,
            "configured": False,
            "used": False,
            "reason": "LLM is not configured.",
        }

    llm_context = _build_llm_context(
        context,
        recommendations,
    )

    try:
        llm_result = (
            generate_energy_recommendations(
                llm_context
            )
        )

    except LLMError as exc:
        # The deterministic engine remains usable. Log the provider failure
        # while avoiding provider credentials or request payloads.
        LOGGER.warning(
            "LLM recommendation enrichment failed: %s",
            exc,
        )

        return recommendations, {
            "enabled": True,
            "configured": True,
            "used": False,
            "error": "LLM enrichment failed.",
        }

    except Exception:
        LOGGER.exception(
            "Unexpected LLM recommendation failure."
        )

        return recommendations, {
            "enabled": True,
            "configured": True,
            "used": False,
            "error": "LLM enrichment failed unexpectedly.",
        }

    return (
        _merge_llm_explanations(
            recommendations,
            llm_result,
        ),
        {
            "enabled": True,
            "configured": True,
            "used": True,
        },
    )


# =============================================================================
# Summary
# =============================================================================

def _build_summary(
    recommendations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """
    Build a service-level recommendation summary.

    Prefer the existing deterministic summarize_recommendations() helper so
    there is one source of truth for recommendation summary semantics.
    """
    try:
        summary = summarize_recommendations(
            recommendations
        )

        if isinstance(summary, Mapping):
            return dict(summary)

    except Exception:
        LOGGER.exception(
            "Unable to generate recommendation summary."
        )

    # Conservative fallback.
    monthly_opportunity = 0.0
    annual_opportunity = 0.0
    high_priority = 0

    for recommendation in recommendations:
        monthly = _safe_non_negative_float(
            recommendation.get(
                "estimated_monthly_savings"
            )
        )

        annual = _safe_non_negative_float(
            recommendation.get(
                "estimated_annual_savings"
            )
        )

        if monthly is not None:
            monthly_opportunity += monthly

        if annual is not None:
            annual_opportunity += annual

        if recommendation.get(
            "priority"
        ) in {
            "high",
            "critical",
        }:
            high_priority += 1

    return {
        "recommendation_count": len(
            recommendations
        ),

        "monthly_savings_opportunity": round(
            monthly_opportunity,
            2,
        ),

        "annual_savings_opportunity": round(
            annual_opportunity,
            2,
        ),

        "high_priority_count": high_priority,
    }


# =============================================================================
# Public service
# =============================================================================

def generate_recommendations(
    readings: Sequence[Any],
    household: Mapping[str, Any] | None = None,
    weather: Mapping[str, Any] | None = None,
    pricing: Mapping[str, Any] | None = None,
    forecast: Mapping[str, Any] | None = None,
    *,
    use_llm: bool = False,
    max_recommendations: int = DEFAULT_MAX_RECOMMENDATIONS,
) -> dict[str, Any]:
    """
    Generate EnergyPilot recommendations.

    Parameters
    ----------
    readings:
        Meter readings from PostgreSQL/simulator/CSV ingestion.

    household:
        Household/building configuration.

    weather:
        Normalized weather data.

    pricing:
        Electricity pricing context.

    forecast:
        Demand forecast context.

    use_llm:
        Whether to request optional natural-language enrichment.

    max_recommendations:
        Maximum recommendations returned to the API/UI.

    Returns
    -------
    dict
        API-ready recommendation response.

    Important:
        Numerical recommendation facts remain deterministic even when
        use_llm=True.
    """
    if not 1 <= max_recommendations <= 50:
        raise RecommendationInputError(
            "max_recommendations must be between 1 and 50."
        )

    reading_records = _clean_sequence(
        readings,
        name="readings",
    )

    household_data = _clean_mapping(
        household,
        name="household",
    )

    weather_data = _clean_mapping(
        weather,
        name="weather",
    )

    pricing_data = _clean_mapping(
        pricing,
        name="pricing",
    )

    forecast_data = _clean_mapping(
        forecast,
        name="forecast",
    )

    LOGGER.info(
        "Generating recommendations from %d readings.",
        len(reading_records),
    )

    # -------------------------------------------------------------------------
    # Build deterministic context.
    # -------------------------------------------------------------------------

    context = build_energy_context(
        reading_records,
        household=household_data,
        weather=weather_data,
        pricing=pricing_data,
        forecast=forecast_data,
    )

    # -------------------------------------------------------------------------
    # Run deterministic recommendation engine.
    # -------------------------------------------------------------------------

    recommendations = (
        _run_deterministic_engine(
            reading_records,
            household_data,
        )
    )

    # Respect the caller's API-level limit.
    recommendations = recommendations[
        :max_recommendations
    ]

    # -------------------------------------------------------------------------
    # Optional LLM enrichment.
    # -------------------------------------------------------------------------

    recommendations, llm_metadata = (
        _maybe_generate_llm_enrichment(
            context,
            recommendations,
            use_llm=use_llm,
        )
    )

    # -------------------------------------------------------------------------
    # Final summary.
    # -------------------------------------------------------------------------

    summary = _build_summary(
        recommendations
    )

    return {
        "recommendations": recommendations,

        "summary": summary,

        "context": context,

        "llm": llm_metadata,

        "meta": {
            "service_version": "1.0",
            "recommendation_count": len(
                recommendations
            ),
            "deterministic": True,
        },
    }


def generate_deterministic_recommendations(
    readings: Sequence[Any],
    household: Mapping[str, Any] | None = None,
    *,
    max_recommendations: int = DEFAULT_MAX_RECOMMENDATIONS,
) -> dict[str, Any]:
    """
    Generate recommendations without weather, forecast, pricing, or LLM
    enrichment.

    Useful for:
        - tests
        - offline mode
        - development
        - deterministic API endpoints
    """
    return generate_recommendations(
        readings=readings,
        household=household,
        use_llm=False,
        max_recommendations=max_recommendations,
    )


__all__ = [
    "RecommendationInputError",
    "RecommendationLLMError",
    "RecommendationServiceError",
    "generate_deterministic_recommendations",
    "generate_recommendations",
]