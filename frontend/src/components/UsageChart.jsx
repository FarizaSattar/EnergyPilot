import { useId, useMemo } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  BarChart3,
  CalendarDays,
  Clock3,
  TrendingUp,
  Zap,
} from "lucide-react";
import "./UsageChart.css";

// =============================================================================
// Constants & Formatters
// =============================================================================

const DEFAULT_MAX_READINGS = 168;
const EMPTY_READINGS = [];
const CHART_HEIGHT = 310;

const AXIS_TIME_FORMAT_OPTIONS = {
  month: "short",
  day: "numeric",
  hour: "numeric",
};

const TOOLTIP_TIME_FORMAT_OPTIONS = {
  weekday: "short",
  month: "short",
  day: "numeric",
  year: "numeric",
  hour: "numeric",
  minute: "2-digit",
};

const NUMBER_FORMATTER = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const AXIS_NUMBER_FORMATTER = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 1,
});

function getUsageValue(item) {
  if (!item || typeof item !== "object") return null;

  const raw =
    item.energy_kwh ??
    item.usage_kwh ??
    item.usage ??
    item.kwh;

  if (
    raw === null ||
    raw === undefined ||
    raw === "" ||
    typeof raw === "boolean"
  ) {
    return null;
  }

  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

function getTimestamp(item) {
  if (!item || typeof item !== "object") return null;

  return (
    item.timestamp ??
    item.ts ??
    item.datetime ??
    item.date ??
    null
  );
}

function parseDate(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  let normalized = value;

  if (
    typeof value === "number" &&
    Number.isFinite(value) &&
    Math.abs(value) < 1e11
  ) {
    normalized = value * 1000;
  } else if (
    typeof value === "string" &&
    /^\d{10}(?:\.\d+)?$/.test(value.trim())
  ) {
    normalized = Number(value) * 1000;
  }

  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

function formatXAxisTime(timestamp) {
  const date = parseDate(timestamp);
  return date ? date.toLocaleString(undefined, AXIS_TIME_FORMAT_OPTIONS) : "";
}

function formatTooltipTime(timestamp) {
  const date = parseDate(timestamp);
  return date ? date.toLocaleString(undefined, TOOLTIP_TIME_FORMAT_OPTIONS) : "Unknown time";
}

function formatNumber(value) {
  return Number.isFinite(value) ? NUMBER_FORMATTER.format(value) : "—";
}

function formatAxisNumber(value) {
  return Number.isFinite(Number(value))
    ? AXIS_NUMBER_FORMATTER.format(Number(value))
    : "";
}

function formatDateRange(date) {
  if (!(date instanceof Date) || Number.isNaN(date.getTime())) {
    return "";
  }

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function normalizeReadings(readings, maxReadings) {
  if (!Array.isArray(readings) || readings.length === 0) {
    return [];
  }

  const normalized = [];

  for (const item of readings) {
    const timestamp = getTimestamp(item);
    const usage = getUsageValue(item);
    const date = parseDate(timestamp);

    if (timestamp === null || usage === null || !date || usage < 0) {
      continue;
    }

    normalized.push({
      timestamp,
      timestampMs: date.getTime(),
      date,
      usage,
    });
  }

  normalized.sort((a, b) => a.timestampMs - b.timestampMs);

  const byTimestamp = new Map();
  for (const item of normalized) {
    byTimestamp.set(item.timestampMs, item);
  }

  const deduplicated = Array.from(byTimestamp.values());

  if (!Number.isInteger(maxReadings) || maxReadings <= 0) {
    return deduplicated;
  }

  return deduplicated.slice(-maxReadings);
}

function calculateStatistics(data) {
  if (data.length === 0) {
    return {
      total: 0,
      average: 0,
      peak: 0,
      peakReading: null,
    };
  }

  let total = 0;
  let peak = -Infinity;
  let peakReading = null;

  for (const item of data) {
    total += item.usage;

    if (item.usage > peak) {
      peak = item.usage;
      peakReading = item;
    }
  }

  return {
    total,
    average: total / data.length,
    peak,
    peakReading,
  };
}

// =============================================================================
// Sub-components
// =============================================================================

function UsageTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;

  const point = payload[0]?.payload;
  if (!point) return null;

  return (
    <div className="usage-tooltip">
      <div className="usage-tooltip__date">
        <CalendarDays size={14} aria-hidden="true" />
        <span>{formatTooltipTime(point.timestamp)}</span>
      </div>

      <div className="usage-tooltip__metric">
        <span className="usage-tooltip__dot" aria-hidden="true" />
        <span className="usage-tooltip__label">Energy consumption</span>
      </div>

      <div className="usage-tooltip__value">
        {formatNumber(point.usage)}
        <span>kWh</span>
      </div>

      <div className="usage-tooltip__caption">Recorded meter reading</div>
    </div>
  );
}

function UsageChartLoading() {
  return (
    <section
      className="usage-chart usage-chart--state"
      aria-label="Electricity consumption chart"
      aria-busy="true"
    >
      <div className="usage-chart__state-icon" aria-hidden="true">
        <Activity size={23} />
      </div>

      <div className="usage-chart__skeleton" aria-hidden="true">
        <span />
        <span />
        <span />
        <span />
      </div>

      <h3>Preparing your energy insights</h3>
      <p>Loading your electricity consumption history…</p>
    </section>
  );
}

function UsageChartEmpty() {
  return (
    <section
      className="usage-chart usage-chart--state"
      aria-label="Electricity consumption chart"
      role="status"
    >
      <div className="usage-chart__state-icon" aria-hidden="true">
        <BarChart3 size={24} />
      </div>

      <h3>No usage data yet</h3>
      <p>
        Upload a CSV dataset or generate simulated smart-meter
        readings to explore your electricity consumption.
      </p>

      <div className="usage-chart__state-note">
        <Zap size={14} aria-hidden="true" />
        Your energy trends will appear here
      </div>
    </section>
  );
}

// =============================================================================
// Main Component
// =============================================================================

/**
 * @typedef {Object} ReadingItem
 * @property {string|number} [timestamp]
 * @property {string|number} [ts]
 * @property {string|number} [datetime]
 * @property {string|number} [date]
 * @property {number} [energy_kwh]
 * @property {number} [usage_kwh]
 * @property {number} [usage]
 * @property {number} [kwh]
 */

/**
 * @typedef {Object} UsageChartProps
 * @property {ReadingItem[]} [readings]
 * @property {number} [maxReadings]
 * @property {boolean} [loading]
 */

/**
 * UsageChart component for displaying historical energy consumption area charts and metrics.
 * 
 * @param {UsageChartProps} props
 */
export default function UsageChart({
  readings = EMPTY_READINGS,
  maxReadings = DEFAULT_MAX_READINGS,
  loading = false,
}) {
  const generatedId = useId();
  const chartId = `usage-chart-${generatedId.replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const gradientId = `${chartId}-gradient`;
  const titleId = `${chartId}-title`;
  const descriptionId = `${chartId}-description`;

  const data = useMemo(
    () => normalizeReadings(readings, maxReadings),
    [readings, maxReadings],
  );

  const statistics = useMemo(
    () => calculateStatistics(data),
    [data],
  );

  const dateRange = useMemo(() => {
    if (data.length === 0) return "Selected period";
    const firstLabel = formatDateRange(data[0].date);
    const lastLabel = formatDateRange(data[data.length - 1].date);

    if (!firstLabel || !lastLabel) return "Selected period";
    return firstLabel === lastLabel ? firstLabel : `${firstLabel} – ${lastLabel}`;
  }, [data]);

  const description = useMemo(() => {
    if (data.length === 0) return "Electricity consumption chart.";
    return (
      `Historical electricity consumption. ${data.length} readings. ` +
      `Total ${formatNumber(statistics.total)} kilowatt-hours. ` +
      `Average ${formatNumber(statistics.average)} kilowatt-hours per reading. ` +
      `Peak ${formatNumber(statistics.peak)} kilowatt-hours. Period: ${dateRange}.`
    );
  }, [data, statistics, dateRange]);

  if (loading) return <UsageChartLoading />;
  if (data.length === 0) return <UsageChartEmpty />;

  return (
    <section className="usage-chart" aria-labelledby={titleId}>
      <header className="usage-chart__header">
        <div className="usage-chart__heading">
          <div className="usage-chart__eyebrow">
            <span className="usage-chart__eyebrow-dot" aria-hidden="true" />
            CONSUMPTION OVERVIEW
          </div>

          <h2 id={titleId} className="usage-chart__title">
            Energy usage
          </h2>

          <p className="usage-chart__description">
            Track your electricity consumption over time.
          </p>
        </div>

        <div className="usage-chart__period">
          <CalendarDays size={15} aria-hidden="true" />
          <span>{dateRange}</span>
        </div>
      </header>

      <div className="usage-chart__metrics">
        <article className="usage-chart__metric usage-chart__metric--primary">
          <div className="usage-chart__metric-top">
            <span>Total consumption</span>
            <span className="usage-chart__metric-icon" aria-hidden="true">
              <Zap size={16} />
            </span>
          </div>

          <div className="usage-chart__metric-value">
            {formatNumber(statistics.total)}
            <span>kWh</span>
          </div>

          <div className="usage-chart__metric-footnote">
            Across {data.length} readings
          </div>
        </article>

        <article className="usage-chart__metric">
          <div className="usage-chart__metric-top">
            <span>Average usage</span>
            <span className="usage-chart__metric-icon" aria-hidden="true">
              <Activity size={16} />
            </span>
          </div>

          <div className="usage-chart__metric-value">
            {formatNumber(statistics.average)}
            <span>kWh</span>
          </div>

          <div className="usage-chart__metric-footnote">
            Per reading
          </div>
        </article>

        <article className="usage-chart__metric">
          <div className="usage-chart__metric-top">
            <span>Peak usage</span>
            <span className="usage-chart__metric-icon" aria-hidden="true">
              <TrendingUp size={16} />
            </span>
          </div>

          <div className="usage-chart__metric-value">
            {formatNumber(statistics.peak)}
            <span>kWh</span>
          </div>

          <div className="usage-chart__metric-footnote">
            Highest recorded reading
          </div>
        </article>
      </div>

      <div className="usage-chart__plot-header">
        <div>
          <h3>Consumption trend</h3>
          <p>Electricity usage by timestamp</p>
        </div>

        <div className="usage-chart__legend">
          <span className="usage-chart__legend-dot" aria-hidden="true" />
          Energy usage
        </div>
      </div>

      <p id={descriptionId} className="usage-chart__sr-only">
        {description}
      </p>

      <div
        className="usage-chart__visual"
        role="img"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <ResponsiveContainer width="100%" height={CHART_HEIGHT}>
          <AreaChart
            data={data}
            margin={{ top: 12, right: 12, left: 2, bottom: 2 }}
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
                  stopColor="#65a30d"
                  stopOpacity={0.24}
                />
                <stop
                  offset="55%"
                  stopColor="#65a30d"
                  stopOpacity={0.09}
                />
                <stop
                  offset="100%"
                  stopColor="#65a30d"
                  stopOpacity={0.005}
                />
              </linearGradient>
            </defs>

            <CartesianGrid
              stroke="#edf1e9"
              strokeDasharray="3 5"
              vertical={false}
            />

            <XAxis
              dataKey="timestampMs"
              type="number"
              scale="time"
              domain={["dataMin", "dataMax"]}
              tickFormatter={formatXAxisTime}
              tick={{ fill: "#879187", fontSize: 11 }}
              minTickGap={35}
              axisLine={false}
              tickLine={false}
              tickMargin={13}
              padding={{ left: 4, right: 4 }}
            />

            <YAxis
              tickFormatter={formatAxisNumber}
              tick={{ fill: "#879187", fontSize: 11 }}
              axisLine={false}
              tickLine={false}
              tickMargin={10}
              width={48}
              allowDecimals
              domain={[0, "auto"]}
            />

            <Tooltip
              content={<UsageTooltip />}
              cursor={{
                stroke: "#a3b98a",
                strokeWidth: 1,
                strokeDasharray: "4 4",
              }}
              wrapperStyle={{ outline: "none", zIndex: 10 }}
            />

            <Area
              type="monotone"
              dataKey="usage"
              name="Energy usage"
              stroke="#5b9410"
              strokeWidth={2.6}
              strokeLinecap="round"
              strokeLinejoin="round"
              fill={`url(#${gradientId})`}
              dot={false}
              activeDot={{
                r: 5,
                fill: "#fff",
                stroke: "#5b9410",
                strokeWidth: 2.5,
              }}
              isAnimationActive={data.length < 300}
              animationDuration={650}
              animationEasing="ease-out"
              connectNulls={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <footer className="usage-chart__footer">
        <div className="usage-chart__footer-item">
          <span className="usage-chart__footer-icon" aria-hidden="true">
            <Clock3 size={14} />
          </span>
          <span>
            <strong>{data.length}</strong>{" "}
            {data.length === 1 ? "reading" : "readings"} analyzed
          </span>
        </div>

        {statistics.peakReading && (
          <div className="usage-chart__footer-item usage-chart__footer-peak">
            <span className="usage-chart__footer-dot" aria-hidden="true" />
            <span>
              Peak recorded{" "}
              <strong>{formatTooltipTime(statistics.peakReading.timestamp)}</strong>
            </span>
          </div>
        )}
      </footer>
    </section>
  );
}