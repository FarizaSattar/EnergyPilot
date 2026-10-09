"""
EnergyPilot LLM recommendation service.

This module provides a thin, defensive integration with OpenRouter.

Architecture:

    PostgreSQL
        |
        v
    deterministic analytics
        |
        +--> electricity pricing
        +--> usage patterns
        +--> weather
        +--> forecast
        +--> savings estimates
        |
        v
    structured LLM context
        |
        v
    OpenRouter
        |
        v
    validated recommendation JSON
        |
        v
    Flask API
        |
        v
    React

IMPORTANT DESIGN PRINCIPLE
---------------------------
The LLM is NOT the source of truth for:

    - electricity prices
    - measured energy consumption
    - forecasts
    - savings calculations
    - tariff periods
    - electrical safety requirements

Those values must come from EnergyPilot's deterministic application logic.

The LLM's job is to explain supplied facts, prioritize communication, and
turn structured evidence into understandable recommendations.

Never pass API keys, database credentials, or other secrets in `context`.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Mapping

import requests


# =============================================================================
# Configuration
# =============================================================================

DEFAULT_OPENROUTER_URL = (
    "https://openrouter.ai/api/v1/chat/completions"
)

DEFAULT_MODEL = "openrouter/free"

DEFAULT_TIMEOUT_SECONDS = 45.0
DEFAULT_CONNECT_TIMEOUT_SECONDS = 10.0

DEFAULT_TEMPERATURE = 0.2

DEFAULT_MAX_CONTEXT_BYTES = 50_000

DEFAULT_MAX_RETRIES = 2
DEFAULT_RETRY_DELAY_SECONDS = 1.0

DEFAULT_APP_URL = "http://localhost:5173"
DEFAULT_APP_TITLE = "EnergyPilot"

LOGGER = logging.getLogger(__name__)


# =============================================================================
# Exceptions
# =============================================================================

class LLMError(Exception):
    """Base exception for EnergyPilot LLM failures."""


class LLMConfigurationError(LLMError):
    """Raised when the LLM integration is incorrectly configured."""


class LLMRequestError(LLMError):
    """Raised when the OpenRouter request fails."""


class LLMResponseError(LLMError):
    """Raised when OpenRouter returns an unusable response."""


class LLMValidationError(LLMError):
    """Raised when the generated recommendation schema is invalid."""


# =============================================================================
# Data structures
# =============================================================================

@dataclass(frozen=True)
class LLMConfig:
    """
    Runtime configuration for the OpenRouter integration.

    Keeping configuration in one immutable object makes it easier to test
    the service and prevents environment-variable lookups from being
    scattered throughout the request logic.
    """

    api_key: str
    model: str = DEFAULT_MODEL
    url: str = DEFAULT_OPENROUTER_URL
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    connect_timeout_seconds: float = DEFAULT_CONNECT_TIMEOUT_SECONDS
    temperature: float = DEFAULT_TEMPERATURE
    max_context_bytes: int = DEFAULT_MAX_CONTEXT_BYTES
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS
    app_url: str = DEFAULT_APP_URL
    app_title: str = DEFAULT_APP_TITLE


@dataclass(frozen=True)
class EnergyRecommendation:
    """
    Validated recommendation returned by the LLM.

    Savings are optional because the model must never invent financial values.
    If deterministic EnergyPilot calculations did not provide a savings
    estimate, the LLM should return null.
    """

    title: str
    description: str
    category: str
    priority: str
    estimated_monthly_savings: float | None
    estimated_annual_savings: float | None
    difficulty: str
    reason: str
    action: str
    confidence: float
    evidence: tuple[Any, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "priority": self.priority,
            "estimated_monthly_savings": (
                self.estimated_monthly_savings
            ),
            "estimated_annual_savings": (
                self.estimated_annual_savings
            ),
            "difficulty": self.difficulty,
            "reason": self.reason,
            "action": self.action,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class RecommendationResponse:
    """Validated top-level LLM recommendation response."""

    summary: str
    recommendations: tuple[EnergyRecommendation, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable response."""
        return {
            "summary": self.summary,
            "recommendations": [
                recommendation.to_dict()
                for recommendation in self.recommendations
            ],
        }


