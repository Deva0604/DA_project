# SafeRoute — Real-Time Road Risk Mapping & Safer Route Recommendation Platform

SafeRoute recommends safer routes through Chennai by combining historical road accident risk,
live TomTom traffic information, weather conditions from Open-Meteo, and road-network data from
OpenStreetMap into a weighted dynamic road-risk score.

**This is an academic prototype.** Risk scores are relative estimates, not guarantees of safety
or predictions of accidents.

---

## Repository Structure

```
SafeRoute/
├── backend/
│   └── main.py                 # FastAPI application
├── data/
│   ├── processed/              # Processed datasets (CSV, GraphML)
│   ├── raw/                    # Raw input data
│   └── final/                  # Final outputs
├── docs/
│   ├── PROJECT_COMPLETION_CHECKLIST.md
│   └── DEMO_GUIDE.md
├── frontend/
│   └── index.html              # Leaflet-based web UI
├── scripts/                    # Data pipeline scripts (01-52)
├── tests/                      # Unit tests
├── backups/                    # Script and data backups
├── .env                        # API keys (TOMTOM_API_KEY)
├── requirements.txt            # Python dependencies
└── README.md
```

---

## Key Data Files

| File | Description | Rows |
|------|-------------|------|
| `data/processed/road_traffic_targets.csv` | Target road segments for traffic refresh | 1,924 |
| `data/processed/road_live_traffic_full.csv` | Production live traffic observations | 1,924 |
| `data/processed/live_weather_grid.csv` | Weather grid observations (Open-Meteo) | 25 |
| `data/processed/road_weather_conditions.csv` | Weather assigned to road segments | 1,924 |
| `data/processed/road_weather_risk.csv` | Weather risk per road segment | 1,924 |
| `data/processed/dynamic_road_risk.csv` | Combined dynamic risk (hist+traffic+weather) | 1,924 |
| `data/processed/ranked_saferoute_recommendations.csv` | Route recommendations | 15 |
| `data/processed/saferoute_routing_graph_v6.graphml` | Chennai road network graph | ~124k nodes, ~310k edges |

---

## Pipeline Execution Order

Run in this order. Each step must succeed before the next.

1. **Validate targets and existing data**
   ```bash
   python -m unittest tests.test_saferoute_pipeline -v
   ```

2. **Collect fresh live traffic into staging** (~48 minutes for 1,924 roads)
   ```bash
   python scripts/17_refresh_full_traffic.py
   ```
   Writes to `data/processed/road_live_traffic_full_refresh_staging.csv`.
   Checkpoints every 5 roads. Stops on HTTP 401/403/429.

3. **Validate and promote staging to production**
   ```bash
   python scripts/promote_traffic_staging.py
   ```
   Validates staging (1,924 rows, unique keys, all SUCCESS, fresh timestamps,
   valid speeds/congestion/risk). Backs up production before atomic replacement.

4. **Collect fresh weather**
   ```bash
   python scripts/19_collect_live_weather.py
   ```
   Collects from Open-Meteo for 25 grid points. Converts Asia/Kolkata → UTC.
   Atomic publish after validation.

5. **Assign weather to roads**
   ```bash
   python scripts/20_assign_weather_to_roads.py
   ```
   Assigns nearest weather grid point to each road segment. Blocks if traffic
   observations are stale (>180 minutes). Atomic publish.

6. **Calculate weather risk**
   ```bash
   python scripts/21_calculate_weather_risk.py
   ```
   Combines rain, weather code, wind, humidity into weather_risk (0-100).

7. **Build dynamic road risk**
   ```bash
   python scripts/23_build_dynamic_risk.py
   ```
   Combines historical (50%), traffic (30%), weather (20%) into dynamic_risk.
   Coverage threshold: 90% complete.

8. **Generate route candidates**
   ```bash
   python scripts/37_test_edge_penalty_routing.py
   ```
   Generates diverse risk-aware routes for 5 test journeys using dynamic edge risk.

9. **Rank routes**
   ```bash
   python scripts/38_rank_edge_penalty_routes.py
   ```
   Selects Fastest/Safest/Balanced recommendations per journey.

10. **Start the backend**
    ```bash
    uvicorn backend.main:app --reload
    ```

11. **Test API endpoints**
    ```bash
    curl http://localhost:8000/api/health
    curl http://localhost:8000/api/data-status
    ```

12. **Open the frontend**
    Open `http://localhost:8000/` in a browser.

---

## Scripts Reference

| Script | Purpose |
|--------|---------|
| `17_refresh_full_traffic.py` | Full TomTom traffic refresh into staging |
| `18_retry_failed_traffic.py` | Retry failed traffic observations |
| `19_collect_live_weather.py` | Open-Meteo weather grid collection (hardened) |
| `20_assign_weather_to_roads.py` | Assign weather to road segments (hardened) |
| `21_calculate_weather_risk.py` | Calculate weather risk per road |
| `23_build_dynamic_risk.py` | Build dynamic road risk (50/30/20 weights) |
| `37_test_edge_penalty_routing.py` | Generate risk-aware route candidates |
| `38_rank_edge_penalty_routes.py` | Rank and select route recommendations |
| `promote_traffic_staging.py` | Validate and promote traffic staging to production |

---

## Backend API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Serve frontend index.html |
| `GET /api/health` | Service health and dataset counts |
| `GET /api/journeys` | List available test journeys |
| `GET /api/recommendations/{test_id}` | Route recommendations for a journey |
| `GET /api/route/{test_id}/{candidate_rank}` | Route geometry for a specific route |
| `GET /api/data-status` | Traffic and weather freshness status |
| `GET /api/dynamic-risk/summary` | Dynamic risk summary statistics |
| `GET /api/dynamic-risk/roads` | Road-level risk data (paginated) |

---

## Dynamic Risk Formula

```
dynamic_risk = 0.50 × historical_risk + 0.30 × traffic_risk + 0.20 × weather_risk
```

- **Historical risk (50%)**: Based on road accident history
- **Traffic risk (30%)**: Based on current TomTom congestion
- **Weather risk (20%)**: Based on current Open-Meteo conditions

All components use a 0–100 scale. Closed roads are assigned dynamic_risk = 100.0.
Risk categories: LOW (<20), MEDIUM (<40), HIGH (<70), SEVERE (≥70).

These are prototype engineering weights, not calibrated probabilities.

---

## Data Freshness

- **Traffic freshness threshold**: 180 minutes (configurable via `SAFEROUTE_TRAFFIC_FRESHNESS_MINUTES`). Aligned with the pipeline freshness window; traffic observations within this window are shown as FRESH.
- **Weather freshness threshold**: 60 minutes (configurable via `SAFEROUTE_WEATHER_FRESHNESS_MINUTES`).
- **Traffic assignment block**: Weather-to-road assignment blocks if traffic observations are older than 180 minutes.

---

## Running Tests

```bash
python -m unittest tests.test_saferoute_pipeline -v
```

Tests cover: traffic timestamp validation, duplicate key rejection, API failure handling,
staging validation, weather validation, weather-to-road assignment, dynamic risk calculation,
routing graph validation, backend schema compatibility.

---

## Configuration

API key is configured in `.env`:
```
TOMTOM_API_KEY=your_key_here
```

The API key is never logged or displayed by any script.

---

## Safety Disclaimer

SafeRoute is an academic prototype. Road risk scores are relative estimates based on
historical data, live traffic observations, and weather conditions. They do not guarantee
road safety or predict accidents with certainty. Always follow local traffic laws and
drive according to conditions.
