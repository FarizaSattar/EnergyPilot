import React, { useMemo } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import "./Analytics.css";

/* ==========================================================================
   Configuration & Constants
   ========================================================================== */

const DEFAULT_DAILY_POINTS = 30;
const DEFAULT_CHART_HEIGHT = 340;

const LOCALE = "en-CA";
const CURRENCY = "CAD";

const DATE_FORMAT_OPTIONS = Object.freeze({
  month: "short",
  day: "numeric",
});

const EMPTY_ARRAY = Object.freeze([]);

/* ==========================================================================
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

function formatNumber(value, decimals = 1) {
  const number = toFiniteNumber(value);

  if (number === null) {
    return "—";
  }

  const safeDecimals = Number.isInteger(decimals)
    ? Math.min(Math.max(decimals, 0), 6)
    : 1;

  return number.toFixed(safeDecimals);
}

function formatCurrency(value) {
  const number = toFiniteNumber(value);

  if (number === null) {
    return "—";
  }

  return new Intl.NumberFormat(LOCALE, {
    style: "currency",
    currency: CURRENCY,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(number);
}

function firstDefined(...values) {
  for (const value of values) {
    if (value !== null && value !== undefined && value !== "") {
      return value;
    }
  }
  return null;
}

/* ==========================================================================
   Date Helpers
   ========================================================================== */

function formatHour(hour) {
  const numericHour = toFiniteNumber(hour);

  if (numericHour === null || numericHour < 0 || numericHour > 23) {
    return "—";
  }

  const roundedHour = Math.round(numericHour);
  const suffix = roundedHour >= 12 ? "PM" : "AM";
  const displayHour = roundedHour % 12 || 12;

  return `${displayHour} ${suffix}`;
}

function parseDate(value) {
  if (!value) return null;

  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  if (typeof value !== "string") return null;

  const trimmed = value.trim();
  if (!trimmed) return null;

  // Treat YYYY-MM-DD as local calendar dates to avoid UTC shifts
  const dateOnlyMatch = /^(\d{4})-(\d{2})-(\d{2})$/.exec(trimmed);

  if (dateOnlyMatch) {
    const [, year, month, day] = dateOnlyMatch;
    const localDate = new Date(
      Number(year),
      Number(month) - 1,
      Number(day)
    );
    return Number.isNaN(localDate.getTime()) ? null : localDate;
  }

  const parsedDate = new Date(trimmed);
  return Number.isNaN(parsedDate.getTime()) ? null : parsedDate;
}

function formatDate(dateValue) {
  const date = parseDate(dateValue);

  if (!date) {
    return dateValue ? String(dateValue) : "";
  }

  return date.toLocaleDateString(LOCALE, DATE_FORMAT_OPTIONS);
}

function getDateKey(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
    return null;
  }

  return [
    date.getFullYear(),
    String(date.getMonth() + 1).padStart(2, "0"),
    String(date.getDate()).padStart(2, "0"),
  ].join("-");
}

/* ==========================================================================
   Analytics Normalization
   ========================================================================== */

function normalizeHourlyProfile(hourlyProfile) {
  if (!Array.isArray(hourlyProfile)) {
    return EMPTY_ARRAY;
  }

  const byHour = new Map();

  for (const item of hourlyProfile) {
    if (!item || typeof item !== "object") continue;

    const hour = toFiniteNumber(
      firstDefined(item.hour, item.hour_of_day, item.hourOfDay)
    );

    const averageKwh = toFiniteNumber(
      firstDefined(
        item.average_kwh,
        item.avg_kwh,
        item.kwh,
        item.usage_kwh,
        item.energy_kwh
      )
    );

    if (
      hour === null ||
      averageKwh === null ||
      hour < 0 ||
      hour > 23 ||
      averageKwh < 0
    ) {
      continue;
    }

    const normalizedHour = Math.round(hour);

    if (!byHour.has(normalizedHour)) {
      byHour.set(normalizedHour, {
        hour: normalizedHour,
        average_kwh: averageKwh,
      });
    }
  }

  return Array.from(byHour.values()).sort((a, b) => a.hour - b.hour);
}

