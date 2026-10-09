/**
 * ================================================================
 * EnergyPilot — Shared Formatters
 * ================================================================
 *
 * Centralized, pure, deterministic formatting utilities for UI presentation.
 */

/* --------------------------------------------------------------------------
 * Constants
 * -------------------------------------------------------------------------- */

const DEFAULT_LOCALE = "en-CA";
const DEFAULT_CURRENCY = "CAD";
const EMPTY_VALUE = "—";

const DEFAULT_NUMBER_DECIMALS = 2;

const DATE_TIME_OPTIONS = Object.freeze({
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const DATE_OPTIONS = Object.freeze({
  year: "numeric",
  month: "short",
  day: "numeric",
});

const SHORT_DATE_OPTIONS = Object.freeze({
  month: "short",
  day: "numeric",
});

const TIME_OPTIONS = Object.freeze({
  hour: "numeric",
  minute: "2-digit",
});

const WEEKDAY_DATE_OPTIONS = Object.freeze({
  weekday: "short",
  month: "short",
  day: "numeric",
});

const CHART_TIMESTAMP_OPTIONS = Object.freeze({
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const COMPACT_NUMBER_OPTIONS = Object.freeze({
  notation: "compact",
  maximumFractionDigits: 1,
});

const WHOLE_NUMBER_OPTIONS = Object.freeze({
  maximumFractionDigits: 0,
});


/* --------------------------------------------------------------------------
 * Cached Intl Formatters
 * -------------------------------------------------------------------------- */

const numberFormatterCache = new Map();
const dateFormatterCache = new Map();

function buildCacheKey(locale, options) {
  if (!options) return locale;
  const sortedKeys = Object.keys(options).sort();
  const serializedOptions = sortedKeys.map((k) => `${k}:${options[k]}`).join("|");
  return `${locale}::${serializedOptions}`;
}

function getNumberFormatter(locale = DEFAULT_LOCALE, options = {}) {
  const key = buildCacheKey(locale, options);
  if (!numberFormatterCache.has(key)) {
    numberFormatterCache.set(key, new Intl.NumberFormat(locale, options));
  }
  return numberFormatterCache.get(key);
}

function getDateFormatter(locale = DEFAULT_LOCALE, options = {}) {
  const key = buildCacheKey(locale, options);
  if (!dateFormatterCache.has(key)) {
    dateFormatterCache.set(key, new Intl.DateTimeFormat(locale, options));
  }
  return dateFormatterCache.get(key);
}


/* --------------------------------------------------------------------------
 * Internal Helpers
 * -------------------------------------------------------------------------- */

export function toFiniteNumber(value) {
  if (value === null || value === undefined || typeof value === "boolean") {
    return null;
  }

  if (typeof value === "string" && value.trim() === "") {
    return null;
  }

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

export function firstDefined(...values) {
  return values.find(
    (value) =>
      value !== undefined &&
      value !== null &&
      (typeof value !== "string" || value.trim() !== "")
  );
}

export function parseDate(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  const date = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function normalizeDecimals(decimals, defaultValue = DEFAULT_NUMBER_DECIMALS) {
  if (decimals === undefined || decimals === null || decimals === "") {
    return defaultValue;
  }

  const number = Number(decimals);
  if (!Number.isInteger(number) || number < 0 || number > 20) {
    throw new RangeError("Decimal places must be an integer between 0 and 20.");
  }

  return number;
}

function formatNumberInternal(value, options = {}, locale = DEFAULT_LOCALE) {
  const number = toFiniteNumber(value);
  if (number === null) {
    return EMPTY_VALUE;
  }
  return getNumberFormatter(locale, options).format(number);
}

function formatDateInternal(value, options, locale = DEFAULT_LOCALE) {
  const date = parseDate(value);
  if (!date) {
    return EMPTY_VALUE;
  }
  return getDateFormatter(locale, options).format(date);
}


/* --------------------------------------------------------------------------
 * Number Formatting
 * -------------------------------------------------------------------------- */

export function formatNumber(value, maximumFractionDigits = DEFAULT_NUMBER_DECIMALS) {
  const decimals = normalizeDecimals(maximumFractionDigits);
  return formatNumberInternal(value, {
    maximumFractionDigits: decimals,
  });
}

export function formatWholeNumber(value) {
  return formatNumberInternal(value, WHOLE_NUMBER_OPTIONS);
}

export function formatCompactNumber(value) {
  return formatNumberInternal(value, COMPACT_NUMBER_OPTIONS);
}


/* --------------------------------------------------------------------------
 * Currency Formatting
 * -------------------------------------------------------------------------- */

export function formatCurrency(value, decimals = 2) {
  const normalizedDecimals = normalizeDecimals(decimals);
  const number = toFiniteNumber(value);

  if (number === null) {
    return EMPTY_VALUE;
  }

  return formatNumberInternal(number, {
    style: "currency",
    currency: DEFAULT_CURRENCY,
    minimumFractionDigits: normalizedDecimals,
    maximumFractionDigits: normalizedDecimals,
  });
}

export function formatWholeCurrency(value) {
  return formatCurrency(value, 0);
}

export function formatSignedCurrency(value, decimals = 2) {
  const number = toFiniteNumber(value);

  if (number === null) {
    return EMPTY_VALUE;
  }

  if (number === 0) {
    return formatCurrency(0, decimals);
  }

  const normalizedDecimals = normalizeDecimals(decimals);
  const formattedAbs = formatCurrency(Math.abs(number), normalizedDecimals);

  return number > 0 ? `+${formattedAbs}` : `-${formattedAbs}`;
}


/* --------------------------------------------------------------------------
 * Energy & Electrical Formatting
 * -------------------------------------------------------------------------- */

export function formatEnergy(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} kWh`;
}

export function formatEnergyParts(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null) {
    return { value: EMPTY_VALUE, unit: "" };
  }
  return {
    value: formatNumber(number, decimals),
    unit: "kWh",
  };
}

export function formatPower(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} kW`;
}

export function formatApparentPower(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} kVA`;
}

export function formatEnergyRate(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} ¢/kWh`;
}

export function formatPricePerKwh(value, decimals = 3) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatCurrency(number, decimals)}/kWh`;
}


/* --------------------------------------------------------------------------
 * Percentage Formatting
 * -------------------------------------------------------------------------- */

export function formatPercentage(value, decimals = 1) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)}%`;
}

export function formatRatioAsPercentage(value, decimals = 0) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number * 100, decimals)}%`;
}

export function normalizeConfidence(value) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return null;

  const percentage = number <= 1 ? number * 100 : number;
  return Math.round(Math.min(100, percentage));
}

export function formatConfidence(value) {
  const normalized = normalizeConfidence(value);
  if (normalized === null) return EMPTY_VALUE;
  return `${normalized}%`;
}


/* --------------------------------------------------------------------------
 * Date & Time Formatting
 * -------------------------------------------------------------------------- */

export function formatDateTime(value, options = DATE_TIME_OPTIONS) {
  return formatDateInternal(value, options);
}

export function formatDate(value) {
  return formatDateInternal(value, DATE_OPTIONS);
}

export function formatShortDate(value) {
  return formatDateInternal(value, SHORT_DATE_OPTIONS);
}

export function formatWeekdayDate(value) {
  return formatDateInternal(value, WEEKDAY_DATE_OPTIONS);
}

export function formatTime(value) {
  return formatDateInternal(value, TIME_OPTIONS);
}

export function formatChartTimestamp(value) {
  return formatDateInternal(value, CHART_TIMESTAMP_OPTIONS);
}


/* --------------------------------------------------------------------------
 * Duration & Payback
 * -------------------------------------------------------------------------- */

export function formatMonths(value) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return EMPTY_VALUE;
  if (number === 0) return "Immediate";

  const decimals = Number.isInteger(number) ? 0 : 1;
  return `${formatNumber(number, decimals)} ${number === 1 ? "month" : "months"}`;
}

export function formatPayback(value) {
  return formatMonths(value);
}

export function formatHours(value) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return EMPTY_VALUE;

  const decimals = Number.isInteger(number) ? 0 : 1;
  return `${formatNumber(number, decimals)} ${number === 1 ? "hour" : "hours"}`;
}


/* --------------------------------------------------------------------------
 * Weather & Temperature
 * -------------------------------------------------------------------------- */

export function formatTemperature(value, decimals = 1) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)}°C`;
}

