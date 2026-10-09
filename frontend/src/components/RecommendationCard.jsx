import { useCallback, useId, useMemo, useState } from "react";
import PropTypes from "prop-types";
import {
  ArrowRight,
  BatteryCharging,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  CircleDollarSign,
  Gauge,
  Home,
  Info,
  Lightbulb,
  Settings2,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  Zap,
} from "lucide-react";
import "./RecommendationCard.css";

/* ============================================================================
   Constants & Configuration
   ========================================================================== */

const DEFAULT_TITLE = "Energy-saving opportunity";
const DEFAULT_DESCRIPTION =
  "EnergyPilot identified an opportunity to reduce energy consumption or electricity costs.";
const DEFAULT_REASON =
  "This recommendation is based on the household's modeled energy-use profile.";
const DEFAULT_ACTION =
  "Review the recommendation and evaluate whether the suggested change fits your household.";

const DEFAULT_CATEGORY = "efficiency";
const DEFAULT_PRIORITY = "medium";
const DEFAULT_IMPACT = "medium";
const DEFAULT_DIFFICULTY = "moderate";
const MAX_TAGS = 8;

const PRIORITIES = Object.freeze({
  HIGH: "high",
  MEDIUM: "medium",
  LOW: "low",
});

const TITLE_FIELDS = Object.freeze(["title", "name", "recommendation"]);
const DESCRIPTION_FIELDS = Object.freeze(["description", "summary", "details"]);
const CATEGORY_FIELDS = Object.freeze(["category", "type", "recommendation_type"]);
const PRIORITY_FIELDS = Object.freeze(["priority", "severity"]);
const IMPACT_FIELDS = Object.freeze(["impact", "expected_impact"]);
const DIFFICULTY_FIELDS = Object.freeze([
  "difficulty",
  "implementation_difficulty",
]);
const MONTHLY_SAVINGS_FIELDS = Object.freeze([
  "monthly_savings",
  "estimated_monthly_savings",
  "estimated_savings",
  "savings",
]);
const ANNUAL_SAVINGS_FIELDS = Object.freeze([
  "annual_savings",
  "estimated_annual_savings",
]);
const COST_FIELDS = Object.freeze([
  "estimated_cost",
  "implementation_cost",
  "cost",
]);
const PAYBACK_FIELDS = Object.freeze([
  "payback_months",
  "estimated_payback_months",
]);
const CONFIDENCE_FIELDS = Object.freeze([
  "confidence",
  "model_confidence",
  "recommendation_confidence",
]);
const REASON_FIELDS = Object.freeze(["reason", "rationale", "why"]);
const ACTION_FIELDS = Object.freeze(["action", "recommended_action", "next_step"]);
const TAG_FIELDS = Object.freeze(["tags", "labels"]);

/* ============================================================================
   Static Formatters (Hoisted for performance)
   ========================================================================== */

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/* ============================================================================
   Data Extraction & Helper Functions
   ========================================================================== */

function getFirstDefinedValue(object, fields) {
  if (!object || typeof object !== "object") return null;

  for (const field of fields) {
    const value = object[field];
    if (value !== undefined && value !== null && value !== "") {
      return value;
    }
  }

  return null;
}

function toFiniteNumber(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    typeof value === "boolean"
  ) {
    return null;
  }

  const number =
    typeof value === "number"
      ? value
      : Number.parseFloat(String(value).replace(/[$,\s]/g, ""));

  return Number.isFinite(number) ? number : null;
}

function getTextValue(object, fields, fallback) {
  const value = getFirstDefinedValue(object, fields);
  if (value === null) return fallback;

  const text = String(value).trim();
  return text || fallback;
}

function normalizeRecommendationPayload(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return null;
  }

  const wrapperKeys = ["recommendation", "data", "result"];
  let current = value;

  for (let depth = 0; depth < 3; depth += 1) {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      break;
    }

    const nestedKey = wrapperKeys.find((key) => {
      const nested = current[key];
      return (
        nested &&
        typeof nested === "object" &&
        !Array.isArray(nested)
      );
    });

    if (!nestedKey) break;
    current = current[nestedKey];
  }

  return current;
}

function formatCurrency(value) {
  const number = toFiniteNumber(value);
  if (number === null) return "—";
  return CURRENCY_FORMATTER.format(Math.max(number, 0));
}

function calculateAnnualSavings(annualValue, monthlySavings) {
  const annual = toFiniteNumber(annualValue);
  if (annual !== null) return Math.max(annual, 0);

  const monthly = toFiniteNumber(monthlySavings);
  if (monthly !== null) return Math.max(monthly * 12, 0);

  return null;
}