function normalizeDailyUsage(dailyUsage, maxPoints = DEFAULT_DAILY_POINTS) {
  if (!Array.isArray(dailyUsage)) {
    return EMPTY_ARRAY;
  }

  const byDate = new Map();

  for (const item of dailyUsage) {
    if (!item || typeof item !== "object") continue;

    const rawDate = firstDefined(item.date, item.timestamp, item.datetime);
    const parsedDate = parseDate(rawDate);

    const kwh = toFiniteNumber(
      firstDefined(item.kwh, item.energy_kwh, item.usage_kwh, item.usage)
    );

    if (!parsedDate || kwh === null || kwh < 0) continue;

    const dateKey = getDateKey(parsedDate);
    if (!dateKey) continue;

    if (!byDate.has(dateKey)) {
      byDate.set(dateKey, {
        date: rawDate,
        parsedDate,
        kwh,
      });
    }
  }

  const normalized = Array.from(byDate.values()).sort(
    (a, b) => a.parsedDate.getTime() - b.parsedDate.getTime()
  );

  if (Number.isInteger(maxPoints) && maxPoints > 0) {
    return normalized.slice(-maxPoints);
  }

  return normalized;
}

/* ==========================================================================
   Calculations
   ========================================================================== */

function calculateDailyStatistics(dailyUsage, backendTotal, backendAverage) {
  const calculatedTotal = dailyUsage.reduce((sum, day) => sum + day.kwh, 0);

  const total =
    toFiniteNumber(backendTotal) ??
    (dailyUsage.length > 0 ? calculatedTotal : null);

  const average =
    toFiniteNumber(backendAverage) ??
    (dailyUsage.length > 0 ? calculatedTotal / dailyUsage.length : null);

  return { total, average };
}

function calculatePeakHour(hourlyProfile) {
  if (!hourlyProfile.length) return null;

  return hourlyProfile.reduce(
    (peak, current) =>
      current.average_kwh > peak.average_kwh ? current : peak,
    hourlyProfile[0]
  );
}

function calculateDailyPeak(dailyUsage) {
  if (!dailyUsage.length) return null;

  return dailyUsage.reduce(
    (peak, current) => (current.kwh > peak.kwh ? current : peak),
    dailyUsage[0]
  );
}

/* ==========================================================================
   Custom Glass Tooltips
   ========================================================================== */

function HourlyTooltip({ active, payload }) {
  if (!active || !Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div className="analytics-tooltip">
      <span className="analytics-tooltip__eyebrow">Hourly Load Profile</span>
      <div className="analytics-tooltip__title">{formatHour(point.hour)}</div>
      <div className="analytics-tooltip__value">
        {formatNumber(point.average_kwh, 2)}
        <span> kWh</span>
      </div>
      <span className="analytics-tooltip__label">Average demand</span>
    </div>
  );
}

function DailyTooltip({ active, payload }) {
  if (!active || !Array.isArray(payload) || payload.length === 0) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div className="analytics-tooltip">
      <span className="analytics-tooltip__eyebrow">Daily Consumption</span>
      <div className="analytics-tooltip__title">{formatDate(point.date)}</div>
      <div className="analytics-tooltip__value">
        {formatNumber(point.kwh, 2)}
        <span> kWh</span>
      </div>
      <span className="analytics-tooltip__label">Total energy used</span>
    </div>
  );
}

/* ==========================================================================
   Metric Icons
   ========================================================================== */

function MetricIcon({ type }) {
  if (type === "consumption") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true" width="20" height="20">
        <path
          d="M13 2L5.5 13H10.75L10 22L18.5 10H13.25L13 2Z"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }

  if (type === "average") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true" width="20" height="20">
        <path
          d="M4 17.5L9 12L12.5 15.5L20 7"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d="M15.5 7H20V11.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    );
  }

  if (type === "peak") {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true" width="20" height="20">
        <path
          d="M12 3V21M5 12H19"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
        />
        <circle
          cx="12"
          cy="12"
          r="8.5"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        />
      </svg>
    );
  }

  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" width="20" height="20">
      <path
        d="M12 2V22M17 5H9.5C8.5 5 7.5 5.8 7.5 7C7.5 8.2 8.5 9 9.5 9H14.5C15.5 9 16.5 9.8 16.5 11C16.5 12.2 15.5 13 14.5 13H7M17 19H9.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ==========================================================================
   State Displays (Loading, Empty, Error)
   ========================================================================== */

function AnalyticsLoading() {
  return (
    <main
      className="analytics-page"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <header className="analytics-hero analytics-hero--loading">
        <div>
          <span className="analytics-eyebrow">LOAD ANALYTICS</span>
          <h1>
            Understand your <br />
            <span>energy profile.</span>
          </h1>
          <p>Analyzing electricity consumption metrics...</p>
        </div>
      </header>

      <section
        className="analytics-metrics"
        aria-label="Loading analytics summary"
      >
        {Array.from({ length: 4 }, (_, index) => (
          <div
            className="analytics-metric analytics-skeleton-card"
            key={index}
          >
            <div className="analytics-skeleton analytics-skeleton--icon" />
            <div className="analytics-skeleton analytics-skeleton--label" />
            <div className="analytics-skeleton analytics-skeleton--value" />
            <div className="analytics-skeleton analytics-skeleton--text" />
          </div>
        ))}
      </section>

      <section className="analytics-panel analytics-skeleton-panel">
        <div className="analytics-skeleton analytics-skeleton--title" />
        <div className="analytics-skeleton analytics-skeleton--chart" />
      </section>
    </main>
  );
}

