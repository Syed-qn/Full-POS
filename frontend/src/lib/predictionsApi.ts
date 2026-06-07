import { ApiError, apiClient } from "./apiClient";

// ── Types (mirrored from src/app/predictions/schemas.py) ────────────────────

export interface ForecastResult {
  run_id: number;
  horizon: string;
  target_date: string;
  predictions: Record<string, unknown>;
  adjusted: boolean;
}

export interface ForecastRun {
  run_id: number;
  horizon: string;
  target_date: string;
}

export interface PrepAheadItem {
  dish_id: number;
  dish_name: string;
  predicted_qty: number;
  confidence: string;
}

// ── API functions ────────────────────────────────────────────────────────────

/**
 * GET /api/v1/predictions/latest?horizon=<horizon>
 * Returns null when no forecast exists yet for the given horizon (404).
 */
export async function fetchLatestForecast(horizon: string): Promise<ForecastResult | null> {
  try {
    return await apiClient.get<ForecastResult>(`/api/v1/predictions/latest?horizon=${encodeURIComponent(horizon)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}

/**
 * GET /api/v1/predictions/runs?limit=<limit>
 * Returns the most recent forecast run summaries (default 20).
 */
export async function fetchForecastRuns(limit = 20): Promise<ForecastRun[]> {
  return apiClient.get<ForecastRun[]>(`/api/v1/predictions/runs?limit=${limit}`);
}

/**
 * GET /api/v1/predictions/prep-ahead?horizon=<horizon>
 * Returns prep-ahead suggestions for the given horizon.
 * Returns null when no forecast run exists yet (404).
 */
export async function fetchPrepAheadAdvice(horizon = "lunch"): Promise<PrepAheadItem[] | null> {
  try {
    return await apiClient.get<PrepAheadItem[]>(`/api/v1/predictions/prep-ahead?horizon=${encodeURIComponent(horizon)}`);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
