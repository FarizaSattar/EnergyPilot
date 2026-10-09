import { useId, useMemo } from "react";
import PropTypes from "prop-types";
import {
  Clock3,
  DollarSign,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import "./PricingCard.css";

/* ============================================================================
   EnergyPilot — PricingCard Configuration
   ========================================================================== */

const DEFAULT_RATE_UNIT = "¢/kWh";
const DEFAULT_PERIOD = "Current";

const PRICING_PERIODS = Object.freeze({
  OFF_PEAK: "Off-Peak",
  MID_PEAK: "Mid-Peak",
  ON_PEAK: "On-Peak",
  ULTRA_LOW_OVERNIGHT: "Ultra-Low Overnight",
});

const RATE_FIELDS = Object.freeze([
  "rate_cents",
  "price_cents",
  "cents_per_kwh",
  "rate",
  "price",
  "current_rate",
  "currentRate",
  "electricity_rate",
  "electricityRate",
]);

const PERIOD_FIELDS = Object.freeze([
  "period",
  "pricing_period",
  "pricingPeriod",
  "tou_period",
  "touPeriod",
  "tier",
]);

const TIMESTAMP_FIELDS = Object.freeze([
  "timestamp",
  "updated_at",
  "updatedAt",
  "time",
  "datetime",
]);

const UNIT_FIELDS = Object.freeze([
  "unit",
  "rate_unit",
  "rateUnit",
  "price_unit",
  "priceUnit",
]);

const LOWER_RATE_THRESHOLD = 10;
const HIGHER_RATE_THRESHOLD = 20;

/* ============================================================================
   Static Formatters (Hoisted for performance)
   ========================================================================== */

const RATE_FORMATTER = new Intl.NumberFormat("en-CA", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const TIME_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  hour: "numeric",
  minute: "2-digit",
});

/* ============================================================================
   DATA HELPERS
   ========================================================================== */

