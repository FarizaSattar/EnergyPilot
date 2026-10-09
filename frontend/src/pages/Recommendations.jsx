import React, { useMemo, useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Clock,
  DollarSign,
  Flame,
  Gauge,
  Lightbulb,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  Zap,
} from "lucide-react";
import "./Recommendations.css";

/* ==========================================================================
   EnergyPilot — Recommendations Page
   ========================================================================== */

const DEFAULT_CATEGORY = "general";
const DEFAULT_PRIORITY = "medium";
const DEFAULT_DIFFICULTY = "moderate";
const DEFAULT_IMPACT = "medium";

const MAX_TAGS = 8;

const PRIORITY_SCORE = Object.freeze({
  critical: 4,
  high: 3,
  medium: 2,
  low: 1,
});

const CATEGORY_LABELS = Object.freeze({
  pricing: "Rate plan",
  "rate-plan": "Rate plan",
  rate_plan: "Rate plan",
  load_shifting: "Load shifting",
  "load-shifting": "Load shifting",
  load: "Load management",
  efficiency: "Efficiency",
  hvac: "HVAC",
  heating: "Heating",
  cooling: "Cooling",
  rebate: "Rebate",
  rebates: "Rebates",
  insulation: "Building envelope",
  solar: "Solar",
  general: "Energy",
});

const DIFFICULTY_MESSAGES = Object.freeze({
  easy: "Can usually be implemented immediately.",
  moderate: "Requires some planning or configuration.",
  difficult: "Likely requires a larger project or investment.",
  hard: "Likely requires a larger project or investment.",
});

/* ==========================================================================
   Formatters & Helper Utilities
   ========================================================================== */

