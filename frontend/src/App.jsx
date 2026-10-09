import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  getAnalytics,
  getDashboard,
  getReadings,
  getRecommendations,
  simulate,
  uploadCSV,
} from "./api";

import Navbar from "./components/Navbar";
import Home from "./pages/Home";
import Analytics from "./pages/Analytics";
import Savings from "./pages/Savings";
import Recommendations from "./pages/Recommendations";
import Data from "./pages/Data";

import "./App.css";

/* ==========================================================================
   Constants & Utilities
   ========================================================================== */

const DEFAULT_PAGE = "home";
const READINGS_LIMIT = 500;

const PAGES = {
  HOME: "home",
  ANALYTICS: "analytics",
  SAVINGS: "savings",
  RECOMMENDATIONS: "recommendations",
  DATA: "data",
};

const normalizeArray = (res, key) => {
  if (Array.isArray(res)) return res;
  if (res && typeof res === "object") {
    if (Array.isArray(res[key])) return res[key];
    if (Array.isArray(res.data)) return res.data;
  }
  return [];
};

const normalizeObject = (res) => {
  if (!res || typeof res !== "object" || Array.isArray(res)) return {};
  if (res.data && typeof res.data === "object" && !Array.isArray(res.data)) {
    return res.data;
  }
  return res;
};

const getErrorMessage = (err) => {
  if (!err) return "An unexpected error occurred.";
  if (typeof err === "string") return err;
  return err.message?.trim() || "Unable to sync with EnergyPilot services.";
};

const isAbortError = (err) =>
  err?.name === "AbortError" || err?.code === "ERR_CANCELED";

const debugLog = (...args) => {
  if (import.meta.env?.DEV) console.debug("[EnergyPilot]", ...args);
};

const debugError = (...args) => {
  if (import.meta.env?.DEV) console.error("[EnergyPilot]", ...args);
};

/* ==========================================================================
   Main Component
   ========================================================================== */

