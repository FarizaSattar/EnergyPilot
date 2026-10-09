/**
 * ============================================================
 * EnergyPilot API Client
 * ============================================================
 *
 * Centralized client layer for backend communication.
 */

/* --------------------------------------------------------------------------
 * Configuration & Constants
 * -------------------------------------------------------------------------- */

const DEFAULT_BASE_URL = "http://localhost:5000";
const DEFAULT_TIMEOUT_MS = 15_000;

export const MAX_READINGS_LIMIT = 5_000;
export const MAX_FORECAST_DAYS = 90;
export const MAX_SIMULATION_DAYS = 365;
export const CSV_MAX_BYTES = 10 * 1024 * 1024;

export const BASE_URL = (
  import.meta.env?.VITE_ENERGYPILOT_API || DEFAULT_BASE_URL
).replace(/\/+$/, "");


/* --------------------------------------------------------------------------
 * Custom Error Class
 * -------------------------------------------------------------------------- */

export class ApiError extends Error {
  constructor(
    message,
    {
      status = 0,
      statusText = "",
      path = "",
      method = "",
      url = "",
      details = null,
      code = "API_ERROR",
      cause = null,
    } = {}
  ) {
    super(message, { cause });

    this.name = "ApiError";
    this.status = status;
    this.statusText = statusText;
    this.path = path;
    this.method = method;
    this.url = url;
    this.details = details;
    this.code = code;

    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, ApiError);
    }
  }
}

function createAbortError(message = "Request was cancelled.") {
  return new ApiError(message, { code: "REQUEST_CANCELLED" });
}

function createTimeoutError(path, method, url) {
  return new ApiError("The request timed out. Please try again.", {
    path,
    method,
    url,
    code: "REQUEST_TIMEOUT",
  });
}


/* --------------------------------------------------------------------------
 * URL & Validation Helpers
 * -------------------------------------------------------------------------- */

function buildUrl(path, params = null) {
  const normalizedPath = String(path).startsWith("/") ? path : `/${path}`;
  const url = new URL(`${BASE_URL}${normalizedPath}`);

  if (params && typeof params === "object") {
    Object.entries(params).forEach(([key, value]) => {
      if (value === undefined || value === null || value === "") return;
      if (Array.isArray(value)) {
        value.forEach((val) => url.searchParams.append(key, String(val)));
      } else {
        url.searchParams.set(key, String(value));
      }
    });
  }

  return url.toString();
}

function validateTimeout(timeout) {
  if (timeout == null) return DEFAULT_TIMEOUT_MS;
  const num = Number(timeout);
  if (!Number.isFinite(num) || num <= 0) {
    throw new TypeError("Request timeout must be a positive number.");
  }
  return num;
}

function normalizePositiveInteger(
  value,
  { defaultValue, min = 1, max = Number.MAX_SAFE_INTEGER, name = "value" }
) {
  if (value === undefined || value === null || value === "") {
    return defaultValue;
  }
  const number = Number(value);
  if (!Number.isInteger(number) || number < min || number > max) {
    throw new RangeError(`${name} must be an integer between ${min} and ${max}.`);
  }
  return number;
}

function normalizeLimit(limit) {
  return normalizePositiveInteger(limit, {
    defaultValue: 200,
    min: 1,
    max: MAX_READINGS_LIMIT,
    name: "limit",
  });
}

function normalizeDays(days, { defaultValue = 7, max = MAX_FORECAST_DAYS, name = "days" } = {}) {
  return normalizePositiveInteger(days, { defaultValue, min: 1, max, name });
}


/* --------------------------------------------------------------------------
 * Response Parsing
 * -------------------------------------------------------------------------- */

function isJsonResponse(response) {
  const contentType = response.headers.get("content-type");
  return Boolean(contentType?.toLowerCase().includes("application/json"));
}

