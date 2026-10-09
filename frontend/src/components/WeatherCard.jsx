import { useId, useMemo } from "react";
import {
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  CloudSnow,
  Droplets,
  MapPin,
  Sun,
  Sunrise,
  Sunset,
  Wind,
} from "lucide-react";
import "./WeatherCard.css";

// =============================================================================
// Constants & Configuration
// =============================================================================

const DEFAULT_LOCATION = "Local weather";

const WEATHER_CONDITIONS = {
  clear: { icon: Sun, label: "Clear" },
  sunny: { icon: Sun, label: "Sunny" },
  "clear sky": { icon: Sun, label: "Clear" },
  partly_cloudy: { icon: Cloud, label: "Partly cloudy" },
  partlycloudy: { icon: Cloud, label: "Partly cloudy" },
  "partly cloudy": { icon: Cloud, label: "Partly cloudy" },
  cloudy: { icon: Cloud, label: "Cloudy" },
  overcast: { icon: Cloud, label: "Overcast" },
  rain: { icon: CloudRain, label: "Rain" },
  rainy: { icon: CloudRain, label: "Rain" },
  drizzle: { icon: CloudDrizzle, label: "Drizzle" },
  snow: { icon: CloudSnow, label: "Snow" },
  snowy: { icon: CloudSnow, label: "Snow" },
  fog: { icon: CloudFog, label: "Fog" },
  mist: { icon: CloudFog, label: "Mist" },
  thunderstorm: { icon: CloudLightning, label: "Thunderstorm" },
  thunder_storm: { icon: CloudLightning, label: "Thunderstorm" },
  storm: { icon: CloudLightning, label: "Storm" },
};

// =============================================================================
// Helpers
// =============================================================================

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

function firstDefined(...values) {
  return values.find(
    (value) => value !== null && value !== undefined && value !== ""
  );
}

function toSafeString(value, fallback = "") {
  const resolved = firstDefined(value);
  return resolved === undefined ? fallback : String(resolved).trim();
}

function normalizeCondition(value) {
  const condition = toSafeString(value);
  if (!condition) return "unknown";

  return condition
    .toLowerCase()
    .trim()
    .replace(/[\s-]+/g, "_");
}

function getWeatherCondition(condition) {
  const normalized = normalizeCondition(condition);
  const spaced = normalized.replace(/_/g, " ");

  return (
    WEATHER_CONDITIONS[normalized] ??
    WEATHER_CONDITIONS[spaced] ?? {
      icon: Cloud,
      label: toSafeString(condition, "Conditions unavailable"),
    }
  );
}

function parseDate(value) {
  if (value === null || value === undefined || value === "") {
    return null;
  }

  let date;

  if (typeof value === "number" && Number.isFinite(value)) {
    date = new Date(Math.abs(value) < 1e11 ? value * 1000 : value);
  } else if (
    typeof value === "string" &&
    /^\d{10,13}$/.test(value.trim())
  ) {
    const numericValue = Number(value);
    date = new Date(
      value.trim().length <= 10 ? numericValue * 1000 : numericValue
    );
  } else {
    date = new Date(value);
  }

  return Number.isNaN(date.getTime()) ? null : date;
}

