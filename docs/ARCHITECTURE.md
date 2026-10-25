# SafeRoute Architecture

## Overview

SafeRoute is a Chennai road-risk-aware route recommendation platform. It computes
routes on demand from the OpenStreetMap graph, overlaying validated observations
(historical accident risk, TomTom traffic, Open-Meteo weather) onto matching road
edges. Routes are generated from real computed edge costs — no hardcoded paths.

## Components

### Frontend (`frontend/index.html`)

Single-page dark-theme dashboard using Leaflet for the map.
- Header: SafeRoute branding, backend connection status, data-status summary.
- KPI cards: journeys, route candidates, graph edges, observed coverage, closures,
  mean risk.
- Live-data panels: TomTom traffic and Open-Meteo weather freshness, observation
  timestamps, coverage.
- Journey selector: 5 predefined Chennai test journeys.
- Route cards: 5 categories (Fastest, Safest, Balanced, Alternative, Weather-Aware)
  with time, distance, risk, coverage, selection reason.
- Interactive map: route polylines, origin/destination markers, legend, fit-to-bounds.
- Risk analysis panel: per-component risk scores (historical/traffic/weather),
  observed vs estimated, selection reason.
- Traffic & weather panel: observed values for the selected route.
- Responsive layout for desktop and mobile.

All values come from backend API responses; no hardcoded metrics.

### Backend (`backend/main.py`, `backend/routing.py`)

FastAPI application serving the frontend and REST API.

**Endpoints:**
- `GET /` — serve frontend
- `GET /api/health` — service health, journey count, graph availability
- `GET /api/journeys` — list available test journeys
- `GET /api/recommendations/{test_id}` — legacy static recommendations (preserved)
- `GET /api/route/{test_id}/{candidate_rank}` — legacy static geometry (preserved)
- `GET /api/routes/{test_id}` — **computed route options** (5 categories)
- `GET /api/route/compute` — computed routes for arbitrary lat/lon
- `GET /api/route/{test_id}/geometry/{category}` — geometry for one category
- `GET /api/data-status` — traffic/weather freshness, observation timestamps
- `GET /api/dynamic-risk/summary` — risk statistics
- `GET /api/dynamic-risk/roads` — road-level risk data (paginated)

**Routing engine (`backend/routing.py`):**
- Loads the OSM graph once (cached via `lru_cache`).
- Builds a routing DiGraph excluding closed roads (hard constraint).
- Overlays observed risk data onto matching edges by `(osm_u, osm_v, osm_key)`.
- Non-matching edges use propagated baseline risk, flagged as `"propagated"`.
- Computes 5 route categories from distinct edge-cost objectives.
- Returns per-route metrics: geometry, distance, time, component risks, coverage,
  freshness, selection reason.

### Data Pipeline

1. Traffic collection (`scripts/17_refresh_full_traffic.py`) — TomTom API, staging,
   validation, promotion (`scripts/promote_traffic_staging.py`).
2. Weather collection (`scripts/19_collect_live_weather.py`) — Open-Meteo grid.
3. Weather-to-road assignment (`scripts/20_assign_weather_to_roads.py`) — nearest
   grid cell via Haversine.
4. Weather risk calculation (`scripts/21_calculate_weather_risk.py`).
5. Dynamic risk build (`scripts/23_build_dynamic_risk.py`) — 50/30/20 weights.

### Data Artifacts (`data/processed/`)

| File | Description | Rows |
|------|-------------|------|
| `saferoute_routing_graph_v6.graphml` | OSM road graph | 124,353 nodes / 310,248 edges |
| `road_live_traffic_full.csv` | TomTom traffic observations | 1,924 |
| `live_weather_grid.csv` | Open-Meteo weather grid | 25 |
| `road_weather_conditions.csv` | Weather assigned to roads | 1,924 |
| `road_weather_risk.csv` | Weather risk per road | 1,924 |
| `dynamic_road_risk.csv` | Combined dynamic risk | 1,924 (1,808 COMPLETE, 116 CLOSED) |
| `road_accident_risk.csv` | Historical accident risk | — |
| `ranked_saferoute_recommendations.csv` | Legacy static recommendations | 15 |

### Data Flow

```
OSM Graph ─────────┐
                   ├─► Routing DiGraph (closures excluded)
Traffic CSV ───────┼─► Overlay observed traffic risk onto matching edges
Weather CSV ───────┼─► Overlay observed weather risk onto matching edges
Accident CSV ──────┼─► Historical risk (in dynamic_road_risk.csv)
                   │
                   ▼
             Route engine (5 edge-cost objectives)
                   │
                   ▼
             FastAPI responses → Frontend dashboard
```

### Data Provenance

Every route edge carries an `observation_source` field:
- `"observed"` — validated TomTom/Open-Meteo observation matched to this edge.
- `"propagated"` — baseline estimate from graph attributes, not a live observation.

Every route reports `observed_coverage_percent` and `data_coverage_percent` so users
can distinguish live observations from fallback estimates.

### Risk Formula

`dynamic_risk = 0.50 * historical_risk + 0.30 * traffic_risk + 0.20 * weather_risk`

Weights are prototype engineering parameters, not calibrated probabilities. Missing
components are renormalized over available components; all-missing → `None`. Missing
data is never treated as zero risk.

### Failure Handling

- Unknown journey → HTTP 404.
- Invalid coordinates → HTTP 422.
- Unknown route category → HTTP 404.
- Missing datasets → HTTP 500 with detail.
- No credentials exposed in responses or logs.
- Long-running graph load cached; no data collection triggered on API requests.

### Testing

`python -m unittest tests.test_saferoute_pipeline -v` — 91 tests, all passing.
Includes unit tests, synthetic routing tests, data-refresh validation, and API
schema checks. Browser tests not run (no browser automation tooling available).
