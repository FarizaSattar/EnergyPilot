import { useEffect, useId, useMemo, useState } from "react";
import PropTypes from "prop-types";
import { Activity, Zap } from "lucide-react";
import "./LoadingState.css";

/* ============================================================================
   Constants & Defaults
   ========================================================================== */

const DEFAULT_MESSAGE = "Loading EnergyPilot...";
const DEFAULT_SIZE = "medium";
const DEFAULT_VARIANT = "inline";
const DEFAULT_DELAY = 150;

const VALID_SIZES = new Set(["small", "medium", "large"]);
const VALID_VARIANTS = new Set(["inline", "card", "page"]);

/* ============================================================================
   Helpers
   ========================================================================== */

function getSizeClass(size) {
  return VALID_SIZES.has(size) ? size : DEFAULT_SIZE;
}

function getVariantClass(variant) {
  return VALID_VARIANTS.has(variant) ? variant : DEFAULT_VARIANT;
}

function getMessage(message) {
  if (typeof message !== "string" || message.trim() === "") {
    return DEFAULT_MESSAGE;
  }
  return message.trim();
}

function getDelay(delay) {
  const numericDelay = Number(delay);
  if (!Number.isFinite(numericDelay) || numericDelay < 0) {
    return DEFAULT_DELAY;
  }
  return numericDelay;
}

function buildClassName({ size, variant, fullScreen }) {
  return [
    "loading-state",
    `loading-state--${size}`,
    `loading-state--${variant}`,
    fullScreen ? "loading-state--fullscreen" : null,
  ]
    .filter(Boolean)
    .join(" ");
}

/* ============================================================================
   Main Component
   ========================================================================== */

export default function LoadingState({
  message = DEFAULT_MESSAGE,
  size = DEFAULT_SIZE,
  variant = DEFAULT_VARIANT,
  fullScreen = false,
  delay = DEFAULT_DELAY,
}) {
  const messageId = useId();

  const normalizedMessage = useMemo(() => getMessage(message), [message]);
  const normalizedSize = useMemo(() => getSizeClass(size), [size]);
  const normalizedVariant = useMemo(() => getVariantClass(variant), [variant]);
  const normalizedDelay = useMemo(() => getDelay(delay), [delay]);

  const [visible, setVisible] = useState(() => normalizedDelay === 0);

  /* --------------------------------------------------------------------------
     Delayed Visibility Handler
     ------------------------------------------------------------------------ */

  useEffect(() => {
    if (normalizedDelay === 0) {
      setVisible(true);
      return undefined;
    }

    setVisible(false);

    const timeoutId = window.setTimeout(() => {
      setVisible(true);
    }, normalizedDelay);

    return () => {
      window.clearTimeout(timeoutId);
    };
  }, [normalizedDelay]);

  if (!visible) {
    return null;
  }

  const containerClassName = buildClassName({
    size: normalizedSize,
    variant: normalizedVariant,
    fullScreen: Boolean(fullScreen),
  });

  const iconSize = normalizedSize === "small" ? 14 : normalizedSize === "large" ? 22 : 18;

  return (
    <div
      className={containerClassName}
      role="status"
      aria-live="polite"
      aria-busy="true"
      aria-describedby={messageId}
    >
      <div className="loading-state-content">
        {/* Animated Visual Indicator */}
        <div className="loading-state-visual" aria-hidden="true">
          <div className="loading-state-orbit">
            <span className="loading-state-orbit-dot" />
          </div>

          <div className="loading-state-icon">
            <Zap size={iconSize} strokeWidth={2.2} />
          </div>
        </div>

        {/* Copy / Message */}
        <div className="loading-state-copy">
          <span className="loading-state-label">
            <Activity size={12} strokeWidth={2.2} aria-hidden="true" />
            Processing
          </span>

          <p id={messageId} className="loading-state-message">
            {normalizedMessage}
          </p>
        </div>
      </div>

      {/* Subtle Bottom Shimmer Progress Line */}
      <div className="loading-state-progress" aria-hidden="true">
        <span />
      </div>
    </div>
  );
}

LoadingState.propTypes = {
  message: PropTypes.string,
  size: PropTypes.oneOf(["small", "medium", "large"]),
  variant: PropTypes.oneOf(["inline", "card", "page"]),
  fullScreen: PropTypes.bool,
  delay: PropTypes.number,
};