function formatTime(value) {
  const date = parseDate(value);
  if (!date) return "—";

  return date.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function getDateTimeValue(value) {
  const date = parseDate(value);
  return date ? date.toISOString() : undefined;
}

function formatTemperature(value) {
  const temperature = toFiniteNumber(value);
  return temperature === null ? "—" : `${Math.round(temperature)}°`;
}

function formatPercentage(value) {
  const number = toFiniteNumber(value);
  return number === null ? "—" : `${Math.round(number)}%`;
}

function formatWindSpeed(value) {
  const speed = toFiniteNumber(value);
  return speed === null ? "—" : `${Math.round(speed)} km/h`;
}

function normalizeWeather(weather) {
  if (!weather || typeof weather !== "object") return null;

  const current =
    weather.current && typeof weather.current === "object"
      ? weather.current
      : weather;

  const temperature = toFiniteNumber(
    firstDefined(
      current.temperature_c,
      current.temp_c,
      current.temperature,
      current.temp
    )
  );

  const feelsLike = toFiniteNumber(
    firstDefined(
      current.feels_like_c,
      current.apparent_temperature_c,
      current.feels_like,
      current.apparent_temperature
    )
  );

  const humidity = toFiniteNumber(
    firstDefined(
      current.humidity_percent,
      current.relative_humidity,
      current.humidity
    )
  );

  const windSpeed = toFiniteNumber(
    firstDefined(current.wind_speed_kmh, current.wind_kmh)
  );

  const condition = firstDefined(
    current.condition,
    current.conditions,
    current.weather,
    current.description
  );

  const location = firstDefined(
    weather.location,
    weather.city,
    weather.name,
    weather.location_name,
    current.location,
    current.city
  );

  const windDirection = firstDefined(
    current.wind_direction,
    current.wind_dir,
    current.wind_direction_text
  );

  const sunrise = firstDefined(
    current.sunrise,
    current.sunrise_time,
    weather.sunrise,
    weather.sunrise_time
  );

  const sunset = firstDefined(
    current.sunset,
    current.sunset_time,
    weather.sunset,
    weather.sunset_time
  );

  const timestamp = firstDefined(
    current.timestamp,
    current.observed_at,
    current.updated_at,
    weather.timestamp,
    weather.observed_at,
    weather.updated_at
  );

  return {
    location: toSafeString(location, DEFAULT_LOCATION),
    temperature,
    feelsLike,
    condition: toSafeString(condition, "Conditions unavailable"),
    humidity,
    windSpeed,
    windDirection: windDirection ? String(windDirection).trim() : null,
    sunrise,
    sunset,
    timestamp,
  };
}

// =============================================================================
// Sub-components
// =============================================================================

function WeatherMetric({ icon: Icon, label, value, description }) {
  return (
    <div className="weather-card__metric">
      <span className="weather-card__metric-icon" aria-hidden="true">
        <Icon size={18} strokeWidth={1.8} />
      </span>

      <div className="weather-card__metric-content">
        <span className="weather-card__metric-label">{label}</span>
        <strong className="weather-card__metric-value">{value}</strong>
        {description && (
          <span className="weather-card__metric-description">
            {description}
          </span>
        )}
      </div>
    </div>
  );
}

function WeatherCardLoading() {
  return (
    <section
      className="weather-card weather-card--loading"
      aria-busy="true"
      aria-label="Loading weather information"
    >
      <div className="weather-card__skeleton weather-card__skeleton--location" />
      <div className="weather-card__skeleton weather-card__skeleton--temperature" />
      <div className="weather-card__skeleton weather-card__skeleton--condition" />

      <div className="weather-card__loading-grid" aria-hidden="true">
        {[1, 2, 3, 4].map((item) => (
          <div
            className="weather-card__skeleton weather-card__skeleton--metric"
            key={item}
          />
        ))}
      </div>
    </section>
  );
}

function WeatherCardMessage({ type, message }) {
  const isError = type === "error";

  return (
    <section
      className={`weather-card weather-card--message ${
        isError ? "weather-card--error" : "weather-card--empty"
      }`}
      role={isError ? "alert" : "status"}
    >
      <span className="weather-card__message-icon" aria-hidden="true">
        <Cloud size={26} strokeWidth={1.7} />
      </span>

      <div className="weather-card__message-content">
        <h3>{isError ? "Unable to load weather" : "Weather unavailable"}</h3>
        <p>
          {message ||
            (isError
              ? "Weather data could not be retrieved. Please try again later."
              : "Current weather information is not available right now.")}
        </p>
      </div>
    </section>
  );
}

// =============================================================================
// Main Component
// =============================================================================

/**
 * @typedef {Object} WeatherCardProps
 * @property {Object|null} [weather]
 * @property {boolean} [loading]
 * @property {string|Error|null} [error]
 */

/**
 * WeatherCard component for displaying current weather conditions, forecasts, and metrics.
 * 
 * @param {WeatherCardProps} props
 */
export default function WeatherCard({
  weather = null,
  loading = false,
  error = null,
}) {
  const titleId = useId();

  const data = useMemo(() => normalizeWeather(weather), [weather]);

  if (loading) return <WeatherCardLoading />;

  if (error) {
    const message = typeof error === "string" ? error : error?.message;
    return <WeatherCardMessage type="error" message={message} />;
  }

  if (!data) return <WeatherCardMessage type="empty" />;

  const conditionInfo = getWeatherCondition(data.condition);
  const WeatherIcon = conditionInfo.icon;

  const updatedDateTime = getDateTimeValue(data.timestamp);
  const sunriseDateTime = getDateTimeValue(data.sunrise);
  const sunsetDateTime = getDateTimeValue(data.sunset);

  return (
    <section className="weather-card" aria-labelledby={titleId}>
      <div className="weather-card__atmosphere" aria-hidden="true">
        <span className="weather-card__orb weather-card__orb--one" />
        <span className="weather-card__orb weather-card__orb--two" />
      </div>

      <header className="weather-card__header">
        <div className="weather-card__location-group">
          <span className="weather-card__eyebrow">
            <span className="weather-card__eyebrow-dot" aria-hidden="true" />
            LOCAL CONDITIONS
          </span>

          <h2 id={titleId} className="weather-card__location">
            <MapPin size={16} strokeWidth={2} aria-hidden="true" />
            <span>{data.location}</span>
          </h2>
        </div>

        {data.timestamp && (
          <span className="weather-card__updated">
            <span className="weather-card__updated-dot" aria-hidden="true" />
            <time dateTime={updatedDateTime}>
              Updated {formatTime(data.timestamp)}
            </time>
          </span>
        )}
      </header>

      <div className="weather-card__hero">
        <div className="weather-card__hero-copy">
          <p className="weather-card__hero-label">Right now</p>

          <div className="weather-card__temperature">
            <span
              className="weather-card__temperature-value"
              aria-label={
                data.temperature !== null
                  ? `${Math.round(data.temperature)} degrees Celsius`
                  : "Temperature unavailable"
              }
            >
              {formatTemperature(data.temperature)}
            </span>
            <span className="weather-card__temperature-unit" aria-hidden="true">
              C
            </span>
          </div>

          <p className="weather-card__condition">{conditionInfo.label}</p>

          {data.feelsLike !== null && (
            <p className="weather-card__feels-like">
              Feels like {formatTemperature(data.feelsLike)}C
            </p>
          )}
        </div>

        <div className="weather-card__condition-art" aria-hidden="true">
          <span className="weather-card__condition-halo" />
          <WeatherIcon
            className="weather-card__condition-icon"
            size={76}
            strokeWidth={1.35}
          />
        </div>
      </div>

      <div className="weather-card__divider" aria-hidden="true" />

      <div className="weather-card__details-heading">
        <span>WEATHER DETAILS</span>
        <span className="weather-card__details-caption">
          Outdoor conditions
        </span>
      </div>

      <div className="weather-card__metrics" aria-label="Weather details">
        <WeatherMetric
          icon={Droplets}
          label="Humidity"
          value={formatPercentage(data.humidity)}
          description="Relative humidity"
        />

        <WeatherMetric
          icon={Wind}
          label="Wind"
          value={formatWindSpeed(data.windSpeed)}
          description={data.windDirection || "Wind speed"}
        />

        <WeatherMetric
          icon={Sunrise}
          label="Sunrise"
          value={
            <time dateTime={sunriseDateTime}>
              {formatTime(data.sunrise)}
            </time>
          }
          description="Local time"
        />

        <WeatherMetric
          icon={Sunset}
          label="Sunset"
          value={
            <time dateTime={sunsetDateTime}>
              {formatTime(data.sunset)}
            </time>
          }
          description="Local time"
        />
      </div>

      <footer className="weather-card__footer">
        <span className="weather-card__footer-icon" aria-hidden="true">
          <Sun size={17} strokeWidth={1.8} />
        </span>
        <p>
          Outdoor conditions can influence your building’s heating and
          cooling demand.
        </p>
      </footer>
    </section>
  );
}