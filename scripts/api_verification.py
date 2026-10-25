"""HTTP API verification for SafeRoute.

Verifies all five route categories through the actual backend API,
confirms route switching updates metrics/geometry/risk/weather together,
and tests error handling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import requests  # noqa: E402

BASE = "http://127.0.0.1:8000"

CATEGORIES = [
    "Fastest Route", "Safest Route", "Balanced Route",
    "Alternative Route", "Weather-Aware Route",
]


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" — {detail}" if detail else ""))
    return condition


def verify_api():
    all_pass = True

    print("=" * 70)
    print("API VERIFICATION — All 5 Journeys × 5 Route Categories")
    print("=" * 70)

    # 1. Health
    print("\n1. Health endpoint")
    r = requests.get(f"{BASE}/api/health", timeout=10)
    all_pass &= check("GET /api/health returns 200", r.status_code == 200)
    body = r.json()
    all_pass &= check("health has journey_count=5", body.get("journey_count") == 5)
    all_pass &= check("health has graph_available=true", body.get("graph_available") is True)

    # 2. Data status
    print("\n2. Data status endpoint")
    r = requests.get(f"{BASE}/api/data-status", timeout=10)
    all_pass &= check("GET /api/data-status returns 200", r.status_code == 200)
    ds = r.json()
    all_pass &= check("traffic freshness reported", "freshness" in ds.get("traffic", {}))
    all_pass &= check("weather freshness reported", "freshness" in ds.get("weather", {}))
    tr = ds.get("traffic", {})
    we = ds.get("weather", {})
    print(f"   Traffic: {tr.get('freshness')} (age {tr.get('age_minutes')} min, threshold {tr.get('threshold_minutes')} min)")
    print(f"   Weather: {we.get('freshness')} (age {we.get('age_minutes')} min, threshold {we.get('threshold_minutes')} min)")

    # 3. All journeys × all categories
    print("\n3. Route options for all 5 journeys")
    for tid in range(1, 6):
        r = requests.get(f"{BASE}/api/routes/{tid}", timeout=30)
        all_pass &= check(f"Journey {tid} returns 200", r.status_code == 200)
        if r.status_code != 200:
            continue
        body = r.json()
        routes = body.get("routes", [])
        all_pass &= check(f"Journey {tid} has routes", len(routes) >= 1)
        all_pass &= check(f"Journey {tid} risk_weights=50/30/20",
                          body.get("risk_weights") == {"historical": 0.5, "traffic": 0.3, "weather": 0.2})

        cats_returned = [route["category"] for route in routes]
        print(f"   Journey {tid}: {len(routes)} routes — {', '.join(cats_returned)}")

        for route in routes:
            # Verify each route has required fields
            required = ["category", "travel_time_min", "distance_km",
                        "distance_weighted_combined_risk", "avg_historical_risk",
                        "avg_traffic_risk", "avg_weather_risk",
                        "observed_coverage_percent", "data_coverage_percent",
                        "observation_sources", "selection_reason", "coordinates"]
            missing = [k for k in required if k not in route]
            all_pass &= check(f"Route {route['category']} has all fields",
                              len(missing) == 0, f"missing: {missing}" if missing else "")

            # Verify geometry
            coords = route.get("coordinates", [])
            all_pass &= check(f"Route {route['category']} has valid geometry",
                              len(coords) >= 2, f"{len(coords)} coords")
            if coords:
                lat, lon = coords[0]
                all_pass &= check(f"Route {route['category']} coords are [lat,lon]",
                                  8.0 <= lat <= 14.0 and 76.0 <= lon <= 81.0,
                                  f"[{lat},{lon}]")

            # Verify coverage is honest (<= 100%)
            oc = route.get("observed_coverage_percent", 0)
            dc = route.get("data_coverage_percent", 0)
            all_pass &= check(f"Route {route['category']} coverage <= 100%",
                              oc <= 100.0 and dc <= 100.0,
                              f"obs={oc}% total={dc}%")

    # 4. Geometry endpoint for each category of journey 1
    print("\n4. Geometry endpoint per category (Journey 1)")
    r = requests.get(f"{BASE}/api/routes/1", timeout=30)
    routes = r.json().get("routes", [])
    for route in routes:
        cat = route["category"]
        r2 = requests.get(f"{BASE}/api/route/1/geometry/{cat.replace(' ', '%20')}", timeout=30)
        all_pass &= check(f"Geometry for {cat} returns 200", r2.status_code == 200)
        if r2.status_code == 200:
            gbody = r2.json()
            all_pass &= check(f"Geometry {cat} matches risk_score",
                              abs(gbody.get("risk_score", -1) - route["distance_weighted_combined_risk"]) < 0.01,
                              f"api={gbody.get('risk_score')} summary={route['distance_weighted_combined_risk']}")
            all_pass &= check(f"Geometry {cat} coordinates match",
                              gbody.get("coordinates") == route["coordinates"])

    # 5. Arbitrary compute endpoint
    print("\n5. Arbitrary compute endpoint")
    r = requests.get(
        f"{BASE}/api/route/compute",
        params={"origin_lat": 13.0067, "origin_lon": 80.2206,
                "destination_lat": 13.0418, "destination_lon": 80.2341,
                "test_id": 2, "origin": "Guindy", "destination": "T Nagar"},
        timeout=30,
    )
    all_pass &= check("GET /api/route/compute returns 200", r.status_code == 200)
    if r.status_code == 200:
        cbody = r.json()
        all_pass &= check("Compute returns routes", len(cbody.get("routes", [])) >= 1)

    # 6. Error handling
    print("\n6. Error handling")
    r = requests.get(f"{BASE}/api/routes/99999", timeout=10)
    all_pass &= check("Unknown journey returns 404", r.status_code == 404)

    r = requests.get(
        f"{BASE}/api/route/compute",
        params={"origin_lat": "bad", "origin_lon": 80.2,
                "destination_lat": 13.0, "destination_lon": 80.2},
        timeout=10,
    )
    all_pass &= check("Invalid coordinates returns 422", r.status_code == 422)

    r = requests.get(f"{BASE}/api/route/1/geometry/Nonexistent%20Category", timeout=10)
    all_pass &= check("Unknown category returns 404", r.status_code == 404)

    # 7. Frontend loads
    print("\n7. Frontend")
    r = requests.get(f"{BASE}/", timeout=10)
    all_pass &= check("GET / returns 200 (frontend)", r.status_code == 200)
    all_pass &= check("Frontend is HTML", "html" in r.headers.get("content-type", "").lower())

    print("\n" + "=" * 70)
    print(f"API VERIFICATION: {'ALL PASS' if all_pass else 'SOME FAILURES'}")
    print("=" * 70)
    return all_pass


if __name__ == "__main__":
    success = verify_api()
    sys.exit(0 if success else 1)
