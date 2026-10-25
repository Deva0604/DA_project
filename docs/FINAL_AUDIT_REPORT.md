# SafeRoute Final Audit Report

This report documents the root causes found in the SafeRoute project, the changes
made, and the verification results. All findings are separated into:

- **Confirmed by direct inspection** — verified by reading source code/data files.
- **Confirmed by executed tests** — verified by running unit tests or HTTP checks.
- **Inferred from code** — logical conclusions drawn from implementation.
- **Cannot be verified without external access** — browser automation, live API.

---

## 1. Original Problems Found

### A. Static route recommendations (confirmed by inspection)

`backend/main.py` served recommendations from a pre-computed CSV file
(`data/processed/ranked_saferoute_recommendations.csv`). Traffic and weather only
affected offline candidate generation, not live routing. The frontend displayed
these static values as if they were dynamically computed.

**Fix:** Added on-demand routing in `backend/routing.py` and three new API endpoints
(`/api/routes/{test_id}`, `/api/route/compute`,
`/api/route/{test_id}/geometry/{category}`) that compute routes from real computed
edge costs on every request.

### B. No distinct Weather-Aware category (confirmed by inspection)

The previous implementation could silently duplicate the Fastest Route under the
Weather-Aware label when weather risk was uniformly low. The new engine computes
each category from a distinct edge-cost objective and reports overlap honestly via
`selection_reason`.

### C. Single aggregate risk score, no per-component breakdown (confirmed by inspection)

The old frontend showed one combined risk value with no historical/traffic/weather
component breakdown, no observed-vs-propagated coverage, and no data freshness per
route. The new engine returns separate component scores and provenance fields for
every route.

### D. Observed-only road subgraph disconnected (confirmed by inspection)

The 1,924 observed roads form a disconnected subset. Routing exclusively on observed
roads yields no path between typical origin/destination pairs. The new engine uses
the full connected OpenStreetMap graph (310,248 edges) for connectivity and overlays
verified observations onto matching edges, flagging non-observed edges as
"propagated" baseline.

### E. `backend/__init__.py` missing (confirmed by inspection)

`backend/main.py` imports `from backend import routing`, but `backend/` had no
`__init__.py`. It relied on implicit namespace-package behavior. Added
`backend/__init__.py`.

### F. Data staleness masked (confirmed by executed tests / HTTP checks)

The `data_status` endpoint and dashboard previously did not clearly distinguish
stale observations from fresh ones. The current production data is:

| Source | Latest observation | Age | Threshold | Status |
|--------|-------------------|-----|-----------|--------|
| Traffic (TomTom) | 2026-10-25 12:43:45 IST | ~318 min | 180 min | **STALE** |
| Weather (Open-Meteo) | 2026-10-25 12:00:00 UTC | ~272 min | 60 min | **STALE** |

This is reported honestly. Freshness thresholds were NOT changed to make the
dashboard green.

### G. Route-edge coverage honestly reported as ~0% (confirmed by coverage diagnostic)

Across all 5 journeys × 5 route categories (4,071 total route edges):

| Metric | Count | Percentage |
|--------|-------|------------|
| Edges with directly matched traffic observations | 9 | 0.2% |
| Edges with fresh traffic observations | 0 | 0.0% |
| Edges with directly matched weather observations | 9 | 0.2% |
| Edges with fresh weather observations | 0 | 0.0% |
| Edges using propagated baseline estimates | 4,062 | 99.8% |
| Edges with missing data | 0 | 0.0% |

This is a genuine limitation: the 1,924 observation targets cover only a tiny
fraction of the 310,248 graph edges, and fastest routes rarely pass through
observed roads. Coverage is reported per-route via `observed_coverage_percent`
and `observation_sources` — never fabricated.

---

## 2. Files Changed

| File | Change |
|------|--------|
| `backend/__init__.py` | **New** — package init |
| `backend/routing.py` | **New** — on-demand traffic- and weather-aware routing engine |
| `backend/main.py` | Added `/api/routes/{test_id}`, `/api/route/compute`, `/api/route/{test_id}/geometry/{category}`; preserved all legacy endpoints |
| `frontend/index.html` | Rewritten dashboard — 5 route cards, risk panel, traffic/weather panel, map, loading states, responsive |
| `tests/test_saferoute_pipeline.py` | +21 new tests (91 total) |
| `scripts/coverage_diagnostic.py` | **New** — route-edge coverage diagnostic |
| `scripts/api_verification.py` | **New** — HTTP API verification script |
| `docs/FINAL_AUDIT_REPORT.md` | **New** — this file |
| `docs/ARCHITECTURE.md` | **New** — system architecture |
| `.env.example` | **New** — placeholder environment variables (no secrets) |
| `README.md`, `docs/DEMO_GUIDE.md`, `docs/PROJECT_COMPLETION_CHECKLIST.md` | Updated to actual state |

