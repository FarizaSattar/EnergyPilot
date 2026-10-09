import React, { useMemo } from "react";
import {
  Activity,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  Clock,
  Cpu,
  Database,
  FileText,
  Gauge,
  Upload,
  Zap,
} from "lucide-react";
import UploadPanel from "../components/UploadPanel";
import "./Data.css";

/* ============================================================================
   EnergyPilot — Data Pipeline Page
   ============================================================================ */

const DEFAULT_RECENT_COUNT = 10;
const EMPTY_ARRAY = Object.freeze([]);

const SOURCE_LABELS = Object.freeze({
  esp32: "ESP32",
  simulator: "Simulator",
  csv: "CSV Upload",
  csv_upload: "CSV Upload",
  smart_meter: "Smart Meter",
  smartmeter: "Smart Meter",
});

/* ============================================================================
   Formatting & Normalization Helpers
   ============================================================================ */

function firstDefined(...values) {
  return values.find(
    (value) => value !== undefined && value !== null && value !== ""
  );
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

  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function parseTimestamp(timestamp) {
  if (!timestamp) return null;

  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

function getReadingEnergy(reading) {
  if (!reading || typeof reading !== "object") return null;

  return toFiniteNumber(
    firstDefined(
      reading.energy_kwh,
      reading.usage_kwh,
      reading.kwh,
      reading.energy,
      reading.usage
    )
  );
}

function getReadingTimestamp(reading) {
  if (!reading || typeof reading !== "object") return null;

  return firstDefined(
    reading.timestamp,
    reading.ts,
    reading.datetime,
    reading.date
  );
}

function normalizeSource(source) {
  if (!source || String(source).trim() === "") {
    return "unknown";
  }
  return String(source).trim().toLowerCase();
}

function formatSource(source) {
  const normalized = normalizeSource(source);

  if (SOURCE_LABELS[normalized]) {
    return SOURCE_LABELS[normalized];
  }

  return normalized
    .replace(/[\_-]+/g, " ")
    .replace(/\s+/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function formatTimestamp(timestamp) {
  const date = parseTimestamp(timestamp);

  if (!date) return "Unknown";

  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function formatEnergy(value, maximumFractionDigits = 3) {
  const number = toFiniteNumber(value);

  if (number === null) return "—";

  const digits = Math.min(
    6,
    Math.max(
      0,
      Number.isInteger(maximumFractionDigits) ? maximumFractionDigits : 3
    )
  );

  return new Intl.NumberFormat("en-CA", {
    minimumFractionDigits: 0,
    maximumFractionDigits: digits,
  }).format(number);
}

function formatCount(value) {
  const number = toFiniteNumber(value);
  if (number === null) return "0";

  return new Intl.NumberFormat("en-CA").format(number);
}

function getReadingKey(reading, index) {
  const stableId = firstDefined(
    reading?.id,
    reading?.reading_id,
    reading?.uuid
  );

  if (stableId !== undefined && stableId !== null) {
    return String(stableId);
  }

  return [
    reading?._timestamp ?? "unknown-time",
    reading?._source ?? "unknown-source",
    reading?._index ?? index,
  ].join("-");
}

/* ============================================================================
   Data Processing Hooks & Calculators
   ============================================================================ */

function normalizeReadings(readings) {
  if (!Array.isArray(readings) || readings.length === 0) {
    return EMPTY_ARRAY;
  }

  return readings
    .filter((reading) => reading !== null && typeof reading === "object")
    .map((reading, index) => {
      const timestamp = getReadingTimestamp(reading);
      const timestampDate = parseTimestamp(timestamp);
      const energyKwh = getReadingEnergy(reading);

      const source = firstDefined(
        reading.source,
        reading.data_source,
        reading.origin,
        "unknown"
      );

      return {
        ...reading,
        _index: index,
        _timestamp: timestamp,
        _timestampDate: timestampDate,
        _energyKwh: energyKwh,
        _source: normalizeSource(source),
        _validEnergy: energyKwh !== null && energyKwh >= 0,
        _validTimestamp: timestampDate !== null,
      };
    });
}

function calculateStatistics(readings) {
  let validEnergyCount = 0;
  let invalidEnergyCount = 0;
  let validTimestampCount = 0;
  let totalEnergyKwh = 0;
  let minimumEnergyKwh = null;
  let maximumEnergyKwh = null;

  for (const reading of readings) {
    if (reading._validTimestamp) {
      validTimestampCount += 1;
    }

    if (!reading._validEnergy) {
      invalidEnergyCount += 1;
      continue;
    }

    validEnergyCount += 1;
    totalEnergyKwh += reading._energyKwh;

    if (
      minimumEnergyKwh === null ||
      reading._energyKwh < minimumEnergyKwh
    ) {
      minimumEnergyKwh = reading._energyKwh;
    }

    if (
      maximumEnergyKwh === null ||
      reading._energyKwh > maximumEnergyKwh
    ) {
      maximumEnergyKwh = reading._energyKwh;
    }
  }

  return {
    totalRecords: readings.length,
    validEnergyCount,
    invalidEnergyCount,
    validTimestampCount,
    totalEnergyKwh,
    averageEnergyKwh:
      validEnergyCount > 0 ? totalEnergyKwh / validEnergyCount : null,
    minimumEnergyKwh,
    maximumEnergyKwh,
  };
}

function calculateSourceCounts(readings) {
  if (readings.length === 0) return {};

  const counts = {};
  for (const reading of readings) {
    const source = reading._source || "unknown";
    counts[source] = (counts[source] ?? 0) + 1;
  }

  return counts;
}

function getReadingStatus(reading) {
  if (!reading._validEnergy) {
    return {
      label: "Review energy",
      type: "warning",
      icon: AlertCircle,
    };
  }

  if (!reading._validTimestamp) {
    return {
      label: "Review time",
      type: "warning",
      icon: AlertCircle,
    };
  }

  return {
    label: "Validated",
    type: "success",
    icon: CheckCircle2,
  };
}

/* ============================================================================
   Data Component
   ============================================================================ */

export default function Data({
  readings = EMPTY_ARRAY,
  onUpload,
  onSimulate,
  loading = false,
  recentCount = DEFAULT_RECENT_COUNT,
}) {
  const normalizedReadings = useMemo(
    () => normalizeReadings(readings),
    [readings]
  );

  const statistics = useMemo(
    () => calculateStatistics(normalizedReadings),
    [normalizedReadings]
  );

  const sourceCounts = useMemo(
    () => calculateSourceCounts(normalizedReadings),
    [normalizedReadings]
  );

  const latestReadings = useMemo(() => {
    const requestedCount = Number(recentCount);
    const count =
      Number.isFinite(requestedCount) && requestedCount > 0
        ? Math.floor(requestedCount)
        : DEFAULT_RECENT_COUNT;

    return [...normalizedReadings]
      .sort((a, b) => {
        const aTime = a._timestampDate?.getTime() ?? -Infinity;
        const bTime = b._timestampDate?.getTime() ?? -Infinity;
        return bTime - aTime;
      })
      .slice(0, count);
  }, [normalizedReadings, recentCount]);

  const sourceEntries = useMemo(
    () =>
      Object.entries(sourceCounts).sort(
        ([sourceA, countA], [sourceB, countB]) =>
          countB - countA || sourceA.localeCompare(sourceB)
      ),
    [sourceCounts]
  );

  const qualityPercentage =
    statistics.totalRecords > 0
      ? Math.round(
          (statistics.validEnergyCount / statistics.totalRecords) * 100
        )
      : null;

  const timestampPercentage =
    statistics.totalRecords > 0
      ? Math.round(
          (statistics.validTimestampCount / statistics.totalRecords) * 100
        )
      : null;

  const hasData = statistics.totalRecords > 0;
  const hasInvalidData = statistics.invalidEnergyCount > 0;

  const qualityState =
    qualityPercentage === null
      ? "empty"
      : qualityPercentage >= 98
      ? "excellent"
      : qualityPercentage >= 90
      ? "good"
      : "review";

  return (
    <main className="page data-page" aria-labelledby="data-page-title">
      {/* ===================================================================
          Hero Section
          =================================================================== */}
      <header className="data-hero">
        <div className="data-hero__content">
          <div className="data-eyebrow">
            <span className="data-eyebrow__dot" />
            DATA PIPELINE
          </div>

          <h1 id="data-page-title">
            Your energy data, <span>connected.</span>
          </h1>

          <p>
            Bring smart-meter readings into EnergyPilot, validate their quality,
            and follow every measurement from ingestion to insight.
          </p>

          <div className="data-hero__meta">
            <span>
              <Database size={15} aria-hidden="true" />
              {formatCount(statistics.totalRecords)} records
            </span>

            <span className="data-hero__meta-divider" />

            <span>
              <Activity size={15} aria-hidden="true" />
              {sourceEntries.length || 0} source
              {sourceEntries.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>

        <div
          className={`data-pipeline-badge data-pipeline-badge--${
            loading
              ? "loading"
              : hasInvalidData
              ? "warning"
              : "ready"
          }`}
          role="status"
          aria-live="polite"
        >
          <span className="data-pipeline-badge__icon">
            {loading ? (
              <Activity size={17} aria-hidden="true" />
            ) : hasInvalidData ? (
              <AlertCircle size={17} aria-hidden="true" />
            ) : (
              <CheckCircle2 size={17} aria-hidden="true" />
            )}
          </span>

          <span>
            <strong>
              {loading
                ? "Processing"
                : hasInvalidData
                ? "Review recommended"
                : "Pipeline ready"}
            </strong>

            <small>
              {loading
                ? "Updating your dataset"
                : hasInvalidData
                ? "Some records need attention"
                : "Ready for analysis"}
            </small>
          </span>
        </div>
      </header>

      {/* ===================================================================
          Overview Metrics
          =================================================================== */}
      <section className="data-metrics" aria-label="Dataset overview">
        <MetricCard
          icon={Database}
          label="Data records"
          value={formatCount(statistics.totalRecords)}
          description="Readings currently available"
          accent="green"
        />

        <MetricCard
          icon={Zap}
          label="Total energy"
          value={formatEnergy(statistics.totalEnergyKwh, 1)}
          unit="kWh"
          description="Sum of valid measurements"
          accent="lime"
        />

        <MetricCard
          icon={Gauge}
          label="Average reading"
          value={formatEnergy(statistics.averageEnergyKwh, 3)}
          unit="kWh"
          description="Average valid record"
          accent="teal"
        />

        <MetricCard
          icon={qualityState === "review" ? AlertCircle : CheckCircle2}
          label="Data quality"
          value={
            qualityPercentage === null ? "—" : `${qualityPercentage}%`
          }
          description={
            statistics.invalidEnergyCount > 0
              ? `${formatCount(
                  statistics.invalidEnergyCount
                )} record${
                  statistics.invalidEnergyCount === 1 ? "" : "s"
                } need review`
              : hasData
              ? "Energy values validated"
              : "No readings loaded"
          }
          accent={qualityState === "review" ? "amber" : "green"}
        />
      </section>

      {/* ===================================================================
          Ingestion Controls Panel
          =================================================================== */}
      <section className="data-panel data-panel--ingestion">
        <PanelHeader
          eyebrow="DATA INGESTION"
          title="Bring your data into EnergyPilot"
          description="Import real smart-meter exports or generate simulated ESP32 telemetry to explore the platform."
          icon={Upload}
          status={
            loading
              ? { label: "Processing", type: "loading" }
              : { label: "Ready", type: "ready" }
          }
        />

        <div className="ingestion-intro">
          <div className="ingestion-intro__icon">
            <Upload size={22} aria-hidden="true" />
          </div>

          <div>
            <strong>Choose your data source</strong>
            <p>
              Upload a CSV for real measurements or generate simulated readings
              when you want a clean dataset for testing.
            </p>
          </div>
        </div>

        <UploadPanel
          onUpload={onUpload}
          onSimulate={onSimulate}
          loading={loading}
        />
      </section>

      {/* ===================================================================
          Architecture Flow
          =================================================================== */}
      <section className="data-panel">
        <PanelHeader
          eyebrow="ENERGY DATA FLOW"
          title="From meter to insight"
          description="A simple ingestion path connects physical electricity measurements to EnergyPilot's analytics layer."
          icon={Activity}
        />

        <div className="pipeline" aria-label="EnergyPilot data pipeline">
          <PipelineStep
            number="01"
            icon={Cpu}
            title="ESP32 Smart Meter"
            description="Measures household electricity consumption."
          />

          <PipelineConnector />

          <PipelineStep
            number="02"
            icon={Activity}
            title="MQTT Telemetry"
            description="Publishes meter readings to the backend."
          />

          <PipelineConnector />

          <PipelineStep
            number="03"
            icon={Database}
            title="Time-Series Storage"
            description="Stores timestamped electricity measurements."
          />

          <PipelineConnector />

          <PipelineStep
            number="04"
            icon={Zap}
            title="Energy Analytics"
            description="Transforms measurements into forecasts, pricing insights, and recommendations."
          />
        </div>
      </section>

      {/* ===================================================================
          Recent Smart-Meter Readings Table
          =================================================================== */}
      <section className="data-panel">
        <PanelHeader
          eyebrow="SMART-METER DATA"
          title="Recent readings"
          description="The latest electricity measurements currently available to EnergyPilot."
          icon={Clock}
          action={
            <div
              className="data-panel-count"
              aria-label={`${formatCount(
                statistics.totalRecords
              )} total records`}
            >
              <Database size={15} aria-hidden="true" />
              <span>{formatCount(statistics.totalRecords)}</span>
            </div>
          }
        />

        {latestReadings.length > 0 ? (
          <div className="data-table-wrapper">
            <table className="data-table">
              <caption className="sr-only">
                Most recent EnergyPilot electricity readings
              </caption>

              <thead>
                <tr>
                  <th scope="col">Timestamp</th>
                  <th scope="col">Energy</th>
                  <th scope="col">Source</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>

              <tbody>
                {latestReadings.map((reading, index) => {
                  const rowKey = getReadingKey(reading, index);
                  const status = getReadingStatus(reading);
                  const StatusIcon = status.icon;

                  return (
                    <tr key={rowKey}>
                      <td>
                        <div className="reading-time">
                          <span className="reading-time__icon">
                            <Clock size={14} aria-hidden="true" />
                          </span>

                          <time
                            dateTime={
                              reading._validTimestamp
                                ? reading._timestamp
                                : undefined
                            }
                          >
                            {formatTimestamp(reading._timestamp)}
                          </time>
                        </div>
                      </td>

                      <td>
                        {reading._validEnergy ? (
                          <span className="reading-energy">
                            {formatEnergy(reading._energyKwh, 3)}
                            <small>kWh</small>
                          </span>
                        ) : (
                          <span className="invalid-value">Invalid</span>
                        )}
                      </td>

                      <td>
                        <span className="source-badge">
                          <FileText size={13} aria-hidden="true" />
                          {formatSource(reading._source)}
                        </span>
                      </td>

                      <td>
                        <span
                          className={`status-badge status-badge--${status.type}`}
                        >
                          <StatusIcon size={13} aria-hidden="true" />
                          {status.label}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyDataState />
        )}
      </section>

      {/* ===================================================================
          Data Quality Section
          =================================================================== */}
      {hasData && (
        <section className="data-panel">
          <PanelHeader
            eyebrow="DATA QUALITY"
            title="Dataset health"
            description="A quick validation summary for the readings currently loaded into EnergyPilot."
            icon={CheckCircle2}
          />

          <div className="quality-overview">
            <div
              className={`quality-score quality-score--${qualityState}`}
            >
              <div className="quality-score__ring">
                <strong>
                  {qualityPercentage ?? 0}
                  <span>%</span>
                </strong>
              </div>

              <div>
                <span className="quality-score__eyebrow">
                  OVERALL QUALITY
                </span>

                <h3>
                  {qualityState === "excellent"
                    ? "Excellent dataset health"
                    : qualityState === "good"
                    ? "Good dataset health"
                    : "Review recommended"}
                </h3>

                <p>
                  {statistics.invalidEnergyCount > 0
                    ? `${formatCount(
                        statistics.invalidEnergyCount
                      )} reading${
                        statistics.invalidEnergyCount === 1 ? "" : "s"
                      } contain invalid energy values.`
                    : "All energy values currently pass validation."}
                </p>
              </div>
            </div>

            <div className="quality-metrics">
              <QualityMetric
                icon={CheckCircle2}
                label="Valid energy values"
                value={formatCount(statistics.validEnergyCount)}
                description="Non-negative numeric readings"
                type="success"
              />

              <QualityMetric
                icon={Clock}
                label="Valid timestamps"
                value={formatCount(statistics.validTimestampCount)}
                description={
                  timestampPercentage === null
                    ? "No timestamps available"
                    : `${timestampPercentage}% of records`
                }
                type="success"
              />

              <QualityMetric
                icon={AlertCircle}
                label="Records needing review"
                value={formatCount(statistics.invalidEnergyCount)}
                description="Missing, malformed, or negative energy values"
                type={
                  statistics.invalidEnergyCount > 0 ? "warning" : "success"
                }
              />
            </div>
          </div>
        </section>
      )}

      {/* ===================================================================
          Data Sources Grid
          =================================================================== */}
      {sourceEntries.length > 0 && (
        <section className="data-panel">
          <PanelHeader
            eyebrow="DATA SOURCES"
            title="Where your readings come from"
            description="A breakdown of the sources contributing to the current dataset."
            icon={Database}
          />

          <div className="source-grid">
            {sourceEntries.map(([source, count], index) => {
              const isEsp32 = source.includes("esp32");
              const SourceIcon = isEsp32 ? Cpu : FileText;

              const percentage =
                statistics.totalRecords > 0
                  ? Math.round((count / statistics.totalRecords) * 100)
                  : 0;

              return (
                <article className="source-card" key={source}>
                  <div className="source-card__top">
                    <div className="source-card__icon">
                      <SourceIcon size={18} aria-hidden="true" />
                    </div>

                    <span className="source-card__rank">
                      {String(index + 1).padStart(2, "0")}
                    </span>
                  </div>

                  <div className="source-card__body">
                    <h3>{formatSource(source)}</h3>

                    <div className="source-card__stats">
                      <strong>{formatCount(count)}</strong>
                      <span>{count === 1 ? "reading" : "readings"}</span>
                      <span className="source-card__separator">·</span>
                      <span>{percentage}%</span>
                    </div>

                    <div
                      className="source-card__track"
                      role="progressbar"
                      aria-label={`${formatSource(
                        source
                      )} represents ${percentage}% of readings`}
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={percentage}
                    >
                      <span style={{ width: `${percentage}%` }} />
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        </section>
      )}

      {/* ===================================================================
          Footer Insight Banner
          =================================================================== */}
      <aside className="data-insight">
        <div className="data-insight__icon">
          <Zap size={19} aria-hidden="true" />
        </div>

        <div className="data-insight__content">
          <span>PIPELINE INSIGHT</span>

          <h2>Clean data creates better energy intelligence.</h2>

          <p>
            EnergyPilot uses validated readings as the foundation for load
            analytics, forecasting, tariff calculations, and personalized
            recommendations.
          </p>
        </div>

        <ChevronRight
          className="data-insight__arrow"
          size={20}
          aria-hidden="true"
        />
      </aside>
    </main>
  );
}

/* ============================================================================
   Supporting Sub-Components
   ============================================================================ */

function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  description,
  accent = "green",
}) {
  return (
    <article className={`data-metric-card data-metric-card--${accent}`}>
      <div className="data-metric-card__top">
        <span className="data-metric-card__label">{label}</span>
        <span className="data-metric-card__icon">
          <Icon size={17} aria-hidden="true" />
        </span>
      </div>

      <div className="data-metric-card__value">
        {value}
        {unit && <span className="data-metric-card__unit">{unit}</span>}
      </div>

      <p>{description}</p>
    </article>
  );
}

function PanelHeader({
  eyebrow,
  title,
  description,
  icon: Icon,
  action,
  status,
}) {
  return (
    <div className="data-panel__header">
      <div className="data-panel__heading">
        {Icon && (
          <div className="data-panel__header-icon">
            <Icon size={18} aria-hidden="true" />
          </div>
        )}

        <div>
          <div className="data-panel__eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
          {description && <p>{description}</p>}
        </div>
      </div>

      {status && (
        <div
          className={`data-panel__status data-panel__status--${status.type}`}
          role="status"
          aria-live="polite"
        >
          {status.type === "loading" ? (
            <Activity size={14} aria-hidden="true" />
          ) : (
            <CheckCircle2 size={14} aria-hidden="true" />
          )}
          {status.label}
        </div>
      )}

      {action}
    </div>
  );
}

function PipelineStep({ number, icon: Icon, title, description }) {
  return (
    <article className="pipeline-step">
      <div className="pipeline-step__number">{number}</div>
      <div className="pipeline-step__icon">
        <Icon size={21} aria-hidden="true" />
      </div>
      <div className="pipeline-step__content">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
    </article>
  );
}

function PipelineConnector() {
  return (
    <div className="pipeline-connector" aria-hidden="true">
      <span />
      <ChevronRight size={16} />
    </div>
  );
}

function QualityMetric({
  icon: Icon,
  label,
  value,
  description,
  type = "success",
}) {
  return (
    <article className={`quality-metric quality-metric--${type}`}>
      <div className="quality-metric__icon">
        <Icon size={17} aria-hidden="true" />
      </div>

      <div className="quality-metric__content">
        <span className="quality-metric__label">{label}</span>
        <strong className="quality-metric__value">{value}</strong>
        <span className="quality-metric__description">{description}</span>
      </div>
    </article>
  );
}

function EmptyDataState() {
  return (
    <div className="data-empty" role="status" aria-live="polite">
      <div className="data-empty__icon">
        <Upload size={23} aria-hidden="true" />
      </div>

      <div>
        <h3>No energy data yet</h3>
        <p>
          Upload a smart-meter CSV or generate simulated ESP32 readings to
          begin analyzing household electricity consumption.
        </p>
      </div>
    </div>
  );
}