function getFirstDefinedValue(object, fields) {
  if (!object || typeof object !== "object") {
    return null;
  }

  for (const field of fields) {
    const value = object[field];
    if (
      value !== undefined &&
      value !== null &&
      String(value).trim() !== ""
    ) {
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

  const number = typeof value === "number" ? value : Number(value);
  return Number.isFinite(number) ? number : null;
}

function parseRate(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }

  if (typeof value !== "string") {
    return null;
  }

  const text = value.trim();
  if (!text) {
    return null;
  }

  const numericValue = Number.parseFloat(text.replace(/[^0-9.-]/g, ""));
  return Number.isFinite(numericValue) ? numericValue : null;
}

function normalizeUnit(unit) {
  return String(unit ?? "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, "");
}

function isCentsPerKwh(unit) {
  const normalized = normalizeUnit(unit);
  if (!normalized) return null;

  return (
    normalized.includes("¢/kwh") ||
    normalized.includes("cents/kwh") ||
    normalized.includes("cent/kwh") ||
    normalized.includes("¢perkwh") ||
    normalized.includes("centsperkwh") ||
    normalized.includes("centperkwh") ||
    normalized === "c/kwh"
  );
}

function isDollarsPerKwh(unit) {
  const normalized = normalizeUnit(unit);
  if (!normalized) return null;

  return (
    normalized.includes("$/kwh") ||
    normalized.includes("dollars/kwh") ||
    normalized.includes("dollar/kwh") ||
    normalized.includes("$perkwh") ||
    normalized.includes("dollarsperkwh") ||
    normalized.includes("dollarperkwh")
  );
}

function getFieldUnit(field) {
  if (!field) return null;

  const normalizedField = String(field).trim().toLowerCase();
  if (
    normalizedField.includes("cents") ||
    normalizedField.endsWith("_cents")
  ) {
    return "cents";
  }

  return null;
}

function getRateSource(pricing) {
  if (!pricing || typeof pricing !== "object") {
    return null;
  }

  for (const field of RATE_FIELDS) {
    const rawValue = pricing[field];
    if (
      rawValue !== undefined &&
      rawValue !== null &&
      String(rawValue).trim() !== ""
    ) {
      return { field, value: rawValue };
    }
  }

  return null;
}

function normalizeRate(pricing) {
  const source = getRateSource(pricing);
  if (!source) return null;

  const rate = parseRate(source.value);
  if (rate === null || rate < 0) return null;

  const rawUnit = getFirstDefinedValue(pricing, UNIT_FIELDS);
  const fieldUnit = getFieldUnit(source.field);

  if (fieldUnit === "cents") return rate;
  if (isCentsPerKwh(rawUnit) === true) return rate;
  if (isDollarsPerKwh(rawUnit) === true) return rate * 100;

  // Heuristic: values under 1.0 (e.g., 0.128) represent $/kWh
  if (rate > 0 && rate < 1.0) {
    return rate * 100;
  }

  return rate;
}

function formatRate(rate) {
  const value = toFiniteNumber(rate);
  return value === null ? "—" : RATE_FORMATTER.format(value);
}

/* ============================================================================
   PRICING PERIOD
   ========================================================================== */

function normalizePeriod(value) {
  if (value === null || value === undefined || String(value).trim() === "") {
    return DEFAULT_PERIOD;
  }

  const normalized = String(value)
    .trim()
    .toLowerCase()
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ");

  const periodMap = {
    "off peak": PRICING_PERIODS.OFF_PEAK,
    offpeak: PRICING_PERIODS.OFF_PEAK,
    "mid peak": PRICING_PERIODS.MID_PEAK,
    midpeak: PRICING_PERIODS.MID_PEAK,
    "on peak": PRICING_PERIODS.ON_PEAK,
    onpeak: PRICING_PERIODS.ON_PEAK,
    "ultra low overnight": PRICING_PERIODS.ULTRA_LOW_OVERNIGHT,
    ultralowovernight: PRICING_PERIODS.ULTRA_LOW_OVERNIGHT,
    ulo: PRICING_PERIODS.ULTRA_LOW_OVERNIGHT,
  };

  return periodMap[normalized] || String(value).trim();
}

function getPeriodClassName(period) {
  const classMap = {
    [PRICING_PERIODS.OFF_PEAK]: "pricing-card__period--off-peak",
    [PRICING_PERIODS.MID_PEAK]: "pricing-card__period--mid-peak",
    [PRICING_PERIODS.ON_PEAK]: "pricing-card__period--on-peak",
    [PRICING_PERIODS.ULTRA_LOW_OVERNIGHT]: "pricing-card__period--ultra-low",
  };

  return [
    "pricing-card__period",
    classMap[period] || "pricing-card__period--default",
  ].join(" ");
}

/* ============================================================================
   TIMESTAMP
   ========================================================================== */

function parseTimestamp(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatUpdatedTime(value) {
  const date = parseTimestamp(value);
  if (!date) return null;

  return TIME_FORMATTER.format(date);
}

/* ============================================================================
   RATE INDICATOR
   ========================================================================== */

function getRateTrend(rate) {
  if (!Number.isFinite(rate)) return null;

  if (rate <= LOWER_RATE_THRESHOLD) {
    return {
      label: "Lower rate",
      Icon: TrendingDown,
      className: "pricing-card__trend--low",
    };
  }

  if (rate >= HIGHER_RATE_THRESHOLD) {
    return {
      label: "Higher rate",
      Icon: TrendingUp,
      className: "pricing-card__trend--high",
    };
  }

  return null;
}

/* ============================================================================
   EMPTY STATE
   ========================================================================== */

function PricingEmptyState({ titleId }) {
  return (
    <section
      className="pricing-card pricing-card--empty"
      aria-labelledby={titleId}
      role="status"
    >
      <div className="pricing-card__header">
        <div className="pricing-card__heading">
          <p className="pricing-card__eyebrow">
            <span className="pricing-card__eyebrow-dot" />
            Electricity pricing
          </p>

          <h2 id={titleId} className="pricing-card__title">
            Current Grid Price
          </h2>
        </div>

        <div className="pricing-card__icon" aria-hidden="true">
          <DollarSign size={20} strokeWidth={1.9} />
        </div>
      </div>

      <div className="pricing-card__empty-content">
        <span className="pricing-card__empty-symbol" aria-hidden="true">
          <Zap size={19} strokeWidth={1.8} />
        </span>

        <p className="pricing-card__empty-message">
          Pricing data is temporarily unavailable.
        </p>

        <span className="pricing-card__empty-hint">
          The current rate will appear when data is received.
        </span>
      </div>

      <footer className="pricing-card__footer">
        <span>Grid pricing</span>
        <span className="pricing-card__footer-separator" aria-hidden="true" />
        <span>Awaiting data</span>
      </footer>
    </section>
  );
}

PricingEmptyState.propTypes = {
  titleId: PropTypes.string.isRequired,
};

/* ============================================================================
   MAIN COMPONENT
   ========================================================================== */

export default function PricingCard({ pricing = null }) {
  const generatedId = useId();
  const titleId = `pricing-card-title-${generatedId.replace(/:/g, "")}`;
  const descriptionId = `pricing-card-description-${generatedId.replace(/:/g, "")}`;

  const normalizedPricing = useMemo(() => {
    if (!pricing || typeof pricing !== "object") {
      return null;
    }

    const rawPeriod = getFirstDefinedValue(pricing, PERIOD_FIELDS);
    const rawTimestamp = getFirstDefinedValue(pricing, TIMESTAMP_FIELDS);

    const rate = normalizeRate(pricing);
    const period = normalizePeriod(rawPeriod);
    const timestamp = parseTimestamp(rawTimestamp);

    return {
      rate,
      unit: DEFAULT_RATE_UNIT,
      period,
      timestamp,
      updatedTime: formatUpdatedTime(rawTimestamp),
    };
  }, [pricing]);

  if (!normalizedPricing || normalizedPricing.rate === null) {
    return <PricingEmptyState titleId={titleId} />;
  }

  const { rate, unit, period, updatedTime, timestamp } = normalizedPricing;

  const trend = getRateTrend(rate);
  const TrendIcon = trend?.Icon;

  return (
    <section
      className="pricing-card"
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      {/* Decorative top accent */}
      <div className="pricing-card__accent" aria-hidden="true" />

      {/* Header */}
      <header className="pricing-card__header">
        <div className="pricing-card__heading">
          <p className="pricing-card__eyebrow">
            <span className="pricing-card__eyebrow-dot" />
            Electricity pricing
          </p>

          <h2 id={titleId} className="pricing-card__title">
            Current Grid Price
          </h2>
        </div>

        <div className="pricing-card__icon" aria-hidden="true">
          <DollarSign size={20} strokeWidth={1.9} />
        </div>
      </header>

      {/* Rate Display */}
      <div className="pricing-card__rate-section">
        <p className="pricing-card__rate-caption">Electricity rate</p>

        <div className="pricing-card__rate-row">
          <div
            className="pricing-card__rate"
            aria-label={`${formatRate(rate)} cents per kilowatt-hour`}
          >
            <span className="pricing-card__rate-value" aria-hidden="true">
              {formatRate(rate)}
            </span>

            <span className="pricing-card__rate-unit" aria-hidden="true">
              {unit}
            </span>
          </div>

          {trend && TrendIcon ? (
            <span
              className={["pricing-card__trend", trend.className].join(" ")}
              title={trend.label}
              aria-label={trend.label}
            >
              <TrendIcon
                size={15}
                aria-hidden="true"
                focusable="false"
              />
              <span>{trend.label}</span>
            </span>
          ) : null}
        </div>

        <p id={descriptionId} className="pricing-card__description">
          Cost per kilowatt-hour of electricity consumed from the grid.
        </p>
      </div>

      {/* Pricing Details */}
      <div className="pricing-card__details">
        <div className="pricing-card__detail">
          <span className="pricing-card__detail-label">Pricing period</span>

          <span className={getPeriodClassName(period)}>
            <span className="pricing-card__period-dot" aria-hidden="true" />
            {period}
          </span>
        </div>

        {updatedTime && timestamp ? (
          <div className="pricing-card__detail">
            <span className="pricing-card__detail-label">Last updated</span>

            <time
              className="pricing-card__updated"
              dateTime={timestamp.toISOString()}
            >
              <Clock3
                size={14}
                strokeWidth={1.9}
                aria-hidden="true"
                focusable="false"
              />
              <span>{updatedTime}</span>
            </time>
          </div>
        ) : null}
      </div>

      {/* Footer */}
      <footer className="pricing-card__footer">
        <span className="pricing-card__footer-brand">
          <Zap size={13} strokeWidth={2.2} aria-hidden="true" />
          EnergyPilot
        </span>

        <span className="pricing-card__footer-separator" aria-hidden="true" />

        <span>Grid pricing data</span>
      </footer>
    </section>
  );
}

PricingCard.propTypes = {
  pricing: PropTypes.object,
};