function AnalyticsEmpty() {
  return (
    <main className="analytics-page" role="status" aria-live="polite">
      <header className="analytics-hero">
        <div>
          <span className="analytics-eyebrow">LOAD ANALYTICS</span>
          <h1>
            Understand your <br />
            <span>energy profile.</span>
          </h1>
          <p>Explore when and how your facility consumes electricity.</p>
        </div>
      </header>

      <section className="analytics-empty">
        <div className="analytics-empty__icon">
          <MetricIcon type="consumption" />
        </div>
        <span className="analytics-eyebrow">AWAITING TELEMETRY</span>
        <h2>No analytics data available</h2>
        <p>
          Upload smart-meter readings or connect live telemetry feeds to begin
          analyzing demand peaks, daily trends, and consumption costs.
        </p>
      </section>
    </main>
  );
}

function AnalyticsError({ error }) {
  const message =
    typeof error === "string"
      ? error
      : error?.message || "The analytics service could not fulfill the request.";

  return (
    <main className="analytics-page" role="alert">
      <header className="analytics-hero">
        <div>
          <span className="analytics-eyebrow">LOAD ANALYTICS</span>
          <h1>
            Analytics are <br />
            <span>temporarily unavailable.</span>
          </h1>
          <p>{message}</p>
        </div>
      </header>

      <section className="analytics-error">
        <div className="analytics-error__icon">!</div>
        <div>
          <h2>System Communication Error</h2>
          <p>
            Verify that the analytics backend is operational and accessible.
          </p>
        </div>
      </section>
    </main>
  );
}

/* ==========================================================================
   Main Component
   ========================================================================== */

