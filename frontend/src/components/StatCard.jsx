import {
  ArrowDownRight,
  ArrowUpRight,
  Minus,
} from "lucide-react";
import { useId, useMemo } from "react";

// =============================================================================
// Constants & Validation
// =============================================================================

const DEFAULT_VARIANT = "default";

const VALID_VARIANTS = new Set([
  "default",
  "primary",
  "success",
  "warning",
  "danger",
  "info",
]);

const TREND_DIRECTIONS = {
  UP: "up",
  DOWN: "down",
  NEUTRAL: "neutral",
};

// =============================================================================
// Helpers
// =============================================================================

function normalizeVariant(variant) {
  if (typeof variant !== "string") {
    return DEFAULT_VARIANT;
  }
  const normalized = variant.trim().toLowerCase();
  return VALID_VARIANTS.has(normalized) ? normalized : DEFAULT_VARIANT;
}

function normalizeTrendDirection(direction) {
  if (typeof direction !== "string") {
    return TREND_DIRECTIONS.NEUTRAL;
  }
  const normalized = direction.trim().toLowerCase();

  if (["up", "increase", "increased", "positive"].includes(normalized)) {
    return TREND_DIRECTIONS.UP;
  }
  if (["down", "decrease", "decreased", "negative"].includes(normalized)) {
    return TREND_DIRECTIONS.DOWN;
  }
  return TREND_DIRECTIONS.NEUTRAL;
}

function inferTrendDirection(value) {
  if (value === null || value === undefined || value === "") {
    return TREND_DIRECTIONS.NEUTRAL;
  }

  const text = String(value).trim().toLowerCase();

  if (text.includes("↓") || text.includes("down") || text.includes("decrease") || text.startsWith("-")) {
    return TREND_DIRECTIONS.DOWN;
  }
  if (text.includes("↑") || text.includes("up") || text.includes("increase") || text.startsWith("+")) {
    return TREND_DIRECTIONS.UP;
  }
  return TREND_DIRECTIONS.NEUTRAL;
}

function normalizeTrend(trend, direction, label) {
  const hasTrend = trend !== null && trend !== undefined && trend !== "";
  const hasDirection = typeof direction === "string" && direction.trim() !== "";
  const hasLabel = typeof label === "string" && label.trim() !== "";

  if (!hasTrend && !hasDirection && !hasLabel) {
    return null;
  }

  let value = "";
  let displayLabel = "";
  let inferredDirection = TREND_DIRECTIONS.NEUTRAL;

  if (typeof trend === "object" && trend !== null && !Array.isArray(trend)) {
    value = trend.value ?? "";
    displayLabel = trend.label ?? trend.value ?? "";
    inferredDirection = normalizeTrendDirection(
      trend.direction ?? inferTrendDirection(value)
    );
  } else if (hasTrend) {
    value = trend;
    displayLabel = trend;
    inferredDirection = inferTrendDirection(trend);
  }

  if (hasDirection) {
    inferredDirection = normalizeTrendDirection(direction);
  }

  if (hasLabel) {
    displayLabel = label.trim();
  }

  return {
    value,
    label: displayLabel,
    direction: inferredDirection,
  };
}

function hasValue(value) {
  return value !== null && value !== undefined && value !== "";
}

function renderIcon(icon, size = 20) {
  if (!icon) return null;

  if (typeof icon === "function") {
    const IconComponent = icon;
    return (
      <IconComponent
        size={size}
        strokeWidth={1.8}
        aria-hidden="true"
        focusable="false"
      />
    );
  }

  return icon;
}

function getTrendIcon(direction) {
  switch (direction) {
    case TREND_DIRECTIONS.UP:
      return ArrowUpRight;
    case TREND_DIRECTIONS.DOWN:
      return ArrowDownRight;
    default:
      return Minus;
  }
}

function getAccessibleValue(value, unit) {
  if (!hasValue(value)) {
    return "No data available";
  }
  return [String(value), unit].filter(Boolean).join(" ");
}

// =============================================================================
// Sub-components
// =============================================================================

function TrendBadge({ trend, description, id }) {
  const Icon = getTrendIcon(trend.direction);
  const defaultDesc = `Trend: ${trend.label}`;

  return (
    <span
      id={id}
      className={`stat-trend stat-trend-${trend.direction}`}
      title={description || "Change compared with the previous period"}
      aria-label={description || defaultDesc}
    >
      <Icon
        size={14}
        strokeWidth={2.2}
        aria-hidden="true"
        focusable="false"
      />
      <span className="stat-trend-label">{trend.label}</span>
    </span>
  );
}

