import { useCallback, useId, useMemo } from "react";
import PropTypes from "prop-types";
import { Menu, X, Zap } from "lucide-react";
import "./MobileHeader.css";

/* ============================================================================
   Constants & Defaults
   ========================================================================== */

const BRAND_NAME = "EnergyPilot";
const DEFAULT_SUBTITLE = "Energy intelligence";
const OPEN_MENU_LABEL = "Open navigation menu";
const CLOSE_MENU_LABEL = "Close navigation menu";

/* ============================================================================
   Helper Functions
   ========================================================================== */

function getDisplayTitle(title) {
  if (typeof title !== "string" || title.trim() === "") {
    return BRAND_NAME;
  }
  return title.trim();
}

function getDisplaySubtitle(subtitle) {
  if (typeof subtitle !== "string" || subtitle.trim() === "") {
    return DEFAULT_SUBTITLE;
  }
  return subtitle.trim();
}

/* ============================================================================
   Main Component
   ========================================================================== */

export default function MobileHeader({
  isMenuOpen = false,
  onMenuToggle,
  title = BRAND_NAME,
  subtitle = DEFAULT_SUBTITLE,
  navigationId,
  rightAction = null,
  className = "",
}) {
  const generatedNavId = useId();

  // Normalize inputs
  const menuOpen = Boolean(isMenuOpen);
  const displayTitle = useMemo(() => getDisplayTitle(title), [title]);
  const displaySubtitle = useMemo(() => getDisplaySubtitle(subtitle), [subtitle]);
  
  const resolvedNavigationId = useMemo(() => {
    if (typeof navigationId === "string" && navigationId.trim() !== "") {
      return navigationId.trim();
    }
    return `mobile-nav-${generatedNavId.replace(/:/g, "")}`;
  }, [navigationId, generatedNavId]);

  const menuLabel = menuOpen ? CLOSE_MENU_LABEL : OPEN_MENU_LABEL;

  const handleMenuToggle = useCallback(
    (event) => {
      if (typeof onMenuToggle === "function") {
        onMenuToggle(event);
      }
    },
    [onMenuToggle]
  );

  const containerClassName = useMemo(() => {
    return [
      "mobile-header",
      menuOpen ? "mobile-header--open" : null,
      className.trim() || null,
    ]
      .filter(Boolean)
      .join(" ");
  }, [menuOpen, className]);

  return (
    <header className={containerClassName} aria-label="Mobile application header">
      {/* Brand / Title Section */}
      <div className="mobile-header-brand">
        <span className="mobile-header-brand-mark" aria-hidden="true">
          <span className="mobile-header-brand-glow" />
          <Zap
            size={18}
            strokeWidth={2.35}
            focusable="false"
          />
        </span>

        <span className="mobile-header-brand-copy">
          <span className="mobile-header-brand-name">{displayTitle}</span>
          <span className="mobile-header-brand-subtitle">{displaySubtitle}</span>
        </span>
      </div>

      {/* Right Action Slot & Navigation Toggle */}
      <div className="mobile-header-actions">
        {rightAction && (
          <div className="mobile-header-extra-action">{rightAction}</div>
        )}

        <button
          type="button"
          className={`mobile-header-menu-button ${
            menuOpen ? "mobile-header-menu-button--open" : ""
          }`}
          onClick={handleMenuToggle}
          aria-label={menuLabel}
          aria-expanded={menuOpen}
          aria-controls={resolvedNavigationId}
          title={menuLabel}
        >
          <span className="mobile-header-menu-icon" aria-hidden="true">
            <Menu
              className="mobile-header-menu-icon--menu"
              size={21}
              strokeWidth={2.1}
              focusable="false"
            />
            <X
              className="mobile-header-menu-icon--close"
              size={21}
              strokeWidth={2.1}
              focusable="false"
            />
          </span>
        </button>
      </div>
    </header>
  );
}

MobileHeader.propTypes = {
  isMenuOpen: PropTypes.bool,
  onMenuToggle: PropTypes.func,
  title: PropTypes.string,
  subtitle: PropTypes.string,
  navigationId: PropTypes.string,
  rightAction: PropTypes.node,
  className: PropTypes.string,
};