# =============================================================================
# Prompt
# =============================================================================

SYSTEM_PROMPT = """
You are EnergyPilot, an energy-efficiency assistant.

Your job is to explain structured energy data and produce practical,
understandable household recommendations.

The application has already calculated the numerical facts you receive.

STRICT RULES:

1. Use only facts explicitly supplied in the EnergyPilot context.
2. Never invent electricity prices.
3. Never invent weather conditions.
4. Never invent energy measurements.
5. Never invent savings estimates.
6. Never invent forecast values.
7. Never claim savings are guaranteed.
8. Clearly distinguish measured data from modeled estimates.
9. If a financial estimate is not supplied by the application, return null.
10. If evidence is insufficient, say so rather than guessing.
11. Do not provide instructions for modifying electrical panels, wiring,
    breakers, service equipment, or other hazardous electrical equipment.
12. Recommendations should be practical and understandable to a homeowner.
13. Use Ontario electricity-price information only when it is explicitly
    provided in the context.
14. Do not override deterministic calculations supplied by EnergyPilot.
15. Keep recommendations grounded in the supplied evidence.
16. Return JSON only.
17. Do not wrap the JSON in Markdown code fences.

For each recommendation:

- `priority` must be one of: high, medium, low.
- `difficulty` must be one of: easy, moderate, advanced.
- `confidence` must be between 0 and 1.
- Savings fields must be numeric only when the context provides a
  corresponding deterministic estimate. Otherwise use null.
- `evidence` should contain concise references to facts actually supplied
  in the context.

Required response:

{
  "summary": "Short evidence-based summary.",
  "recommendations": [
    {
      "title": "Recommendation title",
      "description": "What the recommendation means.",
      "category": "Category",
      "priority": "high|medium|low",
      "estimated_monthly_savings": 0,
      "estimated_annual_savings": 0,
      "difficulty": "easy|moderate|advanced",
      "reason": "Why this recommendation is supported by the supplied data.",
      "action": "Safe, practical next step.",
      "confidence": 0.0,
      "evidence": []
    }
  ]
}
""".strip()


# =============================================================================
# Configuration loading
# =============================================================================

def _env_float(
    name: str,
    default: float,
) -> float:
    """Read a floating-point environment variable safely."""
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        return float(raw)
    except ValueError as exc:
        raise LLMConfigurationError(
            f"{name} must be a valid number."
        ) from exc


def _env_int(
    name: str,
    default: int,
) -> int:
    """Read an integer environment variable safely."""
    raw = os.getenv(name)

    if raw is None or not raw.strip():
        return default

    try:
        return int(raw)
    except ValueError as exc:
        raise LLMConfigurationError(
            f"{name} must be a valid integer."
        ) from exc