export default function Analytics({
  analytics = null,
  loading = false,
  error = null,
  maxDailyPoints = DEFAULT_DAILY_POINTS,
}) {
  /*
   * Hooks run unconditionally to maintain React hook order.
   */
  const hourlyProfile = useMemo(
    () =>
      normalizeHourlyProfile(
        analytics?.hourly_profile ?? analytics?.hourlyProfile
      ),
    [analytics]
  );

  const dailyUsage = useMemo(
    () =>
      normalizeDailyUsage(
        analytics?.daily_usage ?? analytics?.dailyUsage,
        maxDailyPoints
      ),
    [analytics, maxDailyPoints]
  );

  const dailyStatistics = useMemo(
    () =>
      calculateDailyStatistics(
        dailyUsage,
        analytics?.total_kwh ?? analytics?.totalKwh,
        analytics?.average_daily_kwh ?? analytics?.averageDailyKwh
      ),
    [
      dailyUsage,
      analytics?.total_kwh,
      analytics?.totalKwh,
      analytics?.average_daily_kwh,
      analytics?.averageDailyKwh,
    ]
  );

  const calculatedPeak = useMemo(
    () => calculatePeakHour(hourlyProfile),
    [hourlyProfile]
  );

  const peakHour =
    toFiniteNumber(analytics?.peak_hour ?? analytics?.peakHour) ??
    calculatedPeak?.hour ??
    null;

  const peakHourlyKwh =
    toFiniteNumber(analytics?.peak_hour_kwh ?? analytics?.peakHourKwh) ??
    calculatedPeak?.average_kwh ??
    null;

  const estimatedCost = toFiniteNumber(
    analytics?.estimated_cost ?? analytics?.estimatedCost
  );

  const hasHourlyData = hourlyProfile.length > 0;
  const hasDailyData = dailyUsage.length > 0;

  const hourlyAccessibleSummary = hasHourlyData
    ? `Hourly load profile with peak average demand at ${formatHour(
        peakHour
      )}, measuring ${formatNumber(peakHourlyKwh, 2)} kWh.`
    : "No hourly consumption data available.";

  const dailyAccessibleSummary = hasDailyData
    ? `Daily consumption chart showing ${dailyUsage.length} days of data.`
    : "No daily consumption data available.";

  /* Conditional view rendering */
  if (loading) return <AnalyticsLoading />;
  if (error) return <AnalyticsError error={error} />;
  if (!analytics || typeof analytics !== "object") return <AnalyticsEmpty />;

  return (
    <main className="analytics-page">
      {/* ================================================================
          Hero Header
          ================================================================ */}
      <header className="analytics-hero">
        <div className="analytics-hero__content">
          <div className="analytics-hero__eyebrow">
            <span className="analytics-eyebrow">LOAD ANALYTICS</span>
            <span className="analytics-live-indicator">
              <span aria-hidden="true" />
              SYSTEM ACTIVE
            </span>
          </div>

          <h1>
            Understand your <br />
            <span>energy profile.</span>
          </h1>

          <p>
            Gain granular insights into electricity demand patterns, daily peak
            loads, and localized energy expenditures.
          </p>
        </div>

        <div className="analytics-hero__visual" aria-hidden="true">
          <div className="analytics-orbit analytics-orbit--outer" />
          <div className="analytics-orbit analytics-orbit--inner" />
          <div className="analytics-hero__bolt">
            <MetricIcon type="consumption" />
          </div>
        </div>
      </header>

      {/* ================================================================
          Key Metric Cards
          ================================================================ */}
      <section className="analytics-metrics" aria-label="Energy summary metrics">
        <article className="analytics-metric analytics-metric--primary">
          <div className="analytics-metric__top">
            <div className="analytics-metric__icon">
              <MetricIcon type="consumption" />
            </div>
            <span className="analytics-metric__tag">ENERGY</span>
          </div>
          <div className="analytics-metric__label">Total Consumption</div>
          <div className="analytics-metric__value">
            {formatNumber(dailyStatistics.total, 1)}
            <span> kWh</span>
          </div>
          <p>Accumulated usage over reporting window</p>
        </article>

        <article className="analytics-metric">
          <div className="analytics-metric__top">
            <div className="analytics-metric__icon">
              <MetricIcon type="average" />
            </div>
            <span className="analytics-metric__tag">BASELINE</span>
          </div>
          <div className="analytics-metric__label">Daily Average</div>
          <div className="analytics-metric__value">
            {formatNumber(dailyStatistics.average, 1)}
            <span> kWh</span>
          </div>
          <p>Mean energy consumption per day</p>
        </article>

        <article className="analytics-metric">
          <div className="analytics-metric__top">
            <div className="analytics-metric__icon">
              <MetricIcon type="peak" />
            </div>
            <span className="analytics-metric__tag analytics-metric__tag--accent">
              PEAK
            </span>
          </div>
          <div className="analytics-metric__label">Peak Load Hour</div>
          <div className="analytics-metric__value analytics-metric__value--time">
            {formatHour(peakHour)}
          </div>
          <p>
            {peakHourlyKwh !== null
              ? `${formatNumber(peakHourlyKwh, 2)} kWh mean demand`
              : "Peak load unavailable"}
          </p>
        </article>

        <article className="analytics-metric">
          <div className="analytics-metric__top">
            <div className="analytics-metric__icon">
              <MetricIcon type="cost" />
            </div>
            <span className="analytics-metric__tag">ESTIMATE</span>
          </div>
          <div className="analytics-metric__label">Estimated Cost</div>
          <div className="analytics-metric__value">
            {formatCurrency(estimatedCost)}
          </div>
          <p>Calculated using active utility tariffs</p>
        </article>
      </section>

      {/* ================================================================
          Hourly Load Profile Chart
          ================================================================ */}
      <section
        className="analytics-panel analytics-panel--large"
        aria-labelledby="hourly-load-title"
      >
        <div className="analytics-panel__header">
          <div>
            <span className="analytics-panel__eyebrow">DIURNAL PATTERN</span>
            <h2 id="hourly-load-title">Average Hourly Load Profile</h2>
            <p>Distribution of electrical demand across a 24-hour cycle.</p>
          </div>

          {hasHourlyData && (
            <div className="analytics-panel__stat">
              <span>Peak Demand</span>
              <strong>{formatHour(peakHour)}</strong>
              {peakHourlyKwh !== null && (
                <small>{formatNumber(peakHourlyKwh, 2)} kWh</small>
              )}
            </div>
          )}
        </div>

        <p className="sr-only">{hourlyAccessibleSummary}</p>

        {hasHourlyData ? (
          <div className="analytics-chart" aria-hidden="true">
            <ResponsiveContainer width="100%" height={DEFAULT_CHART_HEIGHT}>
              <BarChart
                data={hourlyProfile}
                margin={{ top: 16, right: 12, left: -16, bottom: 8 }}
                barCategoryGap="16%"
              >
                <defs>
                  <linearGradient id="primaryBarGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#0f766e" stopOpacity={0.9} />
                    <stop offset="100%" stopColor="#0f766e" stopOpacity={0.4} />
                  </linearGradient>
                  <linearGradient id="peakBarGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#84cc16" stopOpacity={1} />
                    <stop offset="100%" stopColor="#65a30d" stopOpacity={0.7} />
                  </linearGradient>
                </defs>

                <CartesianGrid
                  stroke="rgba(255, 255, 255, 0.06)"
                  strokeDasharray="3 4"
                  vertical={false}
                />

                <XAxis
                  dataKey="hour"
                  tickFormatter={formatHour}
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={16}
                />

                <YAxis
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                />

                <Tooltip
                  cursor={{ fill: "rgba(255, 255, 255, 0.03)" }}
                  content={<HourlyTooltip />}
                />

                <Bar
                  dataKey="average_kwh"
                  name="Average Load"
                  radius={[6, 6, 2, 2]}
                  isAnimationActive
                  animationDuration={600}
                >
                  {hourlyProfile.map((entry) => (
                    <Cell
                      key={`hour-${entry.hour}`}
                      fill={
                        entry.hour === peakHour
                          ? "url(#peakBarGrad)"
                          : "url(#primaryBarGrad)"
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="analytics-empty-chart" role="status">
            <span>No hourly consumption data available.</span>
          </div>
        )}

        {hasHourlyData && (
          <div className="analytics-chart-footer">
            <div className="analytics-chart-legend">
              <span className="analytics-chart-legend__item">
                <i className="analytics-chart-legend__dot analytics-chart-legend__dot--teal" />
                Baseline Load
              </span>
              <span className="analytics-chart-legend__item">
                <i className="analytics-chart-legend__dot analytics-chart-legend__dot--lime" />
                Peak Hour Demand
              </span>
            </div>
            <span className="analytics-chart-footer__sub">24-hour profile</span>
          </div>
        )}
      </section>

      {/* ================================================================
          Daily Consumption Trend Chart
          ================================================================ */}
      <section
        className="analytics-panel analytics-panel--large"
        aria-labelledby="daily-consumption-title"
      >
        <div className="analytics-panel__header">
          <div>
            <span className="analytics-panel__eyebrow">HISTORICAL TREND</span>
            <h2 id="daily-consumption-title">Daily Consumption</h2>
            <p>Track energy consumption patterns over recent billing days.</p>
          </div>

          {hasDailyData && (
            <div className="analytics-panel__stat">
              <span>Daily Average</span>
              <strong>
                {formatNumber(dailyStatistics.average, 1)} kWh
              </strong>
              <small>{dailyUsage.length} Days Recorded</small>
            </div>
          )}
        </div>

        <p className="sr-only">{dailyAccessibleSummary}</p>

        {hasDailyData ? (
          <div className="analytics-chart" aria-hidden="true">
            <ResponsiveContainer width="100%" height={DEFAULT_CHART_HEIGHT}>
              <BarChart
                data={dailyUsage}
                margin={{ top: 16, right: 12, left: -16, bottom: 8 }}
                barCategoryGap="20%"
              >
                <defs>
                  <linearGradient id="dailyBarGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#14b8a6" stopOpacity={0.85} />
                    <stop offset="100%" stopColor="#0f766e" stopOpacity={0.35} />
                  </linearGradient>
                </defs>

                <CartesianGrid
                  stroke="rgba(255, 255, 255, 0.06)"
                  strokeDasharray="3 4"
                  vertical={false}
                />

                <XAxis
                  dataKey="date"
                  tickFormatter={formatDate}
                  tick={{ fontSize: 10, fill: "#94a3b8" }}
                  axisLine={false}
                  tickLine={false}
                  minTickGap={20}
                />

                <YAxis
                  tick={{ fontSize: 11, fill: "#94a3b8" }}
                  axisLine={false}
                  tickLine={false}
                  width={48}
                />

                <Tooltip
                  cursor={{ fill: "rgba(255, 255, 255, 0.03)" }}
                  content={<DailyTooltip />}
                />

                <Bar
                  dataKey="kwh"
                  name="Daily Consumption"
                  fill="url(#dailyBarGrad)"
                  radius={[6, 6, 2, 2]}
                  isAnimationActive
                  animationDuration={600}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <div className="analytics-empty-chart" role="status">
            <span>No daily consumption data available.</span>
          </div>
        )}

        {hasDailyData && (
          <div className="analytics-chart-footer">
            <div className="analytics-chart-legend">
              <span className="analytics-chart-legend__item">
                <i className="analytics-chart-legend__dot analytics-chart-legend__dot--teal" />
                Energy Consumed (kWh)
              </span>
            </div>
            <span className="analytics-chart-footer__sub">
              Last {dailyUsage.length} periods
            </span>
          </div>
        )}
      </section>
    </main>
  );
}