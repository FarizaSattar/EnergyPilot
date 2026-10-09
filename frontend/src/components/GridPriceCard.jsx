import { useId, useMemo } from "react";
import {
  Clock3,
  CircleDollarSign,
  Zap,
  AlertCircle,
  TrendingUp,
  TrendingDown,
} from "lucide-react";
import PropTypes from "prop-types";
import "./GridPriceCard.css";

/* ============================================================================
   Constants & Static Configuration
   ========================================================================== */

const DEFAULT_PRICE_UNIT = "¢/kWh";
const DEFAULT_PERIOD = "Electricity Rate";

const PRICING_PERIODS = Object.freeze({
  ON_PEAK: "On-Peak",
  MID_PEAK: "Mid-Peak",
  OFF_PEAK: "Off-Peak",
  ULTRA_LOW_OVERNIGHT: "Ultra-Low Overnight",
  TIERED: "Tiered",
});

const PRICE_FIELDS = Object.freeze([
  "price_cents",
  "rate_cents",
  "cents_per_kwh",
  "price",
  "rate",
  "current_price",
  "cost",
]);

const PERIOD_FIELDS = Object.freeze([
  "period",
  "tier",
  "rate_period",
  "price_period",
  "label",
  "category",
]);

const TIMESTAMP_FIELDS = Object.freeze([
  "timestamp",
  "ts",
  "datetime",
  "date",
  "updated_at",
]);

/* ============================================================================
   Static Formatters (Hoisted for performance)
   ========================================================================== */

const PRICE_FORMATTER = new Intl.NumberFormat("en-CA", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const TIME_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  hour: "numeric",
  minute: "2-digit",
});

/* ============================================================================
   Generic Helpers
   ========================================================================== */

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
      String(value).trim() !== ""
  );
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

/* ============================================================================
   Price & Unit Normalization
   ========================================================================== */

function getPriceValue(pricing) {
  if (!pricing || typeof pricing !== "object") {
    return null;
  }

  for (const field of PRICE_FIELDS) {
    const value = toFiniteNumber(pricing[field]);
    if (value !== null) {
      return value;
    }
  }

  return null;
}

function isPriceInCents(pricing, explicitPriceInCents) {
  if (typeof explicitPriceInCents === "boolean") {
    return explicitPriceInCents;
  }

  const unit = String(
    firstDefined(
      pricing?.unit,
      pricing?.price_unit,
      pricing?.rate_unit
    ) ?? ""
  )
    .trim()
    .toLowerCase();

  if (
    unit.includes("cent") ||
    unit.includes("¢") ||
    unit.includes("c/kwh") ||
    unit.includes("cents/kwh")
  ) {
    return true;
  }

  if (
    unit.includes("dollar") ||
    unit.includes("$") ||
    unit.includes("$/kwh") ||
    unit.includes("dollars/kwh")
  ) {
    return false;
  }

  const explicitCentsField = [
    "price_cents",
    "rate_cents",
    "cents_per_kwh",
  ].some(
    (field) =>
      pricing &&
      pricing[field] !== undefined &&
      pricing[field] !== null
  );

  if (explicitCentsField) {
    return true;
  }

  // Heuristic: If raw rate is less than 1.0 (e.g., 0.128 $/kWh), treat as Dollars and convert to Cents
  const rawValue = getPriceValue(pricing);
  if (rawValue !== null && rawValue > 0 && rawValue < 1.0) {
    return false;
  }

  return true;
}

function normalizePrice(pricing, explicitPriceInCents) {
  const rawPrice = getPriceValue(pricing);

  if (rawPrice === null || rawPrice < 0) {
    return null;
  }

  return isPriceInCents(pricing, explicitPriceInCents)
    ? rawPrice
    : rawPrice * 100;
}

function formatPrice(value) {
  const number = toFiniteNumber(value);
  return number === null ? "—" : PRICE_FORMATTER.format(number);
}

/* ============================================================================
   Pricing Period & Tier Mapping
   ========================================================================== */

function getPricingPeriod(pricing) {
  if (!pricing || typeof pricing !== "object") {
    return DEFAULT_PERIOD;
  }

  const value = firstDefined(
    ...PERIOD_FIELDS.map((field) => pricing[field])
  );

  return formatLabel(value, DEFAULT_PERIOD);
}

