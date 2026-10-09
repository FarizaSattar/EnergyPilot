import React, { useMemo, useState } from "react";
import {
  ArrowDownRight,
  ArrowRight,
  Calculator,
  CalendarDays,
  CheckCircle2,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  DollarSign,
  Gauge,
  Info,
  Lightbulb,
  PiggyBank,
  SlidersHorizontal,
  Sparkles,
  Target,
  TrendingDown,
  Zap,
} from "lucide-react";
import "./Savings.css";

/* ==========================================================================
   Formatters & Utility Helpers
   ========================================================================== */

function formatNumber(value, decimals = 1) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return number.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function formatCurrency(value, decimals = 2) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return number.toLocaleString("en-CA", {
    style: "currency",
    currency: "CAD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
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
    return "Energy optimization opportunity";
  }

  return (
    item.title ||
    item.name ||
    item.recommendation ||
    item.description ||
    "Energy optimization opportunity"
  );
}

function getRecommendationDescription(item) {
  if (!item || typeof item !== "object") {
    return "Review your energy usage to identify opportunities for lower consumption and cost.";
  }

  return (
    item.description ||
    item.reason ||
    item.details ||
    item.explanation ||
    "Review this opportunity to reduce energy consumption and operating costs."
  );
}

function getRecommendationSavings(item) {
  return getFirstNumber(item, [
    "savings",
    "estimatedSavings",
    "monthlySavings",
    "annualSavings",
    "potentialSavings",
    "estimated_savings",
    "monthly_savings",
    "annual_savings",
  ]);
}

function formatHour(value) {
  const number = Number(value);

  if (!Number.isFinite(number) || number < 0 || number > 23) {
    return "—";
  }

  const hour = Math.round(number) % 24;
  const suffix = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 || 12;

  return `${displayHour} ${suffix}`;
}

/* ==========================================================================
   Sub-Components
   ========================================================================== */

function SavingsStat({
  icon: Icon,
  label,
  value,
  detail,
  tone = "green",
}) {
  return (
    <article className={`savings-stat-card savings-stat-card--${tone}`}>
      <div className="savings-stat-icon">
        <Icon size={20} strokeWidth={2} />
      </div>

      <div className="savings-stat-content">
        <span className="savings-stat-label">{label}</span>
        <strong className="savings-stat-value">{value}</strong>
        {detail && <span className="savings-stat-detail">{detail}</span>}
      </div>
    </article>
  );
}

function OpportunityCard({ item, index, onNavigate }) {
  const title = getRecommendationTitle(item);
  const description = getRecommendationDescription(item);
  const savings = getRecommendationSavings(item);

  return (
    <article className="savings-opportunity-card">
      <div className="savings-opportunity-number">
        {String(index + 1).padStart(2, "0")}
      </div>

      <div className="savings-opportunity-main">
        <div className="savings-opportunity-heading">
          <div className="savings-opportunity-icon">
            <Lightbulb size={19} strokeWidth={2} />
          </div>

          {savings !== null && (
            <span className="savings-opportunity-badge">
              <CircleDollarSign size={14} />
              {formatCurrency(savings)}
            </span>
          )}
        </div>

        <h3>{title}</h3>
        <p>{description}</p>

        <button
          type="button"
          className="savings-opportunity-action"
          onClick={() => onNavigate?.("recommendations")}
        >
          View recommendation
          <ArrowRight size={16} />
        </button>
      </div>
    </article>
  );
}

/* ==========================================================================
   Main Savings Dashboard Component
   ========================================================================== */