function normalizeConfidence(value) {
  const number = toFiniteNumber(value);
  if (number === null) return null;

  const percentage = number <= 1 ? number * 100 : number;
  return Math.min(Math.max(percentage, 0), 100);
}

function formatPercentage(value) {
  const percentage = normalizeConfidence(value);
  return percentage === null ? "—" : `${Math.round(percentage)}%`;
}

function formatPayback(months) {
  const number = toFiniteNumber(months);
  if (number === null) return "—";
  if (number <= 0) return "Immediate";
  if (number < 1) return "Under 1 month";
  if (Math.abs(number - 1) < 0.001) return "1 month";

  return `${number.toFixed(1)} months`;
}

function formatLabel(value, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  const normalized = String(value)
    .trim()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");

  if (!normalized) return fallback;

  const uppercaseLabels = new Set([
    "hvac",
    "ev",
    "ev charging",
    "led",
    "solar pv",
    "bms",
    "bas",
    "tou",
  ]);

  const key = normalized.toLowerCase();
  if (uppercaseLabels.has(key)) {
    return key.toUpperCase();
  }

  return normalized.replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function normalizePriority(priority) {
  const value = String(priority || DEFAULT_PRIORITY)
    .trim()
    .toLowerCase();

  if (["high", "critical", "urgent"].includes(value)) {
    return PRIORITIES.HIGH;
  }

  if (["low", "minor"].includes(value)) {
    return PRIORITIES.LOW;
  }

  return PRIORITIES.MEDIUM;
}

function normalizeMetric(value, fallback) {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }
  return String(value).trim().toLowerCase();
}

function getCategoryIcon(category) {
  const value = String(category || "").toLowerCase();

  if (/pricing|tariff|cost|rate/.test(value)) return CircleDollarSign;
  if (/load|demand|peak/.test(value)) return Gauge;
  if (/hvac|heating|cooling|thermal/.test(value)) return Home;
  if (/solar|generation|renewable/.test(value)) return Zap;
  if (/battery|storage|backup/.test(value)) return BatteryCharging;
  if (/equipment|device|appliance/.test(value)) return Settings2;
  if (/efficiency|conservation|usage/.test(value)) return TrendingDown;
  if (/security|reliability/.test(value)) return ShieldCheck;

  return Lightbulb;
}

function normalizeTags(tags) {
  if (!Array.isArray(tags)) return [];

  const uniqueTags = new Map();

  for (const tag of tags) {
    if (tag === null || tag === undefined) continue;

    const normalizedTag = String(tag).trim();
    if (!normalizedTag) continue;

    const key = normalizedTag.toLowerCase();
    if (!uniqueTags.has(key)) {
      uniqueTags.set(key, normalizedTag);
    }
  }

  return Array.from(uniqueTags.values()).slice(0, MAX_TAGS);
}

/* ============================================================================
   Empty State Sub-component
   ========================================================================== */

function RecommendationEmptyState({ className = "" }) {
  const titleId = useId();

  return (
    <article
      className={["recommendation-card", "recommendation-card--empty", className]
        .filter(Boolean)
        .join(" ")}
      aria-labelledby={titleId}
    >
      <div className="recommendation-empty-art" aria-hidden="true">
        <div className="recommendation-icon">
          <Lightbulb size={22} strokeWidth={1.8} />
        </div>
        <span className="recommendation-empty-spark">
          <Sparkles size={15} />
        </span>
      </div>

      <div className="recommendation-content">
        <div className="recommendation-top">
          <span className="recommendation-eyebrow">ENERGY INSIGHTS</span>
          <span className="recommendation-status">
            <span className="recommendation-status-dot" aria-hidden="true" />
            Awaiting insights
          </span>
        </div>

        <h3 id={titleId}>No recommendation available</h3>

        <p className="recommendation-description">
          EnergyPilot does not currently have enough information to display a
          recommendation. Check back as more energy data becomes available.
        </p>
      </div>
    </article>
  );
}

RecommendationEmptyState.propTypes = {
  className: PropTypes.string,
};

/* ============================================================================
   Main Component
   ========================================================================== */