async function parseResponseBody(response) {
  if (response.status === 204) return null;

  if (isJsonResponse(response)) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }

  try {
    const text = await response.text();
    return text || null;
  } catch {
    return null;
  }
}

function extractErrorMessage(body, response) {
  if (!body) {
    return response.statusText || `Request failed with status ${response.status}.`;
  }
  if (typeof body === "string") return body;
  if (typeof body === "object") {
    return (
      body.error ||
      body.message ||
      body.detail ||
      body.details?.message ||
      response.statusText ||
      `Request failed with status ${response.status}.`
    );
  }
  return response.statusText || `Request failed with status ${response.status}.`;
}


/* --------------------------------------------------------------------------
 * Core Request Execution
 * -------------------------------------------------------------------------- */

function shouldSerializeAsJson(body) {
  if (body == null || typeof body === "string") return false;
  if (typeof FormData !== "undefined" && body instanceof FormData) return false;
  if (typeof Blob !== "undefined" && body instanceof Blob) return false;
  if (typeof ArrayBuffer !== "undefined" && body instanceof ArrayBuffer) return false;
  return true;
}

function prepareRequestBody(body, headers) {
  const requestHeaders = new Headers(headers);
  let requestBody = body;

  if (shouldSerializeAsJson(body)) {
    requestBody = JSON.stringify(body);
    if (!requestHeaders.has("Content-Type")) {
      requestHeaders.set("Content-Type", "application/json");
    }
  }

  if (!requestHeaders.has("Accept")) {
    requestHeaders.set("Accept", "application/json");
  }

  return { headers: requestHeaders, body: requestBody };
}

async function request(
  path,
  {
    method = "GET",
    params = null,
    body = undefined,
    headers = {},
    timeout = DEFAULT_TIMEOUT_MS,
    signal: callerSignal = null,
  } = {}
) {
  const normalizedMethod = String(method).toUpperCase();
  const url = buildUrl(path, params);
  const timeoutMs = validateTimeout(timeout);

  const timeoutController = new AbortController();
  let timedOut = false;

  const timeoutId = setTimeout(() => {
    timedOut = true;
    timeoutController.abort();
  }, timeoutMs);

  // Combine caller signal and timeout signal cleanly
  let combinedSignal = timeoutController.signal;
  if (callerSignal) {
    if (callerSignal.aborted) {
      clearTimeout(timeoutId);
      throw createAbortError();
    }
    if (typeof AbortSignal.any === "function") {
      combinedSignal = AbortSignal.any([callerSignal, timeoutController.signal]);
    } else {
      callerSignal.addEventListener("abort", () => timeoutController.abort(), { once: true });
    }
  }

  const prepared = prepareRequestBody(body, headers);
  let response;

  try {
    response = await fetch(url, {
      method: normalizedMethod,
      headers: prepared.headers,
      body: prepared.body,
      signal: combinedSignal,
    });
  } catch (err) {
    if (timedOut) throw createTimeoutError(path, normalizedMethod, url);
    if (callerSignal?.aborted) throw createAbortError();

    throw new ApiError("Unable to connect to the EnergyPilot backend.", {
      path,
      method: normalizedMethod,
      url,
      code: "NETWORK_ERROR",
      cause: err,
    });
  } finally {
    clearTimeout(timeoutId);
  }

  const responseBody = await parseResponseBody(response);

  if (!response.ok) {
    throw new ApiError(extractErrorMessage(responseBody, response), {
      status: response.status,
      statusText: response.statusText,
      path,
      method: normalizedMethod,
      url,
      details: responseBody,
      code: "HTTP_ERROR",
    });
  }

  return responseBody;
}


/* --------------------------------------------------------------------------
 * Specific API Endpoints
 * -------------------------------------------------------------------------- */

export async function getHealth(options = {}) {
  return request("/api/health", options);
}

export async function getDashboard(options = {}) {
  return request("/api/dashboard", options);
}

export async function getOverview(options = {}) {
  return request("/api/overview", options);
}