export function formatFahrenheit(value, decimals = 1) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)}°F`;
}

export function celsiusToFahrenheit(value) {
  const number = toFiniteNumber(value);
  if (number === null) return null;
  return (number * 9) / 5 + 32;
}

export function formatHumidity(value, decimals = 0) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return EMPTY_VALUE;
  return `${formatNumber(Math.min(100, number), decimals)}%`;
}

export function formatWindSpeed(value, decimals = 0) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} km/h`;
}


/* --------------------------------------------------------------------------
 * Electrical Measurements
 * -------------------------------------------------------------------------- */

export function formatVoltage(value, decimals = 1) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} V`;
}

export function formatCurrent(value, decimals = 1) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} A`;
}

export function formatFrequency(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;
  return `${formatNumber(number, decimals)} Hz`;
}

export function formatPowerFactor(value, decimals = 2) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return EMPTY_VALUE;
  return formatNumber(Math.min(1, number), decimals);
}


/* --------------------------------------------------------------------------
 * Text & Label Formatting
 * -------------------------------------------------------------------------- */

export function formatLabel(value, fallback = EMPTY_VALUE) {
  const text = String(value ?? "").trim();
  if (!text) return fallback;

  return text
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

export function formatSentence(value, fallback = EMPTY_VALUE) {
  const text = String(value ?? "").trim().replace(/\s+/g, " ");
  if (!text) return fallback;

  return text.charAt(0).toUpperCase() + text.slice(1).toLowerCase();
}

export function formatList(values, separator = ", ") {
  if (!Array.isArray(values)) return EMPTY_VALUE;

  const cleaned = values.map((val) => String(val ?? "").trim()).filter(Boolean);
  return cleaned.length > 0 ? cleaned.join(separator) : EMPTY_VALUE;
}


/* --------------------------------------------------------------------------
 * Quality, Status, & Trends
 * -------------------------------------------------------------------------- */

export function formatCount(value, singular, plural) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;

  const pluralLabel = plural ?? `${singular}s`;
  return `${formatWholeNumber(number)} ${number === 1 ? singular : pluralLabel}`;
}