export default function Savings({
  dashboard = {},
  analytics = {},
  recommendations = [],
  readings = [],
  onNavigate,
}) {
  const [selectedBreakdownTab, setSelectedBreakdownTab] = useState("all");
  const [investmentInput, setInvestmentInput] = useState(250);

  const recommendationList = useMemo(
    () => (Array.isArray(recommendations) ? recommendations : []),
    [recommendations]
  );

  const readingList = useMemo(
    () => (Array.isArray(readings) ? readings : []),
    [readings]
  );

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
      "annualSavings",
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

    const peakHour = getFirstNumber(analytics, [
      "peakHour",
      "peak_hour",
    ]);

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

  const readingValues = useMemo(() => {
    return readingList
      .map((reading) =>
        getFirstNumber(reading, [
          "energy",
          "energyConsumption",
          "consumption",
          "kwh",
          "value",
        ])
      )
      .filter((value) => value !== null);
  }, [readingList]);

  const projectedSavings = useMemo(() => {
    if (metrics.savings !== null) {
      return metrics.savings;
    }

    const recommendationSavings = recommendationList
      .map(getRecommendationSavings)
      .filter((value) => value !== null);

    if (!recommendationSavings.length) {
      return null;
    }

    return recommendationSavings.reduce((total, value) => total + value, 0);
  }, [metrics.savings, recommendationList]);

  const annualizedSavings = useMemo(() => {
    if (projectedSavings === null) {
      return null;
    }
    return projectedSavings * 12;
  }, [projectedSavings]);

  const savingsRate = useMemo(() => {
    if (
      projectedSavings === null ||
      metrics.totalCost === null ||
      metrics.totalCost <= 0
    ) {
      return null;
    }

    return Math.min(
      100,
      Math.max(0, (projectedSavings / metrics.totalCost) * 100)
    );
  }, [projectedSavings, metrics.totalCost]);

  // Charting Data calculations
  const chartValues = useMemo(() => {
    return readingValues.slice(-12);
  }, [readingValues]);

  const chartMax = useMemo(() => {
    if (!chartValues.length) return 0;
    return Math.max(...chartValues, 0);
  }, [chartValues]);

  const chartMin = useMemo(() => {
    if (!chartValues.length) return 0;
    return Math.min(...chartValues);
  }, [chartValues]);

  const chartAverage = useMemo(() => {
    if (!chartValues.length) return null;
    return (
      chartValues.reduce((total, value) => total + value, 0) /
      chartValues.length
    );
  }, [chartValues]);

  const averagePosition = useMemo(() => {
    if (!chartMax || chartAverage === null) return null;
    return Math.min(92, Math.max(8, (chartAverage / chartMax) * 100));
  }, [chartAverage, chartMax]);

  const maxChartValue = useMemo(() => {
    if (!chartValues.length) return null;
    return Math.max(...chartValues);
  }, [chartValues]);

  // ROI / Simulator Calculations
  const calculatedSimulatorRoi = useMemo(() => {
    const annual = annualizedSavings ?? 0;
    const inv = Number(investmentInput) || 1;
    if (annual <= 0) return { roi: 0, paybackMonths: 0 };

    const roi = (annual / inv) * 100;
    const paybackMonths = (inv / (annual / 12));
    return {
      roi: Math.round(roi),
      paybackMonths: Number.isFinite(paybackMonths) ? paybackMonths.toFixed(1) : "—",
    };
  }, [annualizedSavings, investmentInput]);

  const topRecommendations = recommendationList.slice(0, 3);
  const hasSavingsData = projectedSavings !== null || recommendationList.length > 0;

  return (
    <main className="savings-page">
      {/* =========================================================
          HERO SECTION
      ========================================================= */}
      <section className="savings-hero">
        <div className="savings-hero-background" />

        <div className="savings-hero-copy">
          <div className="savings-eyebrow">
            <span className="savings-eyebrow-dot" />
            SAVINGS ENGINE
          </div>

          <h1>
            Turn energy data into
            <span> real savings.</span>
          </h1>

          <p>
            See where your energy budget is going, uncover the biggest
            opportunities, and prioritize changes that lower your operating costs.
          </p>

          <div className="savings-hero-actions">
            <button
              type="button"
              className="savings-button savings-button--primary"
              onClick={() => onNavigate?.("recommendations")}
            >
              <Sparkles size={17} />
              Explore opportunities
              <ArrowRight size={17} />
            </button>

            <button
              type="button"
              className="savings-button savings-button--secondary"
              onClick={() => onNavigate?.("analytics")}
            >
              <TrendingDown size={17} />
              Analyze usage
            </button>
          </div>
        </div>

        <div className="savings-hero-visual">
          <div className="savings-orbit savings-orbit--outer" />
          <div className="savings-orbit savings-orbit--inner" />
          <div className="savings-hero-glow" />

          <div className="savings-hero-card">
            <div className="savings-hero-card-top">
              <div className="savings-hero-icon">
                <PiggyBank size={22} />
              </div>

              <span className="savings-live-badge">
                <span />
                OPTIMIZATION
              </span>
            </div>

            <span className="savings-hero-card-label">ESTIMATED SAVINGS</span>

            <strong className="savings-hero-card-value">
              {projectedSavings !== null
                ? formatCurrency(projectedSavings)
                : "—"}
            </strong>

            <div className="savings-hero-card-divider" />

            <div className="savings-hero-mini-grid">
              <div>
                <span>Annualized</span>
                <strong>
                  {annualizedSavings !== null
                    ? formatCurrency(annualizedSavings)
                    : "—"}
                </strong>
              </div>

              <div>
                <span>Opportunities</span>
                <strong>{recommendationList.length}</strong>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* =========================================================
          SUMMARY KPI GRID
      ========================================================= */}
      <section
        className="savings-section"
        aria-labelledby="savings-summary-heading"
      >
        <div className="savings-section-heading">
          <div>
            <span className="savings-section-kicker">AT A GLANCE</span>
            <h2 id="savings-summary-heading">Your savings potential</h2>
            <p>
              A quick view of the financial impact available from your current
              energy profile.
            </p>
          </div>

          <div className="savings-period">
            <CalendarDays size={16} />
            <span>Current period</span>
          </div>
        </div>

        <div className="savings-stats-grid">
          <SavingsStat
            icon={PiggyBank}
            label="Potential savings"
            value={
              projectedSavings !== null
                ? formatCurrency(projectedSavings)
                : "—"
            }
            detail="Estimated monthly opportunity"
            tone="green"
          />

          <SavingsStat
            icon={TrendingDown}
            label="Annualized impact"
            value={
              annualizedSavings !== null
                ? formatCurrency(annualizedSavings)
                : "—"
            }
            detail="If savings repeat monthly"
            tone="lime"
          />

          <SavingsStat
            icon={Target}
            label="Savings rate"
            value={
              savingsRate !== null
                ? `${formatNumber(savingsRate, 1)}%`
                : "—"
            }
            detail="Relative to current cost"
            tone="teal"
          />

          <SavingsStat
            icon={Lightbulb}
            label="Opportunities"
            value={recommendationList.length}
            detail="Optimization recommendations"
            tone="gold"
          />
        </div>
      </section>

      {/* =========================================================
          SAVINGS PROFILE & USAGE TREND
      ========================================================= */}
      <section className="savings-main-grid">
        {/* Savings Profile Card */}
        <article className="savings-panel savings-profile-panel">
          <div className="savings-panel-heading">
            <div>
              <span className="savings-panel-kicker">SAVINGS PROFILE</span>
              <h2>Where the opportunity stands</h2>
            </div>

            <div className="savings-panel-icon">
              <Gauge size={19} />
            </div>
          </div>

          <div className="savings-profile-content">
            <div className="savings-profile-primary">
              <span>Current energy cost</span>
              <strong>
                {metrics.totalCost !== null
                  ? formatCurrency(metrics.totalCost)
                  : "—"}
              </strong>

              {metrics.costTrend !== null && (
                <div
                  className={`savings-trend ${
                    metrics.costTrend <= 0
                      ? "savings-trend--good"
                      : "savings-trend--warning"
                  }`}
                >
                  <ArrowDownRight
                    size={15}
                    className={
                      metrics.costTrend > 0 ? "savings-trend-arrow-up" : ""
                    }
                  />
                  {formatNumber(Math.abs(metrics.costTrend), 1)}%
                  <span>
                    {metrics.costTrend <= 0
                      ? "lower than previous period"
                      : "higher than previous period"}
                  </span>
                </div>
              )}
            </div>

            <div className="savings-progress-block">
              <div className="savings-progress-header">
                <span>Potential reduction</span>
                <strong>
                  {savingsRate !== null
                    ? `${formatNumber(savingsRate, 1)}%`
                    : "—"}
                </strong>
              </div>

              <div
                className="savings-progress-track"
                role="progressbar"
                aria-valuemin="0"
                aria-valuemax="100"
                aria-valuenow={savingsRate ?? 0}
              >
                <div
                  className="savings-progress-fill"
                  style={{
                    width: `${savingsRate ?? 0}%`,
                  }}
                />
              </div>

              <div className="savings-progress-labels">
                <span>Current spend</span>
                <span>Optimization potential</span>
              </div>
            </div>

            <div className="savings-profile-details">
              <div className="savings-detail-row">
                <div className="savings-detail-icon">
                  <Zap size={16} />
                </div>
                <div>
                  <span>Energy consumption</span>
                  <strong>
                    {metrics.totalEnergy !== null
                      ? `${formatNumber(metrics.totalEnergy)} kWh`
                      : "—"}
                  </strong>
                </div>
              </div>

              <div className="savings-detail-row">
                <div className="savings-detail-icon">
                  <Gauge size={16} />
                </div>
                <div>
                  <span>Peak demand</span>
                  <strong>
                    {metrics.peakDemand !== null
                      ? `${formatNumber(metrics.peakDemand)} kW`
                      : "—"}
                  </strong>
                </div>
              </div>

              <div className="savings-detail-row">
                <div className="savings-detail-icon">
                  <Clock3 size={16} />
                </div>
                <div>
                  <span>Peak usage hour</span>
                  <strong>{formatHour(metrics.peakHour)}</strong>
                </div>
              </div>
            </div>
          </div>
        </article>

        {/* Usage Trend Chart Panel */}
        <article className="savings-panel savings-chart-panel">
          <div className="savings-panel-heading">
            <div>
              <span className="savings-panel-kicker">USAGE SIGNAL</span>
              <h2>Consumption trend</h2>
            </div>

            <div className="savings-chart-summary">
              <span>Average</span>
              <strong>
                {chartAverage !== null
                  ? `${formatNumber(chartAverage)} kWh`
                  : "—"}
              </strong>
            </div>
          </div>

          {chartValues.length >= 2 ? (
            <>
              <div
                className="savings-chart"
                role="img"
                aria-label="Recent energy consumption trend bar chart"
              >
                <div className="savings-chart-grid">
                  <span />
                  <span />
                  <span />
                  <span />
                </div>

                {averagePosition !== null && (
                  <div
                    className="savings-chart-average"
                    style={{
                      bottom: `${averagePosition}%`,
                    }}
                  >
                    <span>AVG</span>
                  </div>
                )}

                <div className="savings-bars">
                  {chartValues.map((value, index) => {
                    const height =
                      chartMax > 0
                        ? Math.max(8, (value / chartMax) * 100)
                        : 8;

                    const isPeak = value === maxChartValue;
                    const isLatest = index === chartValues.length - 1;

                    return (
                      <div
                        className={`savings-bar-column ${
                          isPeak ? "is-peak" : ""
                        } ${isLatest ? "is-latest" : ""}`}
                        key={`${value}-${index}`}
                        title={`${formatNumber(value)} kWh`}
                      >
                        {isPeak && (
                          <span className="savings-bar-label">Peak</span>
                        )}

                        <div
                          className="savings-bar"
                          style={{
                            height: `${height}%`,
                          }}
                        />
                      </div>
                    );
                  })}
                </div>
              </div>

              <div className="savings-chart-footer">
                <span>{formatNumber(chartMin)} kWh min</span>
                <span>{formatNumber(chartMax)} kWh max</span>
              </div>
            </>
          ) : (
            <div className="savings-empty-chart">
              <div className="savings-empty-icon">
                <TrendingDown size={22} />
              </div>

              <strong>Not enough usage data yet</strong>

              <p>
                Add more readings to identify consumption patterns and
                calculate stronger savings opportunities.
              </p>

              <button
                type="button"
                onClick={() => onNavigate?.("data")}
                className="savings-text-button"
              >
                View data
                <ArrowRight size={15} />
              </button>
            </div>
          )}
        </article>
      </section>

      {/* =========================================================
          INTERACTIVE SIMULATOR / ROI CALCULATOR
      ========================================================= */}
      <section className="savings-section">
        <article className="savings-panel savings-simulator-panel">
          <div className="savings-panel-heading">
            <div>
              <span className="savings-panel-kicker">ROI SIMULATOR</span>
              <h2>Implementation & Payback Estimator</h2>
              <p>
                Estimate your return on investment based on potential upfront
                implementation costs.
              </p>
            </div>
            <div className="savings-panel-icon">
              <Calculator size={20} />
            </div>
          </div>

          <div className="savings-simulator-content">
            <div className="savings-simulator-controls">
              <div className="savings-simulator-field">
                <label htmlFor="investment-range">
                  <span>Upfront Implementation Budget:</span>
                  <strong>{formatCurrency(investmentInput, 0)}</strong>
                </label>
                <input
                  id="investment-range"
                  type="range"
                  min="0"
                  max="5000"
                  step="50"
                  value={investmentInput}
                  onChange={(e) => setInvestmentInput(Number(e.target.value))}
                  className="savings-slider"
                />
                <div className="savings-slider-ticks">
                  <span>$0 (No Cost)</span>
                  <span>$2,500</span>
                  <span>$5,000+</span>
                </div>
              </div>
            </div>

            <div className="savings-simulator-results">
              <div className="savings-sim-card">
                <span>Annualized Savings</span>
                <strong>
                  {annualizedSavings !== null
                    ? formatCurrency(annualizedSavings)
                    : "—"}
                </strong>
              </div>

              <div className="savings-sim-card">
                <span>Estimated Payback</span>
                <strong>
                  {calculatedSimulatorRoi.paybackMonths === "0.0" || Number(investmentInput) === 0
                    ? "Immediate"
                    : `${calculatedSimulatorRoi.paybackMonths} months`}
                </strong>
              </div>

              <div className="savings-sim-card highlight">
                <span>1-Year ROI</span>
                <strong>{calculatedSimulatorRoi.roi}%</strong>
              </div>
            </div>
          </div>
        </article>
      </section>

      {/* =========================================================
          RECOMMENDED OPPORTUNITIES
      ========================================================= */}
      <section
        className="savings-section savings-opportunities-section"
        aria-labelledby="savings-opportunities-heading"
      >
        <div className="savings-section-heading">
          <div>
            <span className="savings-section-kicker">RECOMMENDED ACTIONS</span>
            <h2 id="savings-opportunities-heading">
              Highest-value opportunities
            </h2>
            <p>
              Prioritized recommendations based on your energy usage and
              available savings potential.
            </p>
          </div>

          {recommendationList.length > 0 && (
            <button
              type="button"
              className="savings-outline-button"
              onClick={() => onNavigate?.("recommendations")}
            >
              View all
              <ArrowRight size={16} />
            </button>
          )}
        </div>

        {topRecommendations.length > 0 ? (
          <div className="savings-opportunities-grid">
            {topRecommendations.map((item, index) => (
              <OpportunityCard
                key={item?.id ?? item?._id ?? index}
                item={item}
                index={index}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        ) : (
          <div className="savings-empty-state">
            <div className="savings-empty-state-icon">
              <CheckCircle2 size={24} />
            </div>

            <div>
              <h3>No recommendations yet</h3>
              <p>
                Once EnergyPilot has enough data, optimization opportunities
                will appear here.
              </p>
            </div>

            <button
              type="button"
              className="savings-text-button"
              onClick={() => onNavigate?.("data")}
            >
              Explore your data
              <ArrowRight size={15} />
            </button>
          </div>
        )}
      </section>

      {/* =========================================================
          PLAYBOOK FOOTER BANNER
      ========================================================= */}
      <section className="savings-playbook">
        <div className="savings-playbook-copy">
          <div className="savings-playbook-icon">
            <Sparkles size={21} />
          </div>

          <div>
            <span className="savings-section-kicker">OPTIMIZATION PLAYBOOK</span>
            <h2>Small changes can compound into meaningful savings.</h2>
            <p>
              Use EnergyPilot's analytics and recommendations together to
              identify high-impact changes, monitor their effect, and
              continuously improve your energy profile.
            </p>
          </div>
        </div>

        <div className="savings-playbook-actions">
          <button
            type="button"
            className="savings-playbook-button"
            onClick={() => onNavigate?.("analytics")}
          >
            Open analytics
            <ArrowRight size={16} />
          </button>

          <button
            type="button"
            className="savings-playbook-button savings-playbook-button--light"
            onClick={() => onNavigate?.("recommendations")}
          >
            See recommendations
            <ArrowRight size={16} />
          </button>
        </div>
      </section>

      <div className="savings-accessibility-status" aria-live="polite">
        {hasSavingsData
          ? "Savings insights available."
          : "Waiting for enough energy data to generate savings insights."}
      </div>
    </main>
  );
}