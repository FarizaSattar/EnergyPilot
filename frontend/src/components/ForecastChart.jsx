import { useId, useMemo } from "react";
import {
  Activity,
  BarChart3,
  Clock3,
  TrendingUp,
  Zap,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import "./ForecastChart.css";

/* ============================================================================
   Configuration & Constants
   ========================================================================== */

const EMPTY_STATE_MESSAGE =
  "Generate or upload energy readings to produce a demand forecast.";

const DEFAULT_UNIT = "kWh";

const FORECAST_VALUE_FIELDS = Object.freeze([
  "predicted_kwh",
  "predicted_kw",
  "forecast_kwh",
  "forecast_kw",
  "prediction",
  "forecast",
  "value",
]);

const UPPER_BOUND_FIELDS = Object.freeze([
  "upper_bound",
  "p90",
  "confidence_high",
  "max",
]);

const LOWER_BOUND_FIELDS = Object.freeze([
  "lower_bound",
  "p10",
  "confidence_low",
  "min",
]);

const TIMESTAMP_FIELDS = Object.freeze([
  "timestamp",
  "ts",
  "datetime",
  "date",
  "time",
]);

/* ============================================================================
   Static Formatters (Instantiated once to maximize performance)
   ========================================================================== */

const AXIS_TIME_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  weekday: "short",
  hour: "numeric",
  minute: "2-digit",
});

