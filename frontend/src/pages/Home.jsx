import React, { useMemo } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  DollarSign,
  Gauge,
  Lightbulb,
  RefreshCw,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react";
import "./Home.css";

/* ============================================================================
   Formatting & Extraction Helpers
   ============================================================================ */

function formatNumber(value, decimals = 1) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return number.toLocaleString("en-CA", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatCurrency(value) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return number.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function getFirstNumber(object, keys, fallback = null) {
  if (!object || typeof object !== "object") {
    return fallback;
  }

  for (const key of keys) {
    const value = Number(object[key]);

    if (Number.isFinite(value)) {
      return value;
    }
  }

  return fallback;
}

function getRecommendationTitle(item) {
  if (!item || typeof item !== "object") {
    return "Energy opportunity";
  }

  return (
    item.title ||
    item.name ||
    item.recommendation ||
    item.description ||
    "Energy opportunity"
  );
}

function getRecommendationDescription(item) {
  if (!item || typeof item !== "object") {
    return "Review your energy usage for potential savings.";
  }

  return (
    item.description ||
    item.reason ||
    item.details ||
    "Review this opportunity to improve energy efficiency."
  );
}

function getRecommendationSavings(item) {
  if (!item || typeof item !== "object") {
    return null;
  }

  return getFirstNumber(
    item,
    [
      "savings",
      "estimatedSavings",
      "monthlySavings",
      "annualSavings",
      "potentialSavings",
    ],
    null
  );
}

/* ============================================================================
   Reusable Sub-Components
   ============================================================================ */

function MetricCard({
  icon: Icon,
  label,
  value,
  unit,
  description,
  trend,
  trendLabel,
  accent = "green",
}) {
  const hasTrend = typeof trend === "number" && Number.isFinite(trend);
  const trendIsPositive = hasTrend && trend > 0;
  const trendIsNegative = hasTrend && trend < 0;

  return (
    <article className={`home-metric-card home-metric-card--${accent}`}>
      <div className="home-metric-card__top">
        <div className="home-metric-card__icon" aria-hidden="true">
          <Icon size={19} strokeWidth={2} />
        </div>

        {hasTrend && (
          <span
            className={[
              "home-metric-card__trend",
              trendIsPositive ? "home-metric-card__trend--positive" : "",
              trendIsNegative ? "home-metric-card__trend--negative" : "",
              trend === 0 ? "home-metric-card__trend--neutral" : "",
            ]
              .filter(Boolean)
              .join(" ")}
          >
            {trendIsPositive ? (
              <TrendingUp
                size={13}
                strokeWidth={2.2}
                aria-hidden="true"
              />
            ) : trendIsNegative ? (
              <TrendingDown
                size={13}
                strokeWidth={2.2}
                aria-hidden="true"
              />
            ) : null}

            {Math.abs(trend).toFixed(1)}%
          </span>
        )}
      </div>

      <div className="home-metric-card__label">{label}</div>

      <div className="home-metric-card__value-row">
        <span className="home-metric-card__value">{value}</span>

        {unit && <span className="home-metric-card__unit">{unit}</span>}
      </div>

      <div className="home-metric-card__bottom">
        <span className="home-metric-card__description">
          {description}
        </span>

        {trendLabel && hasTrend && (
          <span className="home-metric-card__trend-label">
            {trendLabel}
          </span>
        )}
      </div>
    </article>
  );
}

function SectionHeading({ eyebrow, title, description, action }) {
  return (
    <div className="home-section-heading">
      <div className="home-section-heading__copy">
        <p className="home-section-kicker">{eyebrow}</p>
        <h2 className="home-section-title">{title}</h2>

        {description && (
          <p className="home-section-description">{description}</p>
        )}
      </div>

      {action}
    </div>
  );
}

/* ============================================================================
   Home Component
   ============================================================================ */

export default function Home({
  dashboard = {},
  analytics = {},
  recommendations = [],
  readings = [],
  refreshing = false,
  onRefresh,
  onNavigate,
}) {
  /* --------------------------------------------------------------------------
     Dashboard & Analytics Metrics
     -------------------------------------------------------------------------- */

  const metrics = useMemo(() => {
    const totalEnergy = getFirstNumber(dashboard, [
      "totalEnergy",
      "total_energy",
      "energy",
      "energyConsumption",
      "consumption",
      "kwh",
      "totalKwh",
    ]);

    const totalCost = getFirstNumber(dashboard, [
      "totalCost",
      "total_cost",
      "cost",
      "energyCost",
      "monthlyCost",
    ]);

    const savings = getFirstNumber(dashboard, [
      "savings",
      "estimatedSavings",
      "potentialSavings",
      "monthlySavings",
    ]);

    const peakDemand = getFirstNumber(dashboard, [
      "peakDemand",
      "peak_demand",
      "maxDemand",
      "demand",
      "peakKw",
    ]);

    const energyTrend = getFirstNumber(dashboard, [
      "energyTrend",
      "energyChange",
      "consumptionChange",
      "changePercent",
    ]);

    const costTrend = getFirstNumber(dashboard, [
      "costTrend",
      "costChange",
      "costChangePercent",
    ]);

    const averageEnergy = getFirstNumber(analytics, [
      "averageEnergy",
      "average_energy",
      "avgEnergy",
      "averageConsumption",
      "avgConsumption",
    ]);

    const peakHour = getFirstNumber(analytics, ["peakHour", "peak_hour"]);

    return {
      totalEnergy,
      totalCost,
      savings,
      peakDemand,
      energyTrend,
      costTrend,
      averageEnergy,
      peakHour,
    };
  }, [dashboard, analytics]);

  /* --------------------------------------------------------------------------
     Readings Processing & Fallbacks
     -------------------------------------------------------------------------- */

  const readingAnalysis = useMemo(() => {
    const readingValues = Array.isArray(readings)
      ? readings
          .map((reading) =>
            getFirstNumber(reading, [
              "energy",
              "energyConsumption",
              "consumption",
              "kwh",
              "value",
              "energy_kwh",
              "usage_kwh",
            ])
          )
          .filter((value) => Number.isFinite(value))
      : [];

    const recentReadingValues = readingValues.slice(-12);

    const calculatedAverage =
      readingValues.length > 0
        ? readingValues.reduce((sum, value) => sum + value, 0) /
          readingValues.length
        : null;

    const displayAverage = metrics.averageEnergy ?? calculatedAverage;

    const chartMax =
      recentReadingValues.length > 0
        ? Math.max(...recentReadingValues, 1)
        : 1;

    const chartAverage =
      recentReadingValues.length > 0
        ? recentReadingValues.reduce((sum, value) => sum + value, 0) /
          recentReadingValues.length
        : null;

    return {
      readingValues,
      recentReadingValues,
      displayAverage,
      chartMax,
      chartAverage,
      hasData: readingValues.length > 0,
    };
  }, [readings, metrics.averageEnergy]);

  /* --------------------------------------------------------------------------
     Recommendations Processing
     -------------------------------------------------------------------------- */

  const recommendationAnalysis = useMemo(() => {
    const topRecommendations = Array.isArray(recommendations)
      ? recommendations.slice(0, 3)
      : [];

    const savingsList = topRecommendations
      .map(getRecommendationSavings)
      .filter((value) => value !== null);

    const totalOpportunityValue =
      savingsList.length > 0
        ? savingsList.reduce((sum, value) => sum + value, 0)
        : null;

    return {
      topRecommendations,
      totalOpportunityValue,
    };
  }, [recommendations]);

  /* --------------------------------------------------------------------------
     Display Formatting
     -------------------------------------------------------------------------- */

  const peakHourLabel = useMemo(() => {
    if (metrics.peakHour === null) return "—";

    const hour = Math.round(metrics.peakHour);

    if (hour < 0 || hour > 23) {
      return "—";
    }

    const suffix = hour >= 12 ? "PM" : "AM";
    const displayHour = hour % 12 || 12;

    return `${displayHour}:00 ${suffix}`;
  }, [metrics.peakHour]);

  const energyValue =
    metrics.totalEnergy !== null ? formatNumber(metrics.totalEnergy) : "—";
  const costValue =
    metrics.totalCost !== null ? formatCurrency(metrics.totalCost) : "—";
  const savingsValue =
    metrics.savings !== null ? formatCurrency(metrics.savings) : "—";
  const demandValue =
    metrics.peakDemand !== null ? formatNumber(metrics.peakDemand) : "—";

  return (
    <main className="home-page" aria-labelledby="home-page-title">
      {/* ====================================================================
          HERO
          ==================================================================== */}

      <section className="home-hero">
        <div className="home-hero__glow home-hero__glow--one" />
        <div className="home-hero__glow home-hero__glow--two" />

        <div className="home-hero__content">
          <div className="home-eyebrow">
            <span
              className="home-eyebrow__dot"
              aria-hidden="true"
            />
            ENERGY INTELLIGENCE PLATFORM
          </div>

          <h1 id="home-page-title" className="home-title">
            Understand your energy.
            <span> Reduce your costs.</span>
          </h1>

          <p className="home-subtitle">
            EnergyPilot turns electricity data into clear, actionable
            intelligence — helping you understand consumption, uncover
            inefficiencies, and identify opportunities to save.
          </p>

          <div className="home-hero__actions">
            <button
              type="button"
              className="home-button home-button--primary"
              onClick={() => onNavigate?.("analytics")}
            >
              <BarChart3
                size={17}
                strokeWidth={2}
                aria-hidden="true"
              />
              Explore analytics
              <ArrowRight
                size={16}
                strokeWidth={2}
                aria-hidden="true"
              />
            </button>

            <button
              type="button"
              className="home-button home-button--secondary"
              onClick={() => onNavigate?.("recommendations")}
            >
              <Lightbulb
                size={16}
                strokeWidth={2}
                aria-hidden="true"
              />
              Find savings
            </button>
          </div>

          <div className="home-hero__meta">
            <span>
              <CheckCircle2 size={14} aria-hidden="true" />
              Data-driven insights
            </span>

            <span>
              <Zap size={14} aria-hidden="true" />
              Smart-meter ready
            </span>
          </div>
        </div>

        <div className="home-hero__visual">
          <div className="home-hero__visual-orbit home-hero__visual-orbit--outer" />
          <div className="home-hero__visual-orbit home-hero__visual-orbit--inner" />

          <div className="home-hero__orb">
            <div className="home-hero__orb-ring">
              <Zap
                size={39}
                strokeWidth={1.6}
                aria-hidden="true"
              />
            </div>
          </div>

          <div className="home-hero__floating-card home-hero__floating-card--top">
            <span className="home-hero__floating-label">
              CURRENT STATUS
            </span>

            <strong>
              {readingAnalysis.hasData ? "Monitoring" : "Ready"}
            </strong>

            <span className="home-hero__floating-status">
              <span aria-hidden="true" />
              {readingAnalysis.hasData
                ? "Energy data connected"
                : "Awaiting energy data"}
            </span>
          </div>

          <div className="home-hero__floating-card home-hero__floating-card--bottom">
            <span className="home-hero__floating-label">
              PERIOD CHANGE
            </span>

            <strong>
              {metrics.energyTrend !== null
                ? `${Math.abs(metrics.energyTrend).toFixed(1)}%`
                : "—"}
            </strong>

            <span>
              {metrics.energyTrend !== null
                ? metrics.energyTrend < 0
                  ? "lower energy use"
                  : "change in energy use"
                : "connect data to calculate"}
            </span>
          </div>
        </div>
      </section>

      {/* ====================================================================
          KPI SECTION
          ==================================================================== */}

      <section
        className="home-section"
        aria-labelledby="performance-title"
      >
        <SectionHeading
          eyebrow="AT A GLANCE"
          title="Energy performance"
          description="A concise view of your current energy profile."
          action={
            <button
              type="button"
              className="home-refresh-button"
              onClick={onRefresh}
              disabled={refreshing}
              title="Refresh energy data"
              aria-label={
                refreshing
                  ? "Updating energy data"
                  : "Refresh energy data"
              }
            >
              <RefreshCw
                size={16}
                strokeWidth={2}
                className={
                  refreshing ? "home-refresh-button__icon--spinning" : ""
                }
                aria-hidden="true"
              />
              <span>{refreshing ? "Updating" : "Refresh"}</span>
            </button>
          }
        />

        <div className="home-metrics-grid">
          <MetricCard
            icon={Zap}
            label="Energy consumption"
            value={energyValue}
            unit="kWh"
            description="Total monitored usage"
            trend={metrics.energyTrend}
            trendLabel="vs. previous period"
            accent="green"
          />

          <MetricCard
            icon={DollarSign}
            label="Energy cost"
            value={costValue}
            description="Estimated energy spend"
            trend={metrics.costTrend}
            trendLabel="vs. previous period"
            accent="teal"
          />

          <MetricCard
            icon={Lightbulb}
            label="Potential savings"
            value={savingsValue}
            description="Identified opportunities"
            accent="lime"
          />

          <MetricCard
            icon={Gauge}
            label="Peak demand"
            value={demandValue}
            unit="kW"
            description="Highest observed demand"
            accent="slate"
          />
        </div>
      </section>

      {/* ====================================================================
          DASHBOARD OVERVIEW
          ==================================================================== */}

      <section
        className="home-dashboard-grid"
        aria-label="Energy dashboard overview"
      >
        {/* Consumption Overview */}
        <article className="home-panel home-consumption-panel">
          <div className="home-panel-header">
            <div>
              <p className="home-panel-kicker">CONSUMPTION</p>

              <h2 className="home-panel-title">Usage overview</h2>

              <p className="home-panel-description">
                Recent readings reveal how your electricity usage is changing
                over time.
              </p>
            </div>

            <button
              type="button"
              className="home-panel-link"
              onClick={() => onNavigate?.("analytics")}
            >
              View details
              <ArrowRight
                size={14}
                strokeWidth={2}
                aria-hidden="true"
              />
            </button>
          </div>

          <div className="home-consumption-content">
            <div className="home-consumption-summary">
              <div className="home-consumption-summary__icon">
                <Activity
                  size={18}
                  strokeWidth={2}
                  aria-hidden="true"
                />
              </div>

              <div>
                <span className="home-consumption-label">
                  Average usage
                </span>

                <div className="home-consumption-value-row">
                  <strong className="home-consumption-value">
                    {readingAnalysis.displayAverage !== null
                      ? formatNumber(readingAnalysis.displayAverage)
                      : "—"}
                  </strong>

                  <span className="home-consumption-unit">
                    kWh / reading
                  </span>
                </div>
              </div>

              {readingAnalysis.chartAverage !== null && (
                <span className="home-consumption-average">
                  Recent avg&nbsp;
                  {formatNumber(readingAnalysis.chartAverage)} kWh
                </span>
              )}
            </div>

            <div
              className="home-chart"
              aria-label="Recent energy consumption trend"
            >
              <div className="home-chart__grid" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
              </div>

              {readingAnalysis.recentReadingValues.length > 1 ? (
                <>
                  <div className="home-chart__bars">
                    {readingAnalysis.recentReadingValues.map(
                      (value, index, values) => {
                        const height = Math.max(
                          10,
                          (value / readingAnalysis.chartMax) * 100
                        );

                        const isLatest = index === values.length - 1;
                        const isHighest = value === Math.max(...values);

                        return (
                          <div
                            key={`${value}-${index}`}
                            className={[
                              "home-chart__bar-column",
                              isLatest
                                ? "home-chart__bar-column--latest"
                                : "",
                              isHighest
                                ? "home-chart__bar-column--highest"
                                : "",
                            ]
                              .filter(Boolean)
                              .join(" ")}
                            title={`${formatNumber(value)} kWh`}
                          >
                            <div className="home-chart__tooltip">
                              {formatNumber(value)} kWh
                            </div>

                            <div
                              className="home-chart__bar"
                              style={{ height: `${height}%` }}
                            />
                          </div>
                        );
                      }
                    )}
                  </div>

                  <div
                    className="home-chart__axis"
                    aria-hidden="true"
                  >
                    <span>Older</span>
                    <span>Recent</span>
                  </div>
                </>
              ) : (
                <div className="home-chart-empty">
                  <div className="home-chart-empty__icon">
                    <Activity
                      size={22}
                      strokeWidth={1.7}
                      aria-hidden="true"
                    />
                  </div>

                  <div>
                    <strong>Waiting for more readings</strong>

                    <span>
                      Add at least two readings to visualize the consumption
                      trend.
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </article>

        {/* Current Profile Snapshot */}
        <article className="home-panel home-snapshot-panel">
          <div className="home-panel-header">
            <div>
              <p className="home-panel-kicker">SNAPSHOT</p>

              <h2 className="home-panel-title">Current profile</h2>

              <p className="home-panel-description">
                Key signals from the data currently available.
              </p>
            </div>
          </div>

          <div className="home-snapshot-list">
            <div className="home-snapshot-item">
              <div className="home-snapshot-icon">
                <Zap
                  size={16}
                  strokeWidth={2}
                  aria-hidden="true"
                />
              </div>

              <div className="home-snapshot-copy">
                <span>Average consumption</span>
                <strong>
                  {readingAnalysis.displayAverage !== null
                    ? `${formatNumber(readingAnalysis.displayAverage)} kWh`
                    : "—"}
                </strong>
              </div>
            </div>

            <div className="home-snapshot-item">
              <div className="home-snapshot-icon">
                <Gauge
                  size={16}
                  strokeWidth={2}
                  aria-hidden="true"
                />
              </div>

              <div className="home-snapshot-copy">
                <span>Peak demand</span>
                <strong>
                  {metrics.peakDemand !== null
                    ? `${formatNumber(metrics.peakDemand)} kW`
                    : "—"}
                </strong>
              </div>
            </div>

            <div className="home-snapshot-item">
              <div className="home-snapshot-icon">
                <Activity
                  size={16}
                  strokeWidth={2}
                  aria-hidden="true"
                />
              </div>

              <div className="home-snapshot-copy">
                <span>Peak hour</span>
                <strong>{peakHourLabel}</strong>
              </div>
            </div>

            <div className="home-snapshot-item">
              <div className="home-snapshot-icon">
                <Lightbulb
                  size={16}
                  strokeWidth={2}
                  aria-hidden="true"
                />
              </div>

              <div className="home-snapshot-copy">
                <span>Opportunities</span>
                <strong>{recommendations.length}</strong>
              </div>
            </div>
          </div>

          <div className="home-snapshot-footer">
            <span className="home-snapshot-footer__indicator">
              <span aria-hidden="true" />
              {readingAnalysis.hasData
                ? "Monitoring active"
                : "No readings loaded"}
            </span>

            <span>
              {readings.length > 0
                ? `${readings.length.toLocaleString("en-CA")} data points`
                : "Connect a data source"}
            </span>
          </div>
        </article>
      </section>

      {/* ====================================================================
          SAVINGS OPPORTUNITIES
          ==================================================================== */}

      <section
        className="home-section home-savings-section"
        aria-labelledby="savings-title"
      >
        <SectionHeading
          eyebrow="AI INSIGHTS"
          title="Savings opportunities"
          description="Potential improvements surfaced from your energy profile."
          action={
            <button
              type="button"
              className="home-panel-link"
              onClick={() => onNavigate?.("recommendations")}
            >
              View all
              <ArrowRight
                size={14}
                strokeWidth={2}
                aria-hidden="true"
              />
            </button>
          }
        />

        {recommendationAnalysis.topRecommendations.length > 0 ? (
          <>
            <div className="home-recommendations-grid">
              {recommendationAnalysis.topRecommendations.map(
                (recommendation, index) => {
                  const title = getRecommendationTitle(recommendation);
                  const description =
                    getRecommendationDescription(recommendation);
                  const recSavings =
                    getRecommendationSavings(recommendation);

                  const key =
                    recommendation?.id ??
                    recommendation?.uuid ??
                    `${title.toLowerCase().replace(/\s+/g, "-")}-${index}`;

                  return (
                    <article
                      key={key}
                      className="home-recommendation-card"
                      onClick={() => onNavigate?.("recommendations")}
                      role="button"
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onNavigate?.("recommendations");
                        }
                      }}
                    >
                      <div className="home-recommendation-card__top">
                        <div className="home-recommendation-icon">
                          <Lightbulb
                            size={18}
                            strokeWidth={2}
                            aria-hidden="true"
                          />
                        </div>

                        <span className="home-recommendation-index">
                          0{index + 1}
                        </span>
                      </div>

                      <div className="home-recommendation-content">
                        <h3>{title}</h3>
                        <p>{description}</p>
                      </div>

                      <div className="home-recommendation-card__footer">
                        {recSavings !== null ? (
                          <div className="home-recommendation-savings">
                            <span>Potential savings</span>
                            <strong>{formatCurrency(recSavings)}</strong>
                          </div>
                        ) : (
                          <span className="home-recommendation-action">
                            Review opportunity
                          </span>
                        )}

                        <span className="home-recommendation-arrow">
                          <ArrowRight
                            size={16}
                            strokeWidth={1.9}
                            aria-hidden="true"
                          />
                        </span>
                      </div>
                    </article>
                  );
                }
              )}
            </div>

            {recommendationAnalysis.totalOpportunityValue !== null && (
              <div className="home-savings-summary">
                <div className="home-savings-summary__icon">
                  <DollarSign
                    size={18}
                    strokeWidth={2}
                    aria-hidden="true"
                  />
                </div>

                <div>
                  <span>Combined opportunity value</span>

                  <strong>
                    {formatCurrency(
                      recommendationAnalysis.totalOpportunityValue
                    )}
                  </strong>
                </div>

                <button
                  type="button"
                  onClick={() => onNavigate?.("recommendations")}
                >
                  Explore opportunities
                  <ArrowRight size={15} aria-hidden="true" />
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="home-empty-state">
            <div className="home-empty-icon">
              <Lightbulb
                size={22}
                strokeWidth={1.7}
                aria-hidden="true"
              />
            </div>

            <div className="home-empty-state__copy">
              <h3>No recommendations yet</h3>

              <p>
                Once EnergyPilot analyzes your energy data, potential savings
                opportunities will appear here.
              </p>
            </div>

            <button
              type="button"
              onClick={() => onNavigate?.("data")}
            >
              Add data
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          </div>
        )}
      </section>

      {/* ====================================================================
          QUICK ACTIONS
          ==================================================================== */}

      <section
        className="home-quick-actions"
        aria-label="Quick actions"
      >
        <button
          type="button"
          className="home-quick-action"
          onClick={() => onNavigate?.("analytics")}
        >
          <span className="home-quick-action__icon">
            <BarChart3
              size={19}
              strokeWidth={2}
              aria-hidden="true"
            />
          </span>

          <span className="home-quick-action__copy">
            <strong>Explore analytics</strong>
            <span>Understand consumption patterns</span>
          </span>

          <ArrowRight
            size={17}
            strokeWidth={1.8}
            aria-hidden="true"
          />
        </button>

        <button
          type="button"
          className="home-quick-action"
          onClick={() => onNavigate?.("data")}
        >
          <span className="home-quick-action__icon">
            <Activity
              size={19}
              strokeWidth={2}
              aria-hidden="true"
            />
          </span>

          <span className="home-quick-action__copy">
            <strong>Manage your data</strong>
            <span>Review readings and upload data</span>
          </span>

          <ArrowRight
            size={17}
            strokeWidth={1.8}
            aria-hidden="true"
          />
        </button>

        <button
          type="button"
          className="home-quick-action"
          onClick={() => onNavigate?.("recommendations")}
        >
          <span className="home-quick-action__icon">
            <Lightbulb
              size={19}
              strokeWidth={2}
              aria-hidden="true"
            />
          </span>

          <span className="home-quick-action__copy">
            <strong>Find savings</strong>
            <span>See AI-generated opportunities</span>
          </span>

          <ArrowRight
            size={17}
            strokeWidth={1.8}
            aria-hidden="true"
          />
        </button>
      </section>
    </main>
  );
}