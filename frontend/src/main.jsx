/**
 * EnergyPilot
 * React Application Entry Point
 *
 * Handles top-level bootstrapping, global error boundaries, and DOM mounting.
 */

import React, { Component } from "react";
import ReactDOM from "react-dom/client";

import App from "./App.jsx";
import "./index.css";

/* ==========================================================================
   Global Error Boundary Fallback
   ========================================================================== */

class GlobalErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    if (import.meta.env?.DEV) {
      console.error("[EnergyPilot Critical Failure]", error, errorInfo);
    }
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          style={{
            minHeight: "100vh",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: "#091310",
            color: "#f0f4f2",
            fontFamily: "Inter, system-ui, sans-serif",
            padding: "2rem",
            textAlign: "center",
            boxSizing: "border-box",
          }}
        >
          <div
            style={{
              width: "56px",
              height: "56px",
              backgroundColor: "rgba(248, 113, 113, 0.15)",
              border: "1px solid rgba(248, 113, 113, 0.3)",
              borderRadius: "12px",
              display: "grid",
              placeItems: "center",
              fontSize: "28px",
              marginBottom: "1rem",
            }}
          >
            ⚠️
          </div>
          <h1
            style={{
              margin: "0 0 0.5rem 0",
              fontSize: "1.25rem",
              fontWeight: 700,
            }}
          >
            EnergyPilot Application Error
          </h1>
          <p
            style={{
              color: "#798c84",
              maxWidth: "400px",
              fontSize: "0.875rem",
              lineHeight: 1.5,
              margin: "0 0 1.5rem 0",
            }}
          >
            An unexpected error occurred while running the analytics workspace.
          </p>
          <button
            type="button"
            onClick={() => window.location.reload()}
            style={{
              backgroundColor: "#0f766e",
              color: "#ffffff",
              border: "none",
              padding: "0.6rem 1.25rem",
              borderRadius: "8px",
              fontSize: "0.8125rem",
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Reload Workspace
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}

/* ==========================================================================
   Application Initialization
   ========================================================================== */

const rootElement = document.getElementById("root");

if (!rootElement) {
  throw new Error(
    "EnergyPilot failed to mount: #root DOM container element was not found."
  );
}

// Performance telemetry marker for development startup monitoring
if (import.meta.env?.DEV) {
  performance.mark("energy-pilot-init");
}

const root = ReactDOM.createRoot(rootElement);

root.render(
  <React.StrictMode>
    <GlobalErrorBoundary>
      <App />
    </GlobalErrorBoundary>
  </React.StrictMode>
);