function StatCardLoading({ title, icon, eyebrow, variant, className, compact }) {
  const loadingLabel = title ? `Loading ${title}` : "Loading statistic";

  const cardClasses = useMemo(() => [
    "stat-card",
    `stat-card-${variant}`,
    "stat-card-loading",
    compact ? "stat-card-compact" : "",
    className,
  ].filter(Boolean).join(" "), [variant, compact, className]);

  return (
    <article className={cardClasses} aria-busy="true" aria-label={loadingLabel}>
      <div className="stat-header">
        <div className="stat-heading">
          {eyebrow && <span className="stat-eyebrow">{eyebrow}</span>}
          <span className="stat-title">{title}</span>
        </div>
        {icon && <div className="stat-icon" aria-hidden="true">{renderIcon(icon)}</div>}
      </div>

      <div className="stat-loading-value" aria-hidden="true" />
      <div className="stat-loading-footer" aria-hidden="true" />
      <span className="sr-only">Loading statistic data</span>
    </article>
  );
}

// =============================================================================
// Main Component
// =============================================================================

/**
 * @typedef {Object} TrendObject
 * @property {string|number} [value]
 * @property {string} [label]
 * @property {'up'|'down'|'neutral'} [direction]
 */

/**
 * StatCard Component for displaying metric cards with optional trends and indicators.
 * 
 * @param {Object} props
 * @param {string} [props.title="Statistic"]
 * @param {string|number|null} [props.value=null]
 * @param {string} [props.unit=""]
 * @param {string} [props.subtitle=""]
 * @param {React.ComponentType|React.ReactNode} [props.icon=null]
 * @param {TrendObject|string|number} [props.trend=null]
 * @param {string} [props.trendLabel=""]
 * @param {string} [props.trendDirection=""]
 * @param {string} [props.trendDescription=""]
 * @param {string} [props.eyebrow=""]
 * @string {'default'|'primary'|'success'|'warning'|'danger'|'info'} [props.variant="default"]
 * @param {boolean} [props.loading=false]
 * @param {string} [props.className=""]
 * @param {React.ReactNode} [props.footer=null]
 * @param {boolean} [props.compact=false]
 */
export default function StatCard({
  title = "Statistic",
  value = null,
  unit = "",
  subtitle = "",
  icon = null,
  trend = null,
  trendLabel = "",
  trendDirection = "",
  trendDescription = "",
  eyebrow = "",
  variant = DEFAULT_VARIANT,
  loading = false,
  className = "",
  footer = null,
  compact = false,
}) {
  const titleId = useId();
  const trendId = useId();

  const normalizedVariant = normalizeVariant(variant);
  
  const normalizedTrend = useMemo(
    () => normalizeTrend(trend, trendDirection, trendLabel),
    [trend, trendDirection, trendLabel]
  );

  const valueExists = hasValue(value);
  const accessibleValue = getAccessibleValue(value, unit);

  const cardClassName = useMemo(() => [
    "stat-card",
    `stat-card-${normalizedVariant}`,
    compact ? "stat-card-compact" : "",
    className.trim(),
  ].filter(Boolean).join(" "), [normalizedVariant, compact, className]);

  if (loading) {
    return (
      <StatCardLoading
        title={title}
        icon={icon}
        eyebrow={eyebrow}
        variant={normalizedVariant}
        className={className.trim()}
        compact={compact}
      />
    );
  }

  return (
    <article className={cardClassName} aria-labelledby={titleId}>
      {/* Header */}
      <div className="stat-header">
        <div className="stat-heading">
          {eyebrow && <span className="stat-eyebrow">{eyebrow}</span>}
          <h3 id={titleId} className="stat-title">{title}</h3>
        </div>

        {icon && (
          <div className="stat-icon" aria-hidden="true">
            {renderIcon(icon)}
          </div>
        )}
      </div>

      {/* Main metric */}
      <div
        className="stat-value"
        role="group"
        aria-label={`${title}: ${accessibleValue}`}
      >
        <span className="stat-number">
          {valueExists ? value : "—"}
        </span>

        {unit && (
          <span className="stat-unit" aria-hidden="true">
            {unit}
          </span>
        )}
      </div>

      {/* Footer */}
      {(normalizedTrend || subtitle || footer) && (
        <div className="stat-footer">
          <div className="stat-footer-main">
            {normalizedTrend && (
              <TrendBadge
                id={trendId}
                trend={normalizedTrend}
                description={trendDescription}
              />
            )}

            {subtitle && (
              <span className="stat-subtitle">{subtitle}</span>
            )}
          </div>

          {footer && (
            <div className="stat-extra-footer">{footer}</div>
          )}
        </div>
      )}
    </article>
  );
}