function getPeriodClassName(period) {
  return String(period)
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

function getKnownPeriodKey(period) {
  const key = normalizeKey(period);

  const mapping = {
    on_peak: PRICING_PERIODS.ON_PEAK,
    mid_peak: PRICING_PERIODS.MID_PEAK,
    off_peak: PRICING_PERIODS.OFF_PEAK,
    ultra_low_overnight: PRICING_PERIODS.ULTRA_LOW_OVERNIGHT,
    ulo: PRICING_PERIODS.ULTRA_LOW_OVERNIGHT,
    tiered: PRICING_PERIODS.TIERED,
  };

  return mapping[key] ?? null;
}

/* ============================================================================
   Timestamp Parsing
   ========================================================================== */

function getPricingTimestamp(pricing) {
  if (!pricing || typeof pricing !== "object") {
    return null;
  }

  return firstDefined(
    ...TIMESTAMP_FIELDS.map((field) => pricing[field])
  );
}

function parseTimestamp(timestamp) {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatUpdatedTime(timestamp) {
  const date = parseTimestamp(timestamp);
  if (!date) return null;

  return TIME_FORMATTER.format(date);
}

/* ============================================================================
   Empty State Component
   ========================================================================== */

function GridPriceEmptyState() {
  const titleId = useId();

  return (
    <section
      className="grid-price-card grid-price-card--empty"
      aria-labelledby={titleId}
      role="status"
    >
      <div className="grid-price-empty-icon" aria-hidden="true">
        <AlertCircle size={20} strokeWidth={2} />
      </div>

      <div className="grid-price-empty-content">
        <span className="grid-price-empty-eyebrow">Electricity pricing</span>

        <h3 id={titleId}>Grid price unavailable</h3>

        <p>Current electricity pricing data is temporarily unavailable.</p>
      </div>
    </section>
  );
}

/* ============================================================================
   Main Component
   ========================================================================== */

export default function GridPriceCard({ pricing = null, priceInCents }) {
  const titleId = useId();

  const normalized = useMemo(() => {
    const price = normalizePrice(pricing, priceInCents);
    const period = getPricingPeriod(pricing);
    const timestamp = getPricingTimestamp(pricing);
    const parsedTimestamp = parseTimestamp(timestamp);

    return {
      price,
      period,
      knownPeriod: getKnownPeriodKey(period),
      timestamp,
      updatedTime: formatUpdatedTime(timestamp),
      periodClassName: getPeriodClassName(period),
      hasTimestamp: Boolean(parsedTimestamp),
      isoTimestamp: parsedTimestamp ? parsedTimestamp.toISOString() : null,
    };
  }, [pricing, priceInCents]);

  if (normalized.price === null) {
    return <GridPriceEmptyState />;
  }

  return (
    <section
      className={`grid-price-card grid-price-card--${normalized.periodClassName}`}
      aria-labelledby={titleId}
    >
      {/* Header */}
      <header className="grid-price-card-header">
        <div className="grid-price-card-heading">
          <div className="grid-price-card-eyebrow">
            <span
              className="grid-price-card-eyebrow-dot"
              aria-hidden="true"
            />
            Live electricity pricing
          </div>

          <h2 id={titleId} className="grid-price-card-title">
            Current Grid Rate
          </h2>
        </div>

        <div className="grid-price-card-icon" aria-hidden="true">
          <Zap size={19} strokeWidth={2} />
        </div>
      </header>

      {/* Main price */}
      <div className="grid-price-card-main">
        <div
          className="grid-price-card-price"
          aria-label={`Current electricity price is ${formatPrice(
            normalized.price
          )} cents per kilowatt hour`}
        >
          <strong>{formatPrice(normalized.price)}</strong>
          <span>{DEFAULT_PRICE_UNIT}</span>
        </div>

        <div className="grid-price-card-live">
          <span
            className="grid-price-card-live-dot"
            aria-hidden="true"
          />
          Current
        </div>
      </div>

      {/* Pricing period */}
      <div className="grid-price-card-period">
        <div className="grid-price-card-period-heading">
          <span className="grid-price-card-period-label">
            Pricing period
          </span>

          <span className="grid-price-card-period-description">
            Current utility rate classification
          </span>
        </div>

        <span
          className="grid-price-card-period-badge"
          aria-label={`Pricing period: ${normalized.period}`}
        >
          {normalized.period}
        </span>
      </div>

      {/* Footer */}
      <footer className="grid-price-card-footer">
        <div className="grid-price-card-footer-item">
          <CircleDollarSign
            size={13}
            strokeWidth={1.9}
            aria-hidden="true"
          />

          <span>Rate per kilowatt-hour</span>
        </div>

        <div className="grid-price-card-footer-item grid-price-card-updated">
          <Clock3 size={13} strokeWidth={1.9} aria-hidden="true" />

          {normalized.updatedTime ? (
            <time dateTime={normalized.isoTimestamp || undefined}>
              Updated {normalized.updatedTime}
            </time>
          ) : (
            <span>Live pricing</span>
          )}
        </div>
      </footer>
    </section>
  );
}

GridPriceCard.propTypes = {
  pricing: PropTypes.shape({
    price: PropTypes.number,
    price_cents: PropTypes.number,
    rate: PropTypes.number,
    rate_cents: PropTypes.number,
    cents_per_kwh: PropTypes.number,
    current_price: PropTypes.number,
    unit: PropTypes.string,
    price_unit: PropTypes.string,
    rate_unit: PropTypes.string,
    period: PropTypes.string,
    tier: PropTypes.string,
    rate_period: PropTypes.string,
    price_period: PropTypes.string,
    label: PropTypes.string,
    timestamp: PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.instanceOf(Date)]),
    ts: PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.instanceOf(Date)]),
    datetime: PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.instanceOf(Date)]),
    date: PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.instanceOf(Date)]),
  }),
  priceInCents: PropTypes.bool,
};