def load_config() -> LLMConfig:
    """
    Load and validate OpenRouter configuration from environment variables.

    Expected environment variables:

        OPENROUTER_API_KEY
        OPENROUTER_MODEL
        OPENROUTER_URL
        OPENROUTER_TIMEOUT_SECONDS
        OPENROUTER_CONNECT_TIMEOUT_SECONDS
        OPENROUTER_TEMPERATURE
        OPENROUTER_MAX_CONTEXT_BYTES
        OPENROUTER_MAX_RETRIES
        OPENROUTER_RETRY_DELAY_SECONDS
        ENERGYPILOT_APP_URL
        ENERGYPILOT_APP_TITLE
    """
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()

    if not api_key:
        raise LLMConfigurationError(
            "OPENROUTER_API_KEY is not configured."
        )

    model = os.getenv(
        "OPENROUTER_MODEL",
        DEFAULT_MODEL,
    ).strip()

    if not model:
        raise LLMConfigurationError(
            "OPENROUTER_MODEL cannot be empty."
        )

    url = os.getenv(
        "OPENROUTER_URL",
        DEFAULT_OPENROUTER_URL,
    ).strip()

    if not url.startswith(("https://", "http://")):
        raise LLMConfigurationError(
            "OPENROUTER_URL must be an HTTP(S) URL."
        )

    timeout = _env_float(
        "OPENROUTER_TIMEOUT_SECONDS",
        DEFAULT_TIMEOUT_SECONDS,
    )

    connect_timeout = _env_float(
        "OPENROUTER_CONNECT_TIMEOUT_SECONDS",
        DEFAULT_CONNECT_TIMEOUT_SECONDS,
    )

    temperature = _env_float(
        "OPENROUTER_TEMPERATURE",
        DEFAULT_TEMPERATURE,
    )

    max_context_bytes = _env_int(
        "OPENROUTER_MAX_CONTEXT_BYTES",
        DEFAULT_MAX_CONTEXT_BYTES,
    )

    max_retries = _env_int(
        "OPENROUTER_MAX_RETRIES",
        DEFAULT_MAX_RETRIES,
    )

    retry_delay = _env_float(
        "OPENROUTER_RETRY_DELAY_SECONDS",
        DEFAULT_RETRY_DELAY_SECONDS,
    )

    if timeout <= 0:
        raise LLMConfigurationError(
            "OPENROUTER_TIMEOUT_SECONDS must be positive."
        )

    if connect_timeout <= 0:
        raise LLMConfigurationError(
            "OPENROUTER_CONNECT_TIMEOUT_SECONDS must be positive."
        )

    if not 0 <= temperature <= 2:
        raise LLMConfigurationError(
            "OPENROUTER_TEMPERATURE must be between 0 and 2."
        )

    if max_context_bytes <= 0:
        raise LLMConfigurationError(
            "OPENROUTER_MAX_CONTEXT_BYTES must be positive."
        )

    if not 0 <= max_retries <= 5:
        raise LLMConfigurationError(
            "OPENROUTER_MAX_RETRIES must be between 0 and 5."
        )

    if retry_delay < 0:
        raise LLMConfigurationError(
            "OPENROUTER_RETRY_DELAY_SECONDS cannot be negative."
        )

    return LLMConfig(
        api_key=api_key,
        model=model,
        url=url,
        timeout_seconds=timeout,
        connect_timeout_seconds=connect_timeout,
        temperature=temperature,
        max_context_bytes=max_context_bytes,
        max_retries=max_retries,
        retry_delay_seconds=retry_delay,
        app_url=os.getenv(
            "ENERGYPILOT_APP_URL",
            DEFAULT_APP_URL,
        ).strip(),
        app_title=os.getenv(
            "ENERGYPILOT_APP_TITLE",
            DEFAULT_APP_TITLE,
        ).strip(),
    )


# =============================================================================
# Context preparation
# =============================================================================