export function formatDataQuality(value) {
  const number = toFiniteNumber(value);
  if (number === null || number < 0) return EMPTY_VALUE;
  return `${formatNumber(Math.min(100, number), 1)}%`;
}

export function formatStatus(value, fallback = "Unknown") {
  return formatLabel(value, fallback);
}

export function formatTrend(value, decimals = 1) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;

  const formatted = formatNumber(Math.abs(number), decimals);
  if (number > 0) return `+${formatted}%`;
  if (number < 0) return `-${formatted}%`;
  return "0%";
}

export function normalizeTrendDirection(direction) {
  const value = String(direction ?? "").trim().toLowerCase();

  if (["up", "increase", "increased", "higher", "positive"].includes(value)) {
    return "up";
  }
  if (["down", "decrease", "decreased", "lower", "negative"].includes(value)) {
    return "down";
  }
  return "neutral";
}

export function formatWithUnit(value, unit, decimals = DEFAULT_NUMBER_DECIMALS) {
  const number = toFiniteNumber(value);
  if (number === null) return EMPTY_VALUE;

  const cleanUnit = String(unit ?? "").trim();
  const formatted = formatNumber(number, decimals);
  return cleanUnit ? `${formatted} ${cleanUnit}` : formatted;
}


/* --------------------------------------------------------------------------
 * Default Export
 * -------------------------------------------------------------------------- */

export default {
  toFiniteNumber,
  firstDefined,
  parseDate,
  formatNumber,
  formatWholeNumber,
  formatCompactNumber,
  formatCurrency,
  formatWholeCurrency,
  formatSignedCurrency,
  formatEnergy,
  formatEnergyParts,
  formatPower,
  formatApparentPower,
  formatEnergyRate,
  formatPricePerKwh,
  formatPercentage,
  formatRatioAsPercentage,
  formatConfidence,
  normalizeConfidence,
  formatDateTime,
  formatDate,
  formatShortDate,
  formatWeekdayDate,
  formatTime,
  formatChartTimestamp,
  formatMonths,
  formatPayback,
  formatHours,
  formatTemperature,
  formatFahrenheit,
  celsiusToFahrenheit,
  formatHumidity,
  formatWindSpeed,
  formatVoltage,
  formatCurrent,
  formatFrequency,
  formatPowerFactor,
  formatLabel,
  formatSentence,
  formatList,
  formatCount,
  formatDataQuality,
  formatStatus,
  formatTrend,
  normalizeTrendDirection,
  formatWithUnit,
};