const CURRENCY_FORMATTER = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const WHOLE_CURRENCY_FORMATTER = new Intl.NumberFormat("en-CA", {
  style: "currency",
  currency: "CAD",
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

function toFiniteNumber(value) {
  if (
    value === null ||
    value === undefined ||
    value === "" ||
    typeof value === "boolean"
  ) {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function firstDefined(...values) {
  return values.find(
    (value) =>
      value !== undefined &&
      value !== null &&
      value !== ""
  );
}

function toNonNegativeNumber(value) {
  const number = toFiniteNumber(value);
  return number === null || number < 0 ? null : number;
}

function normalizeKey(value, fallback = "") {
  return String(value ?? fallback)
    .trim()
    .toLowerCase()
    .replace(/[\s-]+/g, "_");
}

function formatLabel(value, fallback = "Unknown") {
  const text = String(value ?? "").trim();
  if (!text) return fallback;

  return text
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatCurrency(value) {
  const number = toFiniteNumber(value);
  return number === null ? "—" : CURRENCY_FORMATTER.format(number);
}

function formatWholeCurrency(value) {
  const number = toFiniteNumber(value);
  return number === null ? "—" : WHOLE_CURRENCY_FORMATTER.format(number);
}

function normalizeConfidence(value) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return null;

  const percentage = number <= 1 ? number * 100 : number;
  return Math.round(Math.min(100, percentage));
}

function getAnnualSavings(recommendation, monthlySavings) {
  const explicitAnnualSavings = toNonNegativeNumber(
    firstDefined(
      recommendation.annual_savings,
      recommendation.annualSavings
    )
  );

  if (explicitAnnualSavings !== null) return explicitAnnualSavings;
  if (monthlySavings !== null) return monthlySavings * 12;

  return null;
}

function normalizeTags(tags) {
  if (!Array.isArray(tags)) return [];

  const seen = new Set();
  const normalized = [];

  for (const tag of tags) {
    const value = String(tag ?? "").trim();
    if (!value) continue;

    const key = value.toLowerCase();
    if (seen.has(key)) continue;

    seen.add(key);
    normalized.push(value);

    if (normalized.length >= MAX_TAGS) break;
  }

  return normalized;
}

function normalizeRecommendation(recommendation, index) {
  if (
    !recommendation ||
    typeof recommendation !== "object" ||
    Array.isArray(recommendation)
  ) {
    return null;
  }

  const savings = toNonNegativeNumber(
    firstDefined(
      recommendation.estimated_savings,
      recommendation.estimatedSavings,
      recommendation.savings,
      recommendation.monthly_savings
    )
  );

  const annualSavings = getAnnualSavings(recommendation, savings);

  const cost = toNonNegativeNumber(
    firstDefined(
      recommendation.estimated_cost,
      recommendation.estimatedCost,
      recommendation.cost,
      recommendation.implementation_cost
    )
  );

  const paybackMonths = toNonNegativeNumber(
    firstDefined(
      recommendation.payback_months,
      recommendation.paybackMonths,
      recommendation.payback
    )
  );

  const confidence = normalizeConfidence(recommendation.confidence);

  const category =
    firstDefined(
      recommendation.category,
      recommendation.type
    ) ?? DEFAULT_CATEGORY;

  const priority =
    firstDefined(
      recommendation.priority,
      recommendation.urgency
    ) ?? DEFAULT_PRIORITY;

  const difficulty =
    firstDefined(
      recommendation.difficulty,
      recommendation.effort
    ) ?? DEFAULT_DIFFICULTY;

  const impact =
    firstDefined(
      recommendation.impact,
      recommendation.impact_level
    ) ?? DEFAULT_IMPACT;

  const backendId = firstDefined(
    recommendation.id,
    recommendation.recommendation_id
  );

  const id =
    backendId !== undefined ? String(backendId) : `recommendation-${index}`;

  return {
    ...recommendation,
    id,
    title:
      firstDefined(recommendation.title, recommendation.name) ??
      "Energy-saving opportunity",
    description:
      firstDefined(recommendation.description, recommendation.summary) ??
      "EnergyPilot identified an opportunity based on your energy profile.",
    category,
    priority,
    impact,
    difficulty,
    savings,
    annualSavings,
    cost,
    paybackMonths,
    confidence,
    action:
      firstDefined(
        recommendation.action,
        recommendation.recommended_action,
        recommendation.recommendedAction
      ) ??
      "Review this opportunity and determine whether it fits your household.",
    reason:
      firstDefined(
        recommendation.reason,
        recommendation.why,
        recommendation.explanation
      ) ??
      "This recommendation was generated from your household's energy usage pattern.",
    tags: normalizeTags(recommendation.tags),
  };
}

function formatCategory(category) {
  const key = normalizeKey(category, DEFAULT_CATEGORY);
  return CATEGORY_LABELS[key] ?? formatLabel(category, "Energy");
}

function formatPriority(priority) {
  return formatLabel(priority, DEFAULT_PRIORITY);
}

function formatDifficulty(difficulty) {
  return formatLabel(difficulty, DEFAULT_DIFFICULTY);
}

function getCategoryIcon(category) {
  const key = normalizeKey(category);

  if (key.includes("pricing") || key.includes("rate")) {
    return <DollarSign size={18} aria-hidden="true" />;
  }
  if (
    key.includes("hvac") ||
    key.includes("heating") ||
    key.includes("cooling")
  ) {
    return <Flame size={18} aria-hidden="true" />;
  }
  if (key.includes("rebate") || key.includes("solar")) {
    return <Sparkles size={18} aria-hidden="true" />;
  }
  if (key.includes("efficiency") || key.includes("load")) {
    return <Gauge size={18} aria-hidden="true" />;
  }

  return <Lightbulb size={18} aria-hidden="true" />;
}

function getDifficultyMessage(difficulty) {
  const key = normalizeKey(difficulty);
  return (
    DIFFICULTY_MESSAGES[key] ??
    "Review the implementation requirements before proceeding."
  );
}

function calculateSummary(recommendations) {
  let totalMonthlySavings = 0;
  let totalAnnualSavings = 0;
  let hasMonthlySavings = false;
  let hasAnnualSavings = false;
  let highPriorityCount = 0;
  let easyActions = 0;

  for (const recommendation of recommendations) {
    if (recommendation.savings !== null) {
      totalMonthlySavings += recommendation.savings;
      hasMonthlySavings = true;
    }

    if (recommendation.annualSavings !== null) {
      totalAnnualSavings += recommendation.annualSavings;
      hasAnnualSavings = true;
    }

    if (normalizeKey(recommendation.priority) === "high") {
      highPriorityCount += 1;
    }

    if (normalizeKey(recommendation.difficulty) === "easy") {
      easyActions += 1;
    }
  }

  return {
    totalMonthlySavings: hasMonthlySavings ? totalMonthlySavings : null,
    totalAnnualSavings: hasAnnualSavings ? totalAnnualSavings : null,
    highPriorityCount,
    easyActions,
  };
}

function sortRecommendations(recommendations) {
  return recommendations
    .map((recommendation, originalIndex) => ({
      recommendation,
      originalIndex,
    }))
    .sort((a, b) => {
      const priorityDifference =
        (PRIORITY_SCORE[normalizeKey(b.recommendation.priority)] ?? 0) -
        (PRIORITY_SCORE[normalizeKey(a.recommendation.priority)] ?? 0);

      if (priorityDifference !== 0) {
        return priorityDifference;
      }

      const bSavings = b.recommendation.savings ?? -1;
      const aSavings = a.recommendation.savings ?? -1;

      if (bSavings !== aSavings) {
        return bSavings - aSavings;
      }

      return a.originalIndex - b.originalIndex;
    })
    .map(({ recommendation }) => recommendation);
}

/* ==========================================================================
   State Views (Empty, Error, Loading)
   ========================================================================== */

function EmptyRecommendations() {
  return (
    <div className="page recommendations-page">
      <div className="page-header">
        <div>
          <span className="eyebrow">SAVINGS ENGINE</span>
          <h1>
            Your personalized
            <br />
            savings plan.
          </h1>
          <p>
            EnergyPilot translates your usage patterns into actionable
            opportunities.
          </p>
        </div>
      </div>

      <section
        className="panel empty-recommendations"
        aria-labelledby="empty-recommendations-title"
      >
        <div className="empty-recommendations-icon" aria-hidden="true">
          <Lightbulb size={28} />
        </div>
        <h2 id="empty-recommendations-title">No opportunities yet</h2>
        <p>
          Upload or generate more household electricity data so EnergyPilot
          can analyze your consumption patterns.
        </p>
      </section>
    </div>
  );
}

function RecommendationsError({ error }) {
  const message = typeof error === "string" ? error : error?.message;

  return (
    <div className="page recommendations-page">
      <div className="page-header">
        <div>
          <span className="eyebrow">SAVINGS ENGINE</span>
          <h1>Recommendations</h1>
          <p>EnergyPilot could not load the recommendation data.</p>
        </div>
      </div>

      <section
        className="panel empty-recommendations"
        role="alert"
        aria-labelledby="recommendations-error-title"
      >
        <div className="empty-recommendations-icon" aria-hidden="true">
          <ShieldCheck size={28} />
        </div>
        <h2 id="recommendations-error-title">
          Unable to load recommendations
        </h2>
        <p>
          {message ||
            "An unexpected error occurred while loading the recommendation data."}
        </p>
      </section>
    </div>
  );
}

function RecommendationsLoading() {
  return (
    <div className="page recommendations-page" aria-busy="true">
      <div className="page-header">
        <div>
          <span className="eyebrow">SAVINGS ENGINE</span>
          <h1>
            Your personalized
            <br />
            savings plan.
          </h1>
          <p>Analyzing your energy opportunities...</p>
        </div>
      </div>

      <div className="stats-grid" aria-hidden="true">
        {[1, 2, 3, 4].map((item) => (
          <section
            className="stat-card recommendations-skeleton-card"
            key={item}
          >
            <span className="recommendations-skeleton recommendations-skeleton-label" />
            <span className="recommendations-skeleton recommendations-skeleton-value" />
            <span className="recommendations-skeleton recommendations-skeleton-text" />
          </section>
        ))}
      </div>

      <div className="recommendations-list" aria-hidden="true">
        {[1, 2, 3].map((item) => (
          <section
            className="recommendation-item recommendations-skeleton-item"
            key={item}
          >
            <span className="recommendations-skeleton recommendations-skeleton-number" />
            <div className="recommendations-skeleton-content">
              <span className="recommendations-skeleton recommendations-skeleton-small" />
              <span className="recommendations-skeleton recommendations-skeleton-title" />
              <span className="recommendations-skeleton recommendations-skeleton-description" />
            </div>
          </section>
        ))}
      </div>

      <span className="sr-only">Loading recommendations</span>
    </div>
  );
}

/* ==========================================================================
   Recommendation Item Component
   ========================================================================== */

function RecommendationItem({ recommendation, index }) {
  const [expanded, setExpanded] = useState(index === 0);

  const priority = normalizeKey(
    recommendation.priority,
    DEFAULT_PRIORITY
  );

  const difficulty = normalizeKey(
    recommendation.difficulty,
    DEFAULT_DIFFICULTY
  );

  const safeId = String(recommendation.id).replace(/[^a-zA-Z0-9_-]/g, "-");
  const detailsId = `recommendation-details-${safeId}-${index}`;
  const titleId = `${detailsId}-title`;

  return (
    <article
      className={`recommendation-item priority-${priority}`}
      aria-labelledby={titleId}
    >
      {/* Main recommendation row */}
      <div className="recommendation-main">
        <div className="recommendation-number" aria-hidden="true">
          {String(index + 1).padStart(2, "0")}
        </div>

        <div className="recommendation-icon" aria-hidden="true">
          {getCategoryIcon(recommendation.category)}
        </div>

        <div className="recommendation-content">
          <div className="recommendation-meta">
            <span className="recommendation-category">
              {formatCategory(recommendation.category)}
            </span>

            <span className={`priority-badge ${priority}`}>
              {formatPriority(recommendation.priority)}
            </span>
          </div>

          <h2 id={titleId}>{recommendation.title}</h2>

          <p>{recommendation.description}</p>
        </div>

        <div
          className="recommendation-savings"
          aria-label={
            recommendation.savings !== null
              ? `Estimated savings ${formatCurrency(
                  recommendation.savings
                )} per month`
              : "Estimated monthly savings unavailable"
          }
        >
          <span>Estimated savings</span>

          <strong>
            {formatCurrency(recommendation.savings)}

            {recommendation.savings !== null && <small>/month</small>}
          </strong>
        </div>

        <button
          type="button"
          className="recommendation-expand"
          onClick={() => setExpanded((current) => !current)}
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={
            expanded
              ? `Collapse details for ${recommendation.title}`
              : `Expand details for ${recommendation.title}`
          }
        >
          {expanded ? (
            <ChevronUp size={19} aria-hidden="true" />
          ) : (
            <ChevronDown size={19} aria-hidden="true" />
          )}
        </button>
      </div>

      {/* Expanded recommendation details */}
      {expanded && (
        <div id={detailsId} className="recommendation-details">
          {/* Why */}
          <div className="recommendation-reason">
            <div className="detail-icon" aria-hidden="true">
              <Lightbulb size={17} />
            </div>

            <div>
              <span className="detail-label">WHY THIS WAS RECOMMENDED</span>
              <p>{recommendation.reason}</p>
            </div>
          </div>

          {/* Action */}
          <div className="recommendation-action">
            <div className="detail-icon" aria-hidden="true">
              <ArrowRight size={17} />
            </div>

            <div>
              <span className="detail-label">RECOMMENDED ACTION</span>
              <p>{recommendation.action}</p>
            </div>
          </div>

          {/* Metrics */}
          <div className="recommendation-metrics">
            <div className="recommendation-metric">
              <DollarSign size={17} aria-hidden="true" />

              <div>
                <span>Annual savings</span>
                <strong>
                  {formatWholeCurrency(recommendation.annualSavings)}
                </strong>
              </div>
            </div>

            <div className="recommendation-metric">
              <Gauge size={17} aria-hidden="true" />

              <div>
                <span>Difficulty</span>
                <strong>
                  {formatDifficulty(recommendation.difficulty)}
                </strong>
              </div>
            </div>

            <div className="recommendation-metric">
              <Zap size={17} aria-hidden="true" />

              <div>
                <span>Estimated cost</span>
                <strong>
                  {formatWholeCurrency(recommendation.cost)}
                </strong>
              </div>
            </div>

            {recommendation.paybackMonths !== null && (
              <div className="recommendation-metric">
                <Clock size={17} aria-hidden="true" />

                <div>
                  <span>Payback</span>
                  <strong>
                    {recommendation.paybackMonths === 0
                      ? "Immediate"
                      : `${recommendation.paybackMonths.toFixed(1)} mo`}
                  </strong>
                </div>
              </div>
            )}

            {recommendation.confidence !== null && (
              <div className="recommendation-metric">
                <ShieldCheck size={17} aria-hidden="true" />

                <div>
                  <span>Model confidence</span>
                  <strong>{recommendation.confidence}%</strong>
                </div>
              </div>
            )}
          </div>

          {/* Confidence */}
          {recommendation.confidence !== null && (
            <div className="recommendation-confidence">
              <div className="recommendation-confidence__header">
                <span>Confidence</span>
                <strong>{recommendation.confidence}%</strong>
              </div>

              <div
                className="recommendation-confidence__track"
                role="progressbar"
                aria-label="Model confidence"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={recommendation.confidence}
              >
                <div
                  className="recommendation-confidence__fill"
                  style={{ width: `${recommendation.confidence}%` }}
                />
              </div>
            </div>
          )}

          {/* Tags */}
          {recommendation.tags.length > 0 && (
            <div
              className="recommendation-tags"
              aria-label="Recommendation tags"
            >
              {recommendation.tags.map((tag, tagIndex) => (
                <span
                  key={`${recommendation.id}-tag-${tagIndex}`}
                  className="recommendation-tag"
                >
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Footer */}
          <div className="recommendation-footer">
            <div className="implementation-note">
              <Clock size={15} aria-hidden="true" />

              <span>{getDifficultyMessage(difficulty)}</span>
            </div>

            <button
              type="button"
              className="recommendation-action-button"
              aria-label={`Review opportunity: ${recommendation.title}`}
            >
              Review opportunity
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          </div>
        </div>
      )}
    </article>
  );
}

/* ==========================================================================
   Main Recommendations Component
   ========================================================================== */

export default function Recommendations({
  recommendations = [],
  loading = false,
  error = null,
}) {
  const normalizedRecommendations = useMemo(() => {
    if (!Array.isArray(recommendations)) {
      return [];
    }

    return recommendations
      .map(normalizeRecommendation)
      .filter(Boolean);
  }, [recommendations]);

  const sortedRecommendations = useMemo(
    () => sortRecommendations(normalizedRecommendations),
    [normalizedRecommendations]
  );

  const summary = useMemo(
    () => calculateSummary(normalizedRecommendations),
    [normalizedRecommendations]
  );

  if (loading) {
    return <RecommendationsLoading />;
  }

  if (error) {
    return <RecommendationsError error={error} />;
  }

  if (normalizedRecommendations.length === 0) {
    return <EmptyRecommendations />;
  }

  return (
    <div className="page recommendations-page">
      {/* HEADER */}
      <div className="page-header">
        <div>
          <span className="eyebrow">SAVINGS ENGINE</span>

          <h1>
            Your personalized
            <br />
            savings plan.
          </h1>

          <p>
            EnergyPilot translates your usage patterns into actionable
            opportunities.
          </p>
        </div>

        <div className="date-chip" role="status">
          <Sparkles size={16} aria-hidden="true" />

          <span>
            {normalizedRecommendations.length}{" "}
            {normalizedRecommendations.length === 1
              ? "opportunity"
              : "opportunities"}{" "}
            identified
          </span>
        </div>
      </div>

      {/* SUMMARY STATS */}
      <div className="stats-grid">
        <section
          className="stat-card"
          aria-label="Monthly savings opportunity"
        >
          <span className="stat-label">MONTHLY OPPORTUNITY</span>

          <div className="stat-value">
            {formatCurrency(summary.totalMonthlySavings)}
          </div>

          <p>Combined modeled savings</p>
        </section>

        <section
          className="stat-card"
          aria-label="Annual savings opportunity"
        >
          <span className="stat-label">ANNUAL OPPORTUNITY</span>

          <div className="stat-value">
            {formatWholeCurrency(summary.totalAnnualSavings)}
          </div>

          <p>Annualized from available estimates</p>
        </section>

        <section
          className="stat-card"
          aria-label="High priority recommendations"
        >
          <span className="stat-label">HIGH PRIORITY</span>

          <div className="stat-value">{summary.highPriorityCount}</div>

          <p>Recommendations marked high priority</p>
        </section>

        <section className="stat-card" aria-label="Easy actions">
          <span className="stat-label">EASY ACTIONS</span>

          <div className="stat-value">{summary.easyActions}</div>

          <p>Opportunities marked low effort</p>
        </section>
      </div>

      {/* STRATEGY CONTEXT PANEL */}
      <section
        className="insight-panel"
        aria-labelledby="recommendations-context-title"
      >
        <div className="insight-icon" aria-hidden="true">
          <TrendingDown size={22} />
        </div>

        <div>
          <span className="eyebrow">ENERGY PILOT CONTEXT</span>

          <h2 id="recommendations-context-title">
            Review opportunities using both savings and implementation effort.
          </h2>

          <p>
            Recommendations are ordered by the priority supplied by the
            recommendation engine, followed by estimated monthly savings. Review
            the supporting reason, estimated cost, confidence, and
            implementation requirements before taking action.
          </p>
        </div>
      </section>

      {/* RECOMMENDATIONS LIST */}
      <section
        className="recommendations-list"
        aria-labelledby="recommendations-list-title"
      >
        <h2 id="recommendations-list-title" className="sr-only">
          Energy-saving recommendations
        </h2>

        {sortedRecommendations.map((recommendation, index) => (
          <RecommendationItem
            key={`${recommendation.id}-${index}`}
            recommendation={recommendation}
            index={index}
          />
        ))}
      </section>
    </div>
  );
}