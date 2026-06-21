# Dispatch optimizer (OR-Tools)

The dispatch engine has two implementations, selected **per restaurant**:

| Engine | How it plans | When to use |
|--------|--------------|-------------|
| `greedy` (default) | Proximity batching + per-batch rider scoring (spec §4.3) | Low order volume; safe default |
| `ortools` | SLA-first vehicle-routing solve (`app/dispatch/optimizer.py`) | Medium density (5–20 concurrent orders, 3–10 riders) |

## What the optimizer does

- **Hard SLA constraint.** Every routed order's projected completion must be within the
  customer SLA (`sla_customer_minutes`, default 40). Implemented as a time-dimension
  cumulative-time upper bound of `40 − minutes_elapsed` per delivery node.
- **Cost tiebreak.** Among all SLA-feasible plans, the solver minimizes total rider
  drive time.
- **Best-effort partial.** Orders that cannot be served on time are *dropped* (high-
  penalty disjunctions) and returned as unassigned — they never block the rest. Dropped
  **ready** orders raise a manager breach alert; the order stays `ready`.
- **Priority orders** get their own dedicated nearest rider, served first (never batched).
- **Re-optimization (phase 3b).** Assigned-but-not-yet-picked orders are folded back into
  the solve, *locked to their current rider* (never moved cross-rider). A new nearby order
  can be inserted into a busy rider's route instead of waiting for a free rider. Routes are
  rebuilt only when they actually change (no churn); when a re-plan shifts a customer's ETA
  by more than 5 minutes the customer is messaged. `picked_up` / `arriving` orders are
  never touched.

The rider→restaurant pickup leg is **not** modeled in the time dimension — per spec
§4.3.4 that is handled by rider scoring, and the SLA promise is measured from order
confirm. All vehicles start at the depot (restaurant) with cumulative time 0.

## Enabling it for a restaurant

The flag lives in `Restaurant.settings` (JSONB) — no migration, no deploy:

```sql
UPDATE restaurants
SET settings = jsonb_set(settings, '{dispatch_engine}', '"ortools"')
WHERE id = <restaurant_id>;
```

Revert by setting it back to `"greedy"` (or removing the key — it reads as greedy).

## Shadow mode (evaluate before flipping)

Set the global env flag to run the optimizer **in-memory, no writes** alongside greedy
and log what it would have done:

```
APP_DISPATCH_SHADOW_COMPARE=true
```

Each dispatch on a greedy restaurant then logs a line like:

```
dispatch shadow-compare restaurant=12 orders=7 | greedy: 3 batches / 7 served | ortools: 2 routes / 7 served / 0 dropped
```

Compare served/dropped counts over real traffic, then flip the per-restaurant flag.

## Metrics (Prometheus, `/metrics`)

| Metric | Labels | Meaning |
|--------|--------|---------|
| `dispatch_runs_total` | `engine` | Dispatch engine invocations |
| `dispatch_orders_total` | `engine`, `outcome` (`assigned`/`dropped`) | Orders processed |
| `dispatch_solve_seconds` | `engine` (`greedy`/`ortools`/`ortools_shadow`) | Plan computation wall time |

## Tuning

- Solve time limit is `time_limit_seconds=3` in `optimize_dispatch`. Guided local search
  runs to the limit even on tiny inputs; if dispatch latency matters at low volume, add a
  `solution_limit` to stop early.
- Travel times use the configured geo provider (`google_maps` traffic-aware) or the
  haversine + static city-speed fallback, same as the greedy batcher.
