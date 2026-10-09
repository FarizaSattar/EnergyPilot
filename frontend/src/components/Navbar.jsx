import { useCallback, useMemo } from "react";
import {
  BarChart3,
  Database,
  Home as HomeIcon,
  Lightbulb,
  Zap,
} from "lucide-react";

import "./Navbar.css";

/* ============================================================================
   Constants & Configuration
   ========================================================================== */

const BRAND_NAME = "EnergyPilot";
const BRAND_SUBTITLE = "Energy intelligence";

const NAVIGATION = Object.freeze([
  {
    id: "home",
    label: "Home",
    icon: HomeIcon,
  },
  {
    id: "analytics",
    label: "Analytics",
    icon: BarChart3,
  },
  {
    id: "recommendations",
    label: "Savings",
    icon: Lightbulb,
  },
  {
    id: "data",
    label: "Data",
    icon: Database,
  },
]);

const VALID_PAGE_IDS = new Set(NAVIGATION.map((item) => item.id));

/* ============================================================================
   Component
   ========================================================================== */

export default function Navbar({
  page = "home",
  onNavigate,
  className = "",
  systemStatus = "Live",
}) {
  const activePage = useMemo(() => {
    return VALID_PAGE_IDS.has(page) ? page : "home";
  }, [page]);

  const handleNavigation = useCallback(
    (id) => {
      if (!VALID_PAGE_IDS.has(id)) {
        return;
      }

      if (typeof onNavigate === "function") {
        onNavigate(id);
      }
    },
    [onNavigate]
  );

  const containerClassName = useMemo(() => {
    return ["navbar", className.trim()].filter(Boolean).join(" ");
  }, [className]);

  return (
    <header className={containerClassName} aria-label="EnergyPilot header">
      <div className="navbar-inner">
        {/* Brand */}
        <button
          type="button"
          className="navbar-brand"
          onClick={() => handleNavigation("home")}
          aria-label="Go to EnergyPilot home"
        >
          <span className="navbar-brand-mark" aria-hidden="true">
            <span className="navbar-brand-mark-glow" />
            <Zap
              size={18}
              strokeWidth={2.35}
              focusable="false"
            />
          </span>

          <span className="navbar-brand-copy">
            <span className="navbar-brand-name">{BRAND_NAME}</span>
            <span className="navbar-brand-subtitle">{BRAND_SUBTITLE}</span>
          </span>
        </button>

        {/* Navigation */}
        <nav className="navbar-navigation" aria-label="Main navigation">
          <div className="navbar-navigation-inner">
            {NAVIGATION.map((item) => {
              const Icon = item.icon;
              const isActive = activePage === item.id;

              return (
                <button
                  key={item.id}
                  type="button"
                  className={[
                    "navbar-navigation-item",
                    isActive ? "navbar-navigation-item-active" : "",
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() => handleNavigation(item.id)}
                  aria-current={isActive ? "page" : undefined}
                >
                  <span className="navbar-navigation-icon" aria-hidden="true">
                    <Icon
                      size={16}
                      strokeWidth={isActive ? 2.15 : 1.85}
                      focusable="false"
                    />
                  </span>

                  <span className="navbar-navigation-label">{item.label}</span>
                </button>
              );
            })}
          </div>
        </nav>

        {/* System Status Indicator */}
        <div className="navbar-right">
          <div
            className="navbar-status"
            title={`EnergyPilot system is ${systemStatus}`}
            aria-label={`System status: ${systemStatus}`}
          >
            <span className="navbar-status-indicator" aria-hidden="true">
              <span className="navbar-status-dot" />
            </span>

            <span className="navbar-status-copy">
              <span className="navbar-status-label">System</span>
              <span className="navbar-status-text">{systemStatus}</span>
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}