export default function RecommendationCard({
  recommendation = null,
  className = "",
}) {
  const [expanded, setExpanded] = useState(false);
  const componentId = useId();
  const titleId = `rec-title-${componentId.replace(/:/g, "")}`;
  const detailsId = `rec-details-${componentId.replace(/:/g, "")}`;

  const data = useMemo(() => {
    const normalized = normalizeRecommendationPayload(recommendation);
    if (!normalized) return null;

    const category = getFirstDefinedValue(normalized, CATEGORY_FIELDS);
    const rawMonthlySavings = getFirstDefinedValue(normalized, MONTHLY_SAVINGS_FIELDS);
    const rawAnnualSavings = getFirstDefinedValue(normalized, ANNUAL_SAVINGS_FIELDS);
    const rawCost = getFirstDefinedValue(normalized, COST_FIELDS);
    const rawPayback = getFirstDefinedValue(normalized, PAYBACK_FIELDS);
    const rawConfidence = getFirstDefinedValue(normalized, CONFIDENCE_FIELDS);

    const monthlySavings = toFiniteNumber(rawMonthlySavings);
    const annualSavings = calculateAnnualSavings(rawAnnualSavings, monthlySavings);
    const cost = toFiniteNumber(rawCost);
    const payback = toFiniteNumber(rawPayback);
    const confidence = normalizeConfidence(rawConfidence);

    const tags = normalizeTags(getFirstDefinedValue(normalized, TAG_FIELDS));
    const normalizedCategory = category || DEFAULT_CATEGORY;

    return {
      title: getTextValue(normalized, TITLE_FIELDS, DEFAULT_TITLE),
      category: normalizedCategory,
      categoryLabel: formatLabel(normalizedCategory, "Energy"),
      description: getTextValue(normalized, DESCRIPTION_FIELDS, DEFAULT_DESCRIPTION),
      priority: normalizePriority(getFirstDefinedValue(normalized, PRIORITY_FIELDS)),
      impact: normalizeMetric(getFirstDefinedValue(normalized, IMPACT_FIELDS), DEFAULT_IMPACT),
      difficulty: normalizeMetric(
        getFirstDefinedValue(normalized, DIFFICULTY_FIELDS),
        DEFAULT_DIFFICULTY
      ),
      monthlySavings: monthlySavings !== null ? Math.max(monthlySavings, 0) : null,
      annualSavings,
      cost: cost !== null ? Math.max(cost, 0) : null,
      payback: payback !== null ? Math.max(payback, 0) : null,
      confidence,
      reason: getTextValue(normalized, REASON_FIELDS, DEFAULT_REASON),
      action: getTextValue(normalized, ACTION_FIELDS, DEFAULT_ACTION),
      tags,
    };
  }, [recommendation]);

  const handleToggleDetails = useCallback(() => {
    setExpanded((prev) => !prev);
  }, []);

  if (!data) {
    return <RecommendationEmptyState className={className} />;
  }

  const CategoryIcon = getCategoryIcon(data.category);
  const hasMonthlySavings = data.monthlySavings !== null;
  const hasAnnualSavings = data.annualSavings !== null;
  const hasFinancialData =
    hasMonthlySavings || hasAnnualSavings || data.cost !== null;

  const cardClassName = [
    "recommendation-card",
    `recommendation-${data.priority}`,
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const priorityLabel = formatLabel(data.priority);
  const impactLabel = formatLabel(data.impact);
  const difficultyLabel = formatLabel(data.difficulty);

  return (
    <article className={cardClassName} aria-labelledby={titleId}>
      <div className="recommendation-accent" aria-hidden="true" />

      <div className="recommendation-card-inner">
        <div className="recommendation-main-icon" aria-hidden="true">
          <CategoryIcon size={22} strokeWidth={1.8} />
          <span className="recommendation-icon-glow" />
        </div>

        <div className="recommendation-content">
          {/* Header */}
          <div className="recommendation-header">
            <div className="recommendation-top">
              <span className="recommendation-eyebrow">ENERGY INSIGHT</span>
              <span className="recommendation-category">{data.categoryLabel}</span>
            </div>

            <span
              className={`recommendation-priority recommendation-priority--${data.priority}`}
              aria-label={`Priority: ${priorityLabel}`}
            >
              <span className="recommendation-priority-dot" aria-hidden="true" />
              {priorityLabel} priority
            </span>
          </div>

          <h3 id={titleId} className="recommendation-title">
            {data.title}
          </h3>

          <p className="recommendation-description">{data.description}</p>

          {/* Savings Callout */}
          {hasFinancialData && (
            <section
              className="recommendation-savings"
              aria-label="Estimated financial opportunity"
            >
              <div className="recommendation-savings-icon" aria-hidden="true">
                <TrendingDown size={19} strokeWidth={2} />
              </div>

              <div className="recommendation-savings-copy">
                <span className="recommendation-section-label">POTENTIAL SAVINGS</span>

                {hasMonthlySavings && (
                  <div className="recommendation-savings-primary">
                    <strong>{formatCurrency(data.monthlySavings)}</strong>
                    <span> / month</span>
                  </div>
                )}

                {!hasMonthlySavings && hasAnnualSavings && (
                  <div className="recommendation-savings-primary">
                    <strong>{formatCurrency(data.annualSavings)}</strong>
                    <span> / year</span>
                  </div>
                )}

                {hasMonthlySavings && hasAnnualSavings && (
                  <p className="recommendation-annual">
                    Up to <strong>{formatCurrency(data.annualSavings)}</strong> annually
                  </p>
                )}
              </div>

              <div className="recommendation-savings-badge">
                <Sparkles size={13} aria-hidden="true" />
                <span>Opportunity</span>
              </div>
            </section>
          )}

          {/* Metrics Grid */}
          <div className="recommendation-metrics" aria-label="Recommendation metrics">
            <div className="recommendation-metric">
              <span className="recommendation-metric-label">Impact</span>
              <strong>{impactLabel}</strong>
            </div>

            <div className="recommendation-metric">
              <span className="recommendation-metric-label">Difficulty</span>
              <strong>{difficultyLabel}</strong>
            </div>

            <div className="recommendation-metric">
              <span className="recommendation-metric-label">Estimated cost</span>
              <strong>{formatCurrency(data.cost)}</strong>
            </div>

            <div className="recommendation-metric">
              <span className="recommendation-metric-label">Payback</span>
              <strong>{formatPayback(data.payback)}</strong>
            </div>
          </div>

          {/* Tags */}
          {data.tags.length > 0 && (
            <div className="recommendation-tags" aria-label="Recommendation tags">
              {data.tags.map((tag) => (
                <span className="recommendation-tag" key={tag.toLowerCase()}>
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Expandable Details Section */}
          <div
            id={detailsId}
            className="recommendation-details"
            hidden={!expanded}
          >
            <div className="recommendation-details-heading">
              <span className="recommendation-details-heading-icon" aria-hidden="true">
                <Info size={16} />
              </span>
              <div>
                <h4>Recommendation details</h4>
                <p>Understand the rationale and next steps.</p>
              </div>
            </div>

            <div className="recommendation-detail-row">
              <div className="recommendation-detail-icon" aria-hidden="true">
                <Lightbulb size={17} />
              </div>
              <div className="recommendation-detail-copy">
                <strong>Why we recommend this</strong>
                <p>{data.reason}</p>
              </div>
            </div>

            <div className="recommendation-detail-row">
              <div className="recommendation-detail-icon" aria-hidden="true">
                <ArrowRight size={17} />
              </div>
              <div className="recommendation-detail-copy">
                <strong>Recommended next step</strong>
                <p>{data.action}</p>
              </div>
            </div>

            {/* Confidence Gauge */}
            {data.confidence !== null && (
              <div className="recommendation-confidence">
                <div className="confidence-header">
                  <div>
                    <strong>Model confidence</strong>
                    <span>Confidence in this recommendation</span>
                  </div>
                  <strong className="confidence-value">
                    {formatPercentage(data.confidence)}
                  </strong>
                </div>

                <div
                  className="confidence-bar"
                  role="progressbar"
                  aria-valuenow={Math.round(data.confidence)}
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-label="Recommendation confidence level"
                >
                  <div
                    className="confidence-fill"
                    style={{ width: `${data.confidence}%` }}
                  />
                </div>
              </div>
            )}

            <div className="recommendation-model-note">
              <CheckCircle2 size={15} aria-hidden="true" />
              <span>Generated from EnergyPilot analysis</span>
            </div>
          </div>

          {/* Footer Action */}
          <footer className="recommendation-bottom">
            <div className="recommendation-bottom-brand">
              <span className="recommendation-brand-icon" aria-hidden="true">
                <Sparkles size={14} />
              </span>
              <span>EnergyPilot</span>
              <span className="recommendation-footer-divider" aria-hidden="true" />
              <span className="recommendation-footer-caption">Energy opportunity</span>
            </div>

            <button
              type="button"
              className="recommendation-action"
              onClick={handleToggleDetails}
              aria-expanded={expanded}
              aria-controls={detailsId}
            >
              <span>{expanded ? "Hide details" : "Explore details"}</span>
              {expanded ? (
                <ChevronUp size={16} aria-hidden="true" />
              ) : (
                <ChevronDown size={16} aria-hidden="true" />
              )}
            </button>
          </footer>
        </div>
      </div>
    </article>
  );
}

RecommendationCard.propTypes = {
  recommendation: PropTypes.object,
  className: PropTypes.string,
};