# SafeRoute Demo Guide

Demonstration of the SafeRoute platform end-to-end using real project data.

---

## Prerequisites

- Python environment with dependencies from `requirements.txt`
- `.env` with `TOMTOM_API_KEY` configured (only needed to refresh live traffic)
- Pipeline data present in `data/processed/`
- Port 8000 available

---

## 1. Verify data pipeline integrity

```bash
cd ~/SafeRoute
python -m unittest tests.test_saferoute_pipeline -v
```

Expected: All 70 tests pass.

---

## 2. Start the backend

```bash
cd ~/SafeRoute
uvicorn backend.main:app --reload
```

The server starts on `http://localhost:8000`.

---

## 3. Verify API endpoints

```bash
# Health
curl -s http://localhost:8000/api/health

# Journeys
curl -s http://localhost:8000/api/journeys

# Data status (traffic + weather freshness, uses configured thresholds)
curl -s http://localhost:8000/api/data-status

# Dynamic risk summary
curl -s http://localhost:8000/api/dynamic-risk/summary

# Computed route options for a journey (all categories)
curl -s "http://localhost:8000/api/routes/1"

# Geometry for a specific route category
curl -s "http://localhost:8000/api/route/1/geometry/Safest%20Route"

# Arbitrary origin/destination routing
curl -s "http://localhost:8000/api/route/compute?origin_lat=13.0067&origin_lon=80.2206&destination_lat=13.0418&destination_lon=80.2341"
```

---

## 4. Open the frontend

Open `http://localhost:8000/` in a browser.

The UI shows:
- **Header**: SafeRoute branding, backend connection status
- **KPI cards**: journeys, route options, road coverage, closures, mean dynamic risk
- **Live Data panels**: TomTom traffic freshness, Open-Meteo weather freshness, risk model weights (50/30/20)
- **Journey selector**: 5 Chennai test journeys
- **Route cards**: Fastest, Safest, Balanced, Alternative, Weather-Aware
- **Map**: Leaflet map with route polylines, origin/destination markers, legend
- **Risk analysis panel**: component risk scores (historical / traffic / weather) for the selected route
- **Traffic & weather panel**: observed values used along the selected route

---

## 5. Run a journey comparison

1. Select a journey from the dropdown (e.g., "Chennai Central → Anna Nagar")
2. Click "Compare Routes"
3. Review route cards: time, distance, risk, coverage, reason
4. Click a route card to display its path on the map
5. Compare "Fastest" vs "Safest" — note the time/risk trade-off
6. Check the risk analysis and traffic/weather panels for the selected route

---

## 6. Test error handling

- Unknown journey ID → `GET /api/routes/99999` returns 404
- Invalid coordinates → `GET /api/route/compute` with bad params returns 422
- Missing route geometry handled gracefully in the UI

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

1. **Traffic refresh** (~48 min for 1,924 roads):
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

3. **Restart backend** to load fresh data:
   ```bash
   # restart uvicorn
   ```

The routing engine reads `data/processed/dynamic_road_risk.csv` on every request, so no route regeneration script is needed for computed routes.

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

### Routes endpoint (per journey, 5 categories)
```json
{
  "test_id": 1,
  "origin": "Chennai Central",
  "destination": "Anna Nagar",
  "routes": [
    {
      "category": "Fastest Route",
      "travel_time_min": 14.62,
      "distance_km": 7.55,
      "distance_weighted_combined_risk": 27.42,
      "avg_historical_risk": 28.88,
      "avg_traffic_risk": 17.27,
      "avg_weather_risk": 0.0,
      "congestion_ratio": null,
      "observed_coverage_percent": 0.0,
      "data_coverage_percent": 100.0,
      "coordinates": [[13.08, 80.27], ...],
      "selection_reason": "shortest estimated travel time"
    },
    {
      "category": "Safest Route",
      "travel_time_min": 23.29,
      "distance_km": 9.92,
      "distance_weighted_combined_risk": 15.01,
      ...
    }
  ],
  "risk_weights": {"historical": 0.5, "traffic": 0.3, "weather": 0.2}
}
```

---

## Safety Disclaimer

SafeRoute is an academic prototype. Road risk scores are relative estimates based on
historical data, live traffic observations, and weather conditions. They do not guarantee
road safety or predict accidents with certainty. Always follow local traffic laws and
drive according to conditions.

Browser verification: NOT TESTED (no browser automation available in environment).
Manual verification steps are documented above. Frontend JavaScript is syntax-validated
and all API responses verified over live HTTP.