export default function App() {
  const [page, setPage] = useState(DEFAULT_PAGE);

  // Application Data States
  const [dashboard, setDashboard] = useState({});
  const [analytics, setAnalytics] = useState({});
  const [recommendations, setRecommendations] = useState([]);
  const [readings, setReadings] = useState([]);

  // UI Flow States
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [dataOperationLoading, setDataOperationLoading] = useState(false);
  const [error, setError] = useState(null);

  // Lifecycle Refs
  const mountedRef = useRef(true);
  const loadRequestIdRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  /* ------------------------------------------------------------------------
     Data Sync
     ------------------------------------------------------------------------ */

  const loadData = useCallback(async ({ isInitial = false } = {}) => {
    const requestId = ++loadRequestIdRef.current;

    if (isInitial) {
      setInitialLoading(true);
    } else {
      setRefreshing(true);
    }

    setError(null);
    debugLog("Synchronizing telemetry & analytical models...");

    const results = await Promise.allSettled([
      getDashboard(),
      getAnalytics(),
      getRecommendations(),
      getReadings(READINGS_LIMIT),
    ]);

    if (!mountedRef.current || requestId !== loadRequestIdRef.current) return;

    const [dashRes, analyticsRes, recsRes, readingsRes] = results;

    if (dashRes.status === "fulfilled") setDashboard(normalizeObject(dashRes.value));
    else debugError("Dashboard sync failed:", dashRes.reason);

    if (analyticsRes.status === "fulfilled") setAnalytics(normalizeObject(analyticsRes.value));
    else debugError("Analytics sync failed:", analyticsRes.reason);

    if (recsRes.status === "fulfilled") setRecommendations(normalizeArray(recsRes.value, "recommendations"));
    else debugError("Recommendations sync failed:", recsRes.reason);

    if (readingsRes.status === "fulfilled") setReadings(normalizeArray(readingsRes.value, "readings"));
    else debugError("Readings sync failed:", readingsRes.reason);

    const failures = results.filter(
      (r) => r.status === "rejected" && !isAbortError(r.reason)
    );

    if (failures.length > 0) {
      setError("Some data feeds were unreachable. Displaying cached telemetry.");
    }

    setInitialLoading(false);
    setRefreshing(false);
    debugLog("Data sync complete.");
  }, []);

  useEffect(() => {
    loadData({ isInitial: true });
  }, [loadData]);

  /* ------------------------------------------------------------------------
     Navigation & Operations
     ------------------------------------------------------------------------ */

  const handlePageChange = useCallback((nextPage) => {
    if (!Object.values(PAGES).includes(nextPage)) return;
    setPage(nextPage);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  const handleRefresh = useCallback(() => {
    loadData({ isInitial: false });
  }, [loadData]);

  const handleSimulate = useCallback(
    async (payload) => {
      setDataOperationLoading(true);
      setError(null);
      try {
        const response = await simulate(payload);
        if (!mountedRef.current) return response;
        await loadData({ isInitial: false });
        return response;
      } catch (err) {
        debugError("Simulation failed:", err);
        if (mountedRef.current) setError(getErrorMessage(err));
        throw err;
      } finally {
        if (mountedRef.current) setDataOperationLoading(false);
      }
    },
    [loadData]
  );

  const handleUploadCSV = useCallback(
    async (file) => {
      setDataOperationLoading(true);
      setError(null);
      try {
        const response = await uploadCSV(file);
        if (!mountedRef.current) return response;
        await loadData({ isInitial: false });
        return response;
      } catch (err) {
        debugError("CSV Ingestion failed:", err);
        if (mountedRef.current) setError(getErrorMessage(err));
        throw err;
      } finally {
        if (mountedRef.current) setDataOperationLoading(false);
      }
    },
    [loadData]
  );

  /* ------------------------------------------------------------------------
     Page Routing
     ------------------------------------------------------------------------ */

  const activePageComponent = useMemo(() => {
    switch (page) {
      case PAGES.ANALYTICS:
        return (
          <Analytics
            analytics={analytics}
            readings={readings}
            dashboard={dashboard}
            refreshing={refreshing}
            onRefresh={handleRefresh}
          />
        );
      case PAGES.SAVINGS:
        return (
          <Savings
            dashboard={dashboard}
            analytics={analytics}
            recommendations={recommendations}
            readings={readings}
            onNavigate={handlePageChange}
          />
        );
      case PAGES.RECOMMENDATIONS:
        return (
          <Recommendations
            recommendations={recommendations}
            dashboard={dashboard}
            analytics={analytics}
            onSimulate={handleSimulate}
            loading={dataOperationLoading}
          />
        );
      case PAGES.DATA:
        return (
          <Data
            readings={readings}
            dashboard={dashboard}
            analytics={analytics}
            onUploadCSV={handleUploadCSV}
            loading={dataOperationLoading}
            refreshing={refreshing}
            onRefresh={handleRefresh}
          />
        );
      case PAGES.HOME:
      default:
        return (
          <Home
            dashboard={dashboard}
            analytics={analytics}
            recommendations={recommendations}
            readings={readings}
            refreshing={refreshing}
            onRefresh={handleRefresh}
            onNavigate={handlePageChange}
          />
        );
    }
  }, [
    page,
    analytics,
    readings,
    dashboard,
    refreshing,
    recommendations,
    dataOperationLoading,
    handleRefresh,
    handlePageChange,
    handleSimulate,
    handleUploadCSV,
  ]);

  /* ------------------------------------------------------------------------
     Render
     ------------------------------------------------------------------------ */

  return (
    <div className="app-container">
      <Navbar page={page} onNavigate={handlePageChange} />

      <div className="app-body">
        {/* Sync Indicator */}
        {refreshing && (
          <div className="app-sync-banner" role="status" aria-live="polite">
            <span className="app-sync-pulse" aria-hidden="true" />
            <span>Updating real-time telemetry...</span>
          </div>
        )}

        {/* Floating Error Notification */}
        {error && (
          <div className="app-toast app-toast-error" role="alert">
            <div className="app-toast-icon" aria-hidden="true">⚠️</div>
            <div className="app-toast-content">
              <span className="app-toast-title">Sync Issue</span>
              <span className="app-toast-msg">{error}</span>
            </div>
            <button
              type="button"
              className="app-toast-close"
              onClick={() => setError(null)}
              aria-label="Dismiss message"
            >
              ✕
            </button>
          </div>
        )}

        <main className="app-content">
          {initialLoading ? (
            <div className="app-skeleton-loader" role="status" aria-live="polite">
              <div className="app-brand-badge">
                <span className="app-brand-icon">⚡</span>
              </div>
              <h1 className="app-brand-title">EnergyPilot</h1>
              <p className="app-brand-subtitle">
                Initializing analytics engine & grid telemetry...
              </p>
              <div className="app-loading-bar">
                <div className="app-loading-fill" />
              </div>
            </div>
          ) : (
            <div className="app-page-fade-in">{activePageComponent}</div>
          )}
        </main>
      </div>
    </div>
  );
}