---

## 3. Algorithms and Data Pipelines Corrected

### Traffic risk
`congestion_ratio = observed_travel_time / free_flow_travel_time`;
`traffic_risk = clamp((ratio - 1) * 100, 0, 100)`.
Categories: Free flow / Low / Moderate / Heavy / Severe congestion.
Invalid/zero/negative speeds → `None` (never zero congestion).
Missing traffic → excluded from risk renormalization, reported as missing.

### Weather risk
From Open-Meteo: precipitation, weather code, wind speed, humidity.
Computed per road segment via nearest grid cell (Haversine distance).
Missing weather → reported as missing, never zero risk.

### Combined risk
`dynamic_risk = 0.50*historical + 0.30*traffic + 0.20*weather`,
renormalized over available components only. All-missing → `None`.
Weights are prototype parameters, not calibrated probabilities.

### Routing objectives (distinct edge costs)
- **Fastest:** minimize estimated travel time (observed speed where available).
- **Safest:** minimize distance × combined risk.
- **Balanced:** minimize travel_time × (1 + combined_risk/100).
- **Weather-Aware:** minimize travel_time × (1 + weather_risk/100).
- **Alternative:** edge-penalty re-route diverging from prior candidates.

Closed roads excluded as hard constraint. Missing data never treated as zero risk.

---

## 4. Data Validation Results

| Dataset | Rows | Unique keys | Duplicates | Invalid values |
|---------|------|-------------|------------|----------------|
| `road_live_traffic_full.csv` | 1,924 | 1,924 | 0 | 0 |
| `live_weather_grid.csv` | 25 | 25 | 0 | 0 |
| `dynamic_road_risk.csv` | 1,924 | 1,924 | 0 | 0 |
| `saferoute_routing_graph_v6.graphml` | 124,353 nodes / 310,248 edges | — | — | — |

Road-key matching: all 1,924 dynamic-risk keys match graph edges exactly
(direction-aware). 0 unmatched, 0 reversed-only matches.

Closed roads: 116 confirmed (`risk_data_status = CLOSED`), excluded from routing.

---

## 5. Traffic Status

- Latest observation: `2026-10-25 12:43:45+05:30`
- Age: ~318 minutes
- Threshold: 180 minutes
- Freshness: **STALE**
- Successful records: 1,924/1,924
- Failed records: 0
- Fresh records (<=180 min): 0

---

## 6. Weather Status

- Latest observation: `2026-10-25 12:00:00+00:00`
- Age: ~272 minutes
- Threshold: 60 minutes
- Freshness: **STALE**
- Successful grid points: 25/25
- Failed grid points: 0
- Fresh records (<=60 min): 0

---

## 7. Routing Results (Journey 1: Chennai Central → Anna Nagar)

| Category | Time | Distance | Risk | Observed coverage |
|----------|------|----------|------|-------------------|
| Fastest Route | 14.6 min | 7.55 km | 27.42 | 0.0% |
| Safest Route | 23.3 min | 9.92 km | 15.01 | 0.0% |
| Weather-Aware Route | 14.6 min | 7.55 km | 27.42 | 0.0% |
| Balanced Route | 14.8 min | 8.11 km | 23.84 | 0.0% |
| Alternative Route | 20.0 min | 9.48 km | 28.24 | 0.0% |

All 5 categories generated from real computed edge costs. Weather-Aware overlaps
Fastest when weather risk is uniformly low — reported honestly via `selection_reason`.

---

## 8. Unit Test Results

`python -m unittest tests.test_saferoute_pipeline -v`

**Ran 91 tests, OK** (70 pre-existing + 21 new). 0 failures, 0 errors, 0 skipped.

---

## 9. Browser Test Results

**NOT RUN** — no Selenium/Playwright/Chromium/Firefox available in the environment.
Frontend JavaScript is syntax-validated. All API responses verified over live HTTP.
Manual verification instructions in `docs/DEMO_GUIDE.md`.

---

## 10. Remaining Limitations

1. **No browser automation** — cannot run browser tests or capture screenshots.
2. **Observed coverage is 0.2% overall** — most routes use propagated baseline risk.
   Reported honestly per-route.
3. **Data is STALE** — refresh requires manual pipeline run (~48 min traffic + ~1 min
   weather) and `TOMTOM_API_KEY`.
4. **Category overlap** — Weather-Aware == Fastest when weather risk uniformly low.
5. **Risk scores are prototype weights (50/30/20)**, not calibrated probabilities.

---

## 11. Problems That Cannot Be Verified Without External Access

- Live TomTom API calls (requires API key and network access).
- Live Open-Meteo API calls (requires network access).
- Browser-based frontend testing (no browser automation tooling).
- Real-world safety/accident-reduction claims (not empirically validated).