export async function getReadings(limit = 200, options = {}) {
  const normalizedLimit = normalizeLimit(limit);
  return request("/api/readings", {
    ...options,
    params: { ...(options.params || {}), limit: normalizedLimit },
  });
}

export async function getSummary(options = {}) {
  return request("/api/summary", options);
}

export async function getAnalytics(options = {}) {
  return request("/api/analytics", options);
}

export async function getRecommendations(options = {}) {
  return request("/api/recommendations", options);
}

export async function getForecast(days = 7, options = {}) {
  const normalizedDays = normalizeDays(days, { max: MAX_FORECAST_DAYS, name: "forecast days" });
  return request("/api/forecast", {
    ...options,
    params: { ...(options.params || {}), days: normalizedDays },
  });
}

export async function getPlans(options = {}) {
  return request("/api/plans", options);
}

export async function getSavings(options = {}) {
  return request("/api/savings", options);
}

export async function getWeather(options = {}) {
  return request("/api/weather", options);
}

export async function uploadCSV(file, options = {}) {
  if (!file) throw new TypeError("Please select a CSV file.");
  if (typeof File !== "undefined" && !(file instanceof File)) {
    throw new TypeError("uploadCSV expects a File object.");
  }

  const filename = String(file.name || "").toLowerCase();
  if (!filename.endsWith(".csv")) {
    throw new TypeError("Only CSV files can be uploaded.");
  }

  if (Number.isFinite(file.size) && file.size > CSV_MAX_BYTES) {
    throw new RangeError("The CSV file exceeds the 10 MB upload limit.");
  }

  const formData = new FormData();
  formData.append("file", file);

  return request("/api/upload", {
    ...options,
    method: "POST",
    body: formData,
  });
}

/**
 * Flexible simulate call supporting primitive days or payload object.
 */
export async function simulate(payload = 7, options = {}) {
  let body = undefined;
  let params = options.params || {};

  if (typeof payload === "object" && payload !== null) {
    body = payload;
  } else {
    const normalizedDays = normalizeDays(payload, { max: MAX_SIMULATION_DAYS, name: "simulation days" });
    params = { ...params, days: normalizedDays };
  }

  return request("/api/simulate", {
    ...options,
    method: "POST",
    body,
    params,
  });
}

export async function resetData(options = {}) {
  return request("/api/reset", { ...options, method: "POST" });
}


/* --------------------------------------------------------------------------
 * Generic HTTP Methods
 * -------------------------------------------------------------------------- */

export function get(path, options = {}) {
  return request(path, { ...options, method: "GET" });
}

export function post(path, body, options = {}) {
  return request(path, { ...options, body, method: "POST" });
}

export function put(path, body, options = {}) {
  return request(path, { ...options, body, method: "PUT" });
}

export function patch(path, body, options = {}) {
  return request(path, { ...options, body, method: "PATCH" });
}

export function del(path, options = {}) {
  return request(path, { ...options, method: "DELETE" });
}


/* --------------------------------------------------------------------------
 * Utilities & Namespace Export
 * -------------------------------------------------------------------------- */

export function isApiError(error) {
  return error instanceof ApiError;
}

export function isCancellationError(error) {
  return error instanceof ApiError && error.code === "REQUEST_CANCELLED";
}

export function isTimeoutError(error) {
  return error instanceof ApiError && error.code === "REQUEST_TIMEOUT";
}

export function getApiErrorMessage(error, fallback = "Something went wrong. Please try again.") {
  if (error instanceof ApiError && error.message) return error.message;
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

export const energyApi = {
  getHealth,
  getDashboard,
  getOverview,
  getReadings,
  getSummary,
  getAnalytics,
  getRecommendations,
  getForecast,
  getPlans,
  getSavings,
  getWeather,
  uploadCSV,
  simulate,
  resetData,
  get,
  post,
  put,
  patch,
  delete: del,
};