def _sanitize_context(context: Mapping[str, Any]) -> dict[str, Any]:
    """
    Convert arbitrary mapping data into JSON-safe context.

    This function intentionally does not attempt to redact arbitrary secrets
    by guessing field names. The caller should construct a dedicated
    EnergyPilot context containing only fields the LLM needs.
    """
    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping/dictionary.")

    try:
        serialized = json.dumps(
            context,
            default=str,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise LLMValidationError(
            "EnergyPilot context could not be serialized as JSON."
        ) from exc

    return json.loads(serialized)


def _serialize_context(
    context: Mapping[str, Any],
    max_bytes: int,
) -> str:
    """Serialize context while enforcing a predictable request size."""
    sanitized = _sanitize_context(context)

    serialized = json.dumps(
        sanitized,
        indent=2,
        ensure_ascii=False,
    )

    size = len(serialized.encode("utf-8"))

    if size > max_bytes:
        raise LLMValidationError(
            "EnergyPilot context is too large for the LLM request "
            f"({size:,} bytes; maximum {max_bytes:,})."
        )

    return serialized


# =============================================================================
# Response parsing
# =============================================================================

def _strip_json_fences(content: str) -> str:
    """
    Remove Markdown JSON fences if a provider/model adds them despite the
    JSON-only instruction.
    """
    text = content.strip()

    match = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if match:
        return match.group(1).strip()

    return text


def _parse_json_content(content: Any) -> dict[str, Any]:
    """Parse the model's message content into a JSON object."""
    if isinstance(content, dict):
        return content

    if not isinstance(content, str):
        raise LLMResponseError(
            "OpenRouter returned recommendation content in an "
            "unsupported format."
        )

    cleaned = _strip_json_fences(content)

    if not cleaned:
        raise LLMResponseError(
            "OpenRouter returned an empty recommendation response."
        )

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMResponseError(
            "OpenRouter returned invalid JSON."
        ) from exc

    if not isinstance(parsed, dict):
        raise LLMResponseError(
            "OpenRouter recommendation response must be a JSON object."
        )

    return parsed


# =============================================================================
# Value validation
# =============================================================================

VALID_PRIORITIES = frozenset(
    {"high", "medium", "low"}
)

VALID_DIFFICULTIES = frozenset(
    {"easy", "moderate", "advanced"}
)

MAX_RECOMMENDATIONS = 10

MAX_STRING_LENGTH = 2_000

MAX_EVIDENCE_ITEMS = 10


def _require_string(
    value: Any,
    field: str,
) -> str:
    """Validate a required non-empty response string."""
    if not isinstance(value, str):
        raise LLMValidationError(
            f"Recommendation field '{field}' must be a string."
        )

    normalized = value.strip()

    if not normalized:
        raise LLMValidationError(
            f"Recommendation field '{field}' cannot be empty."
        )

    if len(normalized) > MAX_STRING_LENGTH:
        raise LLMValidationError(
            f"Recommendation field '{field}' exceeds "
            f"{MAX_STRING_LENGTH} characters."
        )

    return normalized


def _optional_money(
    value: Any,
    field: str,
) -> float | None:
    """
    Validate an optional CAD savings estimate.

    Negative savings are rejected because the schema represents estimated
    savings, not costs.
    """
    if value is None:
        return None

    if isinstance(value, bool):
        raise LLMValidationError(
            f"'{field}' must be a number or null."
        )

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMValidationError(
            f"'{field}' must be a number or null."
        ) from exc

    if not np_is_finite(numeric):
        raise LLMValidationError(
            f"'{field}' must be finite."
        )

    if numeric < 0:
        raise LLMValidationError(
            f"'{field}' cannot be negative."
        )

    return numeric


def np_is_finite(value: float) -> bool:
    """
    Small local finite-number check.

    Avoiding a NumPy dependency here keeps this integration layer lightweight;
    the ML layer already depends on NumPy separately.
    """
    return value == value and abs(value) != float("inf")


def _confidence(value: Any) -> float:
    """Validate and clamp model confidence to [0, 1]."""
    if isinstance(value, bool):
        raise LLMValidationError(
            "confidence must be a number between 0 and 1."
        )

    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMValidationError(
            "confidence must be a number between 0 and 1."
        ) from exc

    if not np_is_finite(confidence):
        raise LLMValidationError(
            "confidence must be finite."
        )

    if not 0 <= confidence <= 1:
        raise LLMValidationError(
            "confidence must be between 0 and 1."
        )

    return confidence


def _evidence(value: Any) -> tuple[Any, ...]:
    """Validate and cap evidence entries."""
    if value is None:
        return ()

    if not isinstance(value, list):
        raise LLMValidationError(
            "evidence must be an array."
        )

    return tuple(value[:MAX_EVIDENCE_ITEMS])


# =============================================================================
# Recommendation validation
# =============================================================================

def _parse_recommendation(
    value: Any,
) -> EnergyRecommendation:
    """Convert one raw LLM recommendation into a validated object."""
    if not isinstance(value, dict):
        raise LLMValidationError(
            "Each recommendation must be a JSON object."
        )

    title = _require_string(
        value.get("title"),
        "title",
    )

    description = _require_string(
        value.get("description"),
        "description",
    )

    category = _require_string(
        value.get("category"),
        "category",
    )

    priority = _require_string(
        value.get("priority"),
        "priority",
    ).lower()

    if priority not in VALID_PRIORITIES:
        raise LLMValidationError(
            "priority must be one of: high, medium, low."
        )

    difficulty = _require_string(
        value.get("difficulty"),
        "difficulty",
    ).lower()

    if difficulty not in VALID_DIFFICULTIES:
        raise LLMValidationError(
            "difficulty must be one of: easy, moderate, advanced."
        )

    return EnergyRecommendation(
        title=title,
        description=description,
        category=category,
        priority=priority,
        estimated_monthly_savings=_optional_money(
            value.get("estimated_monthly_savings"),
            "estimated_monthly_savings",
        ),
        estimated_annual_savings=_optional_money(
            value.get("estimated_annual_savings"),
            "estimated_annual_savings",
        ),
        difficulty=difficulty,
        reason=_require_string(
            value.get("reason"),
            "reason",
        ),
        action=_require_string(
            value.get("action"),
            "action",
        ),
        confidence=_confidence(
            value.get("confidence")
        ),
        evidence=_evidence(
            value.get("evidence")
        ),
    )


def validate_response(
    value: Any,
) -> RecommendationResponse:
    """
    Validate the complete LLM response.

    This is essential because JSON syntax alone does not guarantee that the
    response follows EnergyPilot's application contract.
    """
    if not isinstance(value, dict):
        raise LLMValidationError(
            "LLM response must be a JSON object."
        )

    summary = _require_string(
        value.get("summary"),
        "summary",
    )

    recommendations = value.get("recommendations")

    if not isinstance(recommendations, list):
        raise LLMValidationError(
            "'recommendations' must be an array."
        )

    if len(recommendations) > MAX_RECOMMENDATIONS:
        raise LLMValidationError(
            f"At most {MAX_RECOMMENDATIONS} recommendations are allowed."
        )

    parsed = tuple(
        _parse_recommendation(recommendation)
        for recommendation in recommendations
    )

    return RecommendationResponse(
        summary=summary,
        recommendations=parsed,
    )


# =============================================================================
# HTTP helpers
# =============================================================================

def _build_headers(config: LLMConfig) -> dict[str, str]:
    """Build OpenRouter request headers."""
    return {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "HTTP-Referer": config.app_url,
        "X-Title": config.app_title,
    }


def _is_retryable_status(status_code: int) -> bool:
    """
    Identify transient HTTP failures.

    429 indicates rate limiting; 5xx generally indicates a provider-side
    failure. Authentication and validation errors should fail immediately.
    """
    return status_code == 429 or 500 <= status_code <= 599


def _request_openrouter(
    config: LLMConfig,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Send the OpenRouter request with bounded retries.

    Retries are intentionally limited because LLM requests can be expensive
    and repeated retries should not turn a temporary failure into a long
    blocking API request.
    """
    headers = _build_headers(config)

    timeout = (
        config.connect_timeout_seconds,
        config.timeout_seconds,
    )

    attempts = config.max_retries + 1

    for attempt in range(attempts):
        try:
            response = requests.post(
                config.url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )

        except requests.Timeout as exc:
            if attempt >= config.max_retries:
                raise LLMRequestError(
                    "OpenRouter request timed out."
                ) from exc

            LOGGER.warning(
                "OpenRouter request timed out; retrying "
                "(attempt %d/%d).",
                attempt + 1,
                attempts,
            )

            time.sleep(
                config.retry_delay_seconds * (2**attempt)
            )
            continue

        except requests.RequestException as exc:
            if attempt >= config.max_retries:
                raise LLMRequestError(
                    "OpenRouter request failed."
                ) from exc

            LOGGER.warning(
                "OpenRouter request failed; retrying "
                "(attempt %d/%d): %s",
                attempt + 1,
                attempts,
                exc,
            )

            time.sleep(
                config.retry_delay_seconds * (2**attempt)
            )
            continue

        if (
            _is_retryable_status(response.status_code)
            and attempt < config.max_retries
        ):
            LOGGER.warning(
                "OpenRouter returned HTTP %d; retrying "
                "(attempt %d/%d).",
                response.status_code,
                attempt + 1,
                attempts,
            )

            time.sleep(
                config.retry_delay_seconds * (2**attempt)
            )
            continue

        if response.status_code >= 400:
            # Do not include the Authorization header or request payload in
            # the error. Provider responses can contain sensitive details.
            detail = response.text[:500].strip()

            raise LLMRequestError(
                "OpenRouter returned HTTP "
                f"{response.status_code}"
                + (f": {detail}" if detail else ".")
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise LLMResponseError(
                "OpenRouter returned a non-JSON HTTP response."
            ) from exc

        if not isinstance(result, dict):
            raise LLMResponseError(
                "OpenRouter response must be a JSON object."
            )

        return result

    raise LLMRequestError(
        "OpenRouter request failed after all retry attempts."
    )


# =============================================================================
# Public service
# =============================================================================

def generate_energy_recommendations(
    context: dict[str, Any],
    *,
    config: LLMConfig | None = None,
) -> dict[str, Any]:
    """
    Generate validated EnergyPilot recommendations.

    Parameters
    ----------
    context:
        Structured, deterministic EnergyPilot facts.

    config:
        Optional pre-built LLMConfig. Supplying one is useful for testing
        and avoids repeatedly reading environment variables.

    Returns
    -------
    dict
        Validated JSON-compatible recommendation structure.

    Raises
    ------
    LLMError
        For configuration, transport, provider, parsing, or schema failures.
    """
    if config is None:
        config = load_config()

    context_json = _serialize_context(
        context,
        config.max_context_bytes,
    )

    user_prompt = f"""
Here is the structured EnergyPilot context:

{context_json}

Analyze this household's energy situation.

Prioritize recommendations that are:

- financially meaningful when supported by supplied calculations
- realistic
- explainable
- supported by the provided evidence
- sensitive to supplied weather information
- sensitive to supplied Ontario electricity pricing
- safe for a homeowner to act on

Do not perform new financial calculations. Use supplied deterministic estimates
when they exist.
""".strip()

    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": config.temperature,
        "response_format": {
            "type": "json_object",
        },
    }

    LOGGER.info(
        "Generating EnergyPilot recommendations using model '%s'.",
        config.model,
    )

    result = _request_openrouter(
        config,
        payload,
    )

    try:
        choices = result["choices"]

        if not isinstance(choices, list) or not choices:
            raise KeyError("choices")

        message = choices[0]["message"]
        content = message["content"]

    except (KeyError, IndexError, TypeError) as exc:
        raise LLMResponseError(
            "OpenRouter response did not contain a usable "
            "assistant message."
        ) from exc

    parsed = _parse_json_content(content)

    validated = validate_response(parsed)

    return validated.to_dict()


# =============================================================================
# Convenience / health helpers
# =============================================================================

def is_llm_configured() -> bool:
    """
    Return whether the minimum OpenRouter configuration exists.

    This is useful for `/api/health` without making an external API request.
    """
    return bool(
        os.getenv("OPENROUTER_API_KEY", "").strip()
    )


__all__ = [
    "EnergyRecommendation",
    "LLMConfig",
    "LLMError",
    "LLMConfigurationError",
    "LLMRequestError",
    "LLMResponseError",
    "LLMValidationError",
    "RecommendationResponse",
    "generate_energy_recommendations",
    "is_llm_configured",
    "load_config",
    "validate_response",
]