const TOOLTIP_TIME_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  weekday: "short",
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const VALUE_FORMATTER = new Intl.NumberFormat("en-CA", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const INTEGER_FORMATTER = new Intl.NumberFormat("en-CA", {
  maximumFractionDigits: 0,
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

function getFirstDefinedValue(item, fields) {
  if (!item || typeof item !== "object" || Array.isArray(item)) {
    return null;
  }

  for (const field of fields) {
    const value = item[field];
    if (value !== null && value !== undefined && value !== "") {
      return value;
    }
  }

  return null;
}

function parseTimestamp(timestamp) {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatXAxisTime(timestampMs) {
  if (!timestampMs) return "";
  return AXIS_TIME_FORMATTER.format(new Date(timestampMs));
}

function formatTooltipTime(timestampMs) {
  if (!timestampMs) return "Unknown time";
  return TOOLTIP_TIME_FORMATTER.format(new Date(timestampMs));
}

function formatValue(value) {
  const number = toFiniteNumber(value);
  return number === null ? "—" : VALUE_FORMATTER.format(number);
}

function formatCount(value) {
  const number = toFiniteNumber(value);
  return number === null ? "0" : INTEGER_FORMATTER.format(number);
}

/* ============================================================================
   Forecast Field Extraction & Data Normalization
   ========================================================================== */

function extractForecastArray(forecast) {
  if (Array.isArray(forecast)) return forecast;
  if (!forecast || typeof forecast !== "object") return [];

  const possibleArrays = [
    forecast.forecast,
    forecast.predictions,
    forecast.data,
    forecast.results,
    forecast.series,
  ];

  for (const candidate of possibleArrays) {
    if (Array.isArray(candidate)) return candidate;
  }

  return [];
}

function normalizeForecastData(rawForecast) {
  const records = extractForecastArray(rawForecast);
  if (!records.length) return [];

  const uniqueByTimestamp = new Map();

  for (let i = 0; i < records.length; i++) {
    const item = records[i];
    if (!item || typeof item !== "object") continue;

    const rawTs = getFirstDefinedValue(item, TIMESTAMP_FIELDS);
    const date = parseTimestamp(rawTs);

    let forecastVal = null;
    for (const field of FORECAST_VALUE_FIELDS) {
      const num = toFiniteNumber(item[field]);
      if (num !== null) {
        forecastVal = num;
        break;
      }
    }

    if (!date || forecastVal === null || forecastVal < 0) {
      continue;
    }

    const upperBound = toFiniteNumber(getFirstDefinedValue(item, UPPER_BOUND_FIELDS));
    const lowerBound = toFiniteNumber(getFirstDefinedValue(item, LOWER_BOUND_FIELDS));

    const timestampMs = date.getTime();
    
    // Deduplicate: later indices override earlier ones for identical timestamps
    uniqueByTimestamp.set(timestampMs, {
      timestamp: date.toISOString(),
      timestampMs,
      forecast: forecastVal,
      range: upperBound !== null && lowerBound !== null ? [lowerBound, upperBound] : null,
      upperBound,
      lowerBound,
    });
  }

  return Array.from(uniqueByTimestamp.values()).sort(
    (a, b) => a.timestampMs - b.timestampMs
  );
}

/* ============================================================================
   Statistics Calculation
   ========================================================================== */

function calculateStatistics(data) {
  if (!data.length) {
    return {
      average: null,
      peak: null,
      minimum: null,
      range: null,
      peakPoint: null,
    };
  }

  let total = 0;
  let peak = -Infinity;
  let minimum = Infinity;
  let peakPoint = null;

  for (let i = 0; i < data.length; i++) {
    const val = data[i].forecast;
    total += val;

    if (val > peak) {
      peak = val;
      peakPoint = data[i];
    }

    if (val < minimum) {
      minimum = val;
    }
  }

  return {
    average: total / data.length,
    peak,
    minimum,
    range: peak - minimum,
    peakPoint,
  };
}

/* ============================================================================
   Sub-components
   ========================================================================== */

function ForecastTooltip({ active, payload, unit = DEFAULT_UNIT }) {
  if (!active || !Array.isArray(payload) || !payload.length) {
    return null;
  }

  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div className="forecast-tooltip" role="status" aria-live="polite">
      <div className="forecast-tooltip-header">
        <span className="forecast-tooltip-icon">
          <Zap size={13} strokeWidth={2.4} />
        </span>
        <span className="forecast-tooltip-date">
          {formatTooltipTime(point.timestampMs)}
        </span>
      </div>

      <div className="forecast-tooltip-value">
        <span>{formatValue(point.forecast)}</span>
        <small>{unit}</small>
      </div>

      {point.upperBound !== null && point.lowerBound !== null && (
        <div className="forecast-tooltip-range">
          <span>Range: </span>
          <strong>
            {formatValue(point.lowerBound)} – {formatValue(point.upperBound)} {unit}
          </strong>
        </div>
      )}

      <div className="forecast-tooltip-caption">Predicted consumption</div>
    </div>
  );
}

function ForecastEmptyState() {
  return (
    <section className="forecast-empty" aria-labelledby="forecast-empty-title">
      <div className="forecast-empty-icon" aria-hidden="true">
        <BarChart3 size={22} strokeWidth={1.8} />
      </div>
      <div className="forecast-empty-content">
        <span className="forecast-empty-eyebrow">Demand forecast</span>
        <h3 id="forecast-empty-title">Forecast unavailable</h3>
        <p>{EMPTY_STATE_MESSAGE}</p>
      </div>
    </section>
  );
}

function ForecastSummary({ statistics, unit, pointCount }) {
  const items = [
    {
      key: "average",
      label: "Average",
      value: formatValue(statistics.average),
      unit,
      icon: Activity,
    },
    {
      key: "peak",
      label: "Peak demand",
      value: formatValue(statistics.peak),
      unit,
      icon: TrendingUp,
    },
    {
      key: "minimum",
      label: "Minimum",
      value: formatValue(statistics.minimum),
      unit,
      icon: Zap,
    },
    {
      key: "points",
      label: "Forecast points",
      value: formatCount(pointCount),
      unit: null,
      icon: Clock3,
    },
  ];

  return (
    <div className="forecast-summary" aria-label="Forecast summary statistics">
      {items.map(({ key, label, value, unit: itemUnit, icon: Icon }) => (
        <div className="forecast-stat" key={key}>
          <div className="forecast-stat-top">
            <span className="forecast-stat-icon">
              <Icon size={15} strokeWidth={2} />
            </span>
            <span className="forecast-stat-label">{label}</span>
          </div>
          <div className="forecast-stat-value">
            <strong>{value}</strong>
            {itemUnit && <small>{itemUnit}</small>}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ============================================================================
   Main ForecastChart Component
   ========================================================================== */

export default function ForecastChart({
  forecast = [],
  unit = DEFAULT_UNIT,
  height = 320,
  showPeakLine = true,
}) {
  const rawId = useId();
  const gradientId = useMemo(
    () => `forecast-gradient-${rawId.replace(/:/g, "")}`,
    [rawId]
  );
  const rangeGradientId = useMemo(
    () => `forecast-range-gradient-${rawId.replace(/:/g, "")}`,
    [rawId]
  );

  const data = useMemo(() => normalizeForecastData(forecast), [forecast]);
  const statistics = useMemo(() => calculateStatistics(data), [data]);

  if (!data.length) {
    return <ForecastEmptyState />;
  }

  const pointCount = data.length;
  const hasRangeData = data.some((p) => p.range !== null);

  return (
    <section
      className="forecast-chart"
      aria-labelledby="forecast-chart-title"
    >
      {/* Header */}
      <header className="forecast-chart-header">
        <div className="forecast-chart-heading">
          <div className="forecast-chart-title-row">
            <span className="forecast-chart-eyebrow">
              <span className="forecast-eyebrow-dot" aria-hidden="true" />
              Demand forecast
            </span>

            <span
              className="forecast-chart-status"
              aria-label="Live model output available"
            >
              <span className="forecast-status-dot" aria-hidden="true" />
              Live model output
            </span>
          </div>

          <h2 id="forecast-chart-title" className="forecast-chart-title">
            Predicted energy consumption
          </h2>

          <p className="forecast-chart-description">
            Expected electricity usage across the forecast horizon.
          </p>
        </div>

        <div
          className="forecast-header-metric"
          aria-label={`Forecast contains ${pointCount} data points`}
        >
          <span className="forecast-header-metric-value">
            {formatCount(pointCount)}
          </span>
          <span className="forecast-header-metric-label">forecast points</span>
        </div>
      </header>

      {/* Summary Statistics */}
      <ForecastSummary
        statistics={statistics}
        unit={unit}
        pointCount={pointCount}
      />

      {/* Chart Canvas */}
      <div
        className="forecast-chart-container"
        role="img"
        aria-label={`Predicted electricity consumption over ${pointCount} forecast ${
          pointCount === 1 ? "point" : "points"
        }`}
      >
        <ResponsiveContainer width="100%" height={height}>
          <AreaChart
            data={data}
            margin={{
              top: 16,
              right: 16,
              left: 4,
              bottom: 8,
            }}
          >
            <defs>
              <linearGradient
                id={gradientId}
                x1="0"
                y1="0"
                x2="0"
                y2="1"
              >
                <stop
                  offset="0%"
                  stopColor="var(--ep-green-700, #15803d)"
                  stopOpacity={0.25}
                />
                <stop
                  offset="60%"
                  stopColor="var(--ep-green-700, #15803d)"
                  stopOpacity={0.06}
                />
                <stop
                  offset="100%"
                  stopColor="var(--ep-green-700, #15803d)"
                  stopOpacity={0}
                />
              </linearGradient>

              {hasRangeData && (
                <linearGradient
                  id={rangeGradientId}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor="var(--ep-green-600, #16a34a)"
                    stopOpacity={0.12}
                  />
                  <stop
                    offset="100%"
                    stopColor="var(--ep-green-600, #16a34a)"
                    stopOpacity={0.02}
                  />
                </linearGradient>
              )}
            </defs>

            <CartesianGrid
              stroke="var(--ep-border, #e2e8f0)"
              strokeDasharray="3 5"
              vertical={false}
              opacity={0.75}
            />

            <XAxis
              dataKey="timestampMs"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={formatXAxisTime}
              tick={{
                fontSize: 11,
                fill: "var(--ep-text-muted, #64748b)",
              }}
              minTickGap={48}
              axisLine={false}
              tickLine={false}
              padding={{ left: 10, right: 10 }}
            />

            <YAxis
              tick={{
                fontSize: 11,
                fill: "var(--ep-text-muted, #64748b)",
              }}
              axisLine={false}
              tickLine={false}
              width={62}
              tickFormatter={formatValue}
              allowDecimals
              domain={[0, "auto"]}
            />

            <Tooltip
              content={<ForecastTooltip unit={unit} />}
              cursor={{
                stroke: "var(--ep-green-700, #15803d)",
                strokeWidth: 1,
                strokeDasharray: "5 5",
                opacity: 0.35,
              }}
              wrapperStyle={{ outline: "none" }}
            />

            {/* Confidence/Prediction Interval Bounds (if payload provides lower/upper bounds) */}
            {hasRangeData && (
              <Area
                type="monotone"
                dataKey="range"
                stroke="none"
                fill={`url(#${rangeGradientId})`}
                isAnimationActive={false}
              />
            )}

            {/* Primary Forecast Line */}
            <Area
              type="monotone"
              dataKey="forecast"
              name="Forecast"
              stroke="var(--ep-green-700, #15803d)"
              strokeWidth={2.5}
              fill={`url(#${gradientId})`}
              fillOpacity={1}
              dot={data.length === 1}
              activeDot={{
                r: 5,
                strokeWidth: 3,
                stroke: "var(--ep-white, #ffffff)",
                fill: "var(--ep-green-700, #15803d)",
              }}
              isAnimationActive
              animationDuration={650}
              animationEasing="ease-out"
            />

            {/* Peak Demand Marker Reference Line */}
            {showPeakLine && statistics.peakPoint && (
              <ReferenceLine
                y={statistics.peak}
                stroke="var(--ep-amber-500, #f59e0b)"
                strokeDasharray="4 4"
                strokeWidth={1.5}
              />
            )}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Footer */}
      <footer className="forecast-chart-footer">
        <div className="forecast-footer-item">
          <span className="forecast-footer-label">Forecast horizon</span>
          <strong>
            {formatCount(pointCount)}{" "}
            {pointCount === 1 ? "point" : "points"}
          </strong>
        </div>

        {statistics.peakPoint && (
          <div className="forecast-footer-item forecast-footer-item-right">
            <span className="forecast-footer-label">Peak expected</span>
            <strong>
              {formatValue(statistics.peak)} {unit}
            </strong>
          </div>
        )}
      </footer>
    </section>
  );
}