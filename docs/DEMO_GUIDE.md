# SafeRoute Demo Guide

Demonstration of the SafeRoute platform end-to-end using real project data.

---

## Prerequisites

- Python environment with dependencies from `requirements.txt`
- `.env` with `TOMTOM_API_KEY` configured
- Pipeline data present in `data/processed/`
- Port 8000 available

---

## Demo Script

### 1. Verify data pipeline integrity

```bash
cd ~/SafeRoute
python -m unittest tests.test_saferoute_pipeline -v
```

Expected: All 42 tests pass.

### 2. Check current data freshness

```bash
curl -s http://localhost:8000/api/data-status | python -m json.tool
```

Or start the backend first (step 4) and then curl.

### 3. Start the backend

```bash
cd ~/SafeRoute
uvicorn backend.main:app --reload
```

The server starts on `http://localhost:8000`.

### 4. Verify API endpoints

```bash
# Health
curl -s http://localhost:8000/api/health

# Journeys
curl -s http://localhost:8000/api/journeys

# Data status (traffic + weather freshness)
curl -s http://localhost:8000/api/data-status

# Dynamic risk summary
curl -s http://localhost:8000/api/dynamic-risk/summary
```

### 5. Open the frontend

Open `http://localhost:8000/` in a browser.

The UI shows:
- **Live Data Status panel**: Traffic and weather freshness indicators
- **Journey selector**: 5 Chennai test journeys (Chennai Central → Anna Nagar, Guindy → T Nagar, etc.)
- **Route recommendations**: Fastest, Safest, Balanced, Alternative cards
- **Map**: Leaflet map with route polylines, origin/destination markers

### 6. Run a journey comparison

1. Select a journey from the dropdown (e.g., "Chennai Central → Anna Nagar")
2. Click "Compare Routes"
3. Review route cards: time, distance, risk score
4. Click a route card to display its path on the map
5. Compare the "Fastest" vs "Safest" route — note the time/risk trade-off

### 7. Test error handling

- Select a journey and the backend handles missing data gracefully
- API errors return readable messages via HTTPException

---

## Demo Test Journeys

| ID | Origin | Destination |
|----|--------|-------------|
| 1 | Chennai Central | Anna Nagar |
| 2 | Guindy | T Nagar |
| 3 | Adyar | Perambur |
| 4 | Velachery | Tambaram |
| 5 | Chennai Airport | Marina Beach |

---

## Pipeline Refresh (Optional)

To refresh live data before the demo:

1. **Traffic refresh** (~48 min):
   ```bash
   python scripts/17_refresh_full_traffic.py
   python scripts/promote_traffic_staging.py
   ```

2. **Weather + risk** (~1 min):
   ```bash
   python scripts/19_collect_live_weather.py
   python scripts/20_assign_weather_to_roads.py
   python scripts/21_calculate_weather_risk.py
   python scripts/23_build_dynamic_risk.py
   ```

3. **Regenerate routes** (~5 min):
   ```bash
   python scripts/37_test_edge_penalty_routing.py
   python scripts/38_rank_edge_penalty_routes.py
   ```

4. **Restart backend** to load fresh data.

---

## Expected Demo Output

### Health endpoint
```json
{
  "status": "ok",
  "service": "SafeRoute",
  "recommendation_count": 15,
  "journey_count": 5,
  "graph_available": true
}
```

### Data status (when data is fresh)
```json
{
  "traffic": {
    "status": "SUCCESS",
    "freshness": "FRESH",
    "age_minutes": 5.2,
    "threshold_minutes": 30
  },
  "weather": {
    "status": "SUCCESS",
    "freshness": "FRESH",
    "age_minutes": 12.3,
    "threshold_minutes": 60
  }
}
```

### Route endpoint
```json
{
  "test_id": 1,
  "candidate_rank": 1,
  "recommendation": "Fastest",
  "travel_time_min": 14.75,
  "distance_km": 8.11,
  "risk_score": 23.84,
  "coordinates": [[80.27, 13.08], ...]
}
```

---

## Safety Disclaimer

SafeRoute is an academic prototype. Road risk scores are relative estimates based on
historical data, live traffic observations, and weather conditions. They do not guarantee
road safety or predict accidents with certainty. Always follow local traffic laws and
drive according to conditions.
