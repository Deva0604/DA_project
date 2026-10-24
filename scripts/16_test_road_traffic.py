import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv


# ============================================================
# SAFEROUTE - TEST TOMTOM TRAFFIC ON ACTUAL OSM ROADS
# ============================================================

INPUT_FILE = (
    "data/processed/road_traffic_targets.csv"
)

OUTPUT_FILE = (
    "data/processed/test_road_traffic.csv"
)

TOMTOM_URL = (
    "https://api.tomtom.com/traffic/services/4/"
    "flowSegmentData/absolute/10/json"
)


# ============================================================
# LOAD API KEY
# ============================================================

load_dotenv()

API_KEY = os.getenv("TOMTOM_API_KEY")

if not API_KEY:
    print("ERROR: TOMTOM_API_KEY not found in .env")
    sys.exit(1)


# ============================================================
# LOAD ROAD TARGETS
# ============================================================

print("=" * 70)
print("SAFEROUTE - ROAD TRAFFIC TEST")
print("=" * 70)

print()
print("[1/4] Loading road traffic targets...")

df = pd.read_csv(INPUT_FILE)

print(f"Total roads available: {len(df):,}")

# Test only first 10 roads
test_df = df.head(10).copy()

print(f"Testing roads: {len(test_df)}")


# ============================================================
# TOMTOM FUNCTION
# ============================================================

def get_traffic(latitude, longitude):

    params = {
        "point": f"{latitude},{longitude}",
        "unit": "KMPH",
        "key": API_KEY
    }

    response = requests.get(
        TOMTOM_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data.get("flowSegmentData", {})


# ============================================================
# TRAFFIC CALCULATION
# ============================================================

def calculate_congestion(
    current_speed,
    free_flow_speed
):

    if current_speed is None:
        return None

    if free_flow_speed is None:
        return None

    if free_flow_speed <= 0:
        return None

    congestion = (
        1 -
        (current_speed / free_flow_speed)
    )

    return max(
        0.0,
        min(1.0, congestion)
    )


# ============================================================
# COLLECT TRAFFIC
# ============================================================

print()
print("[2/4] Requesting TomTom traffic...")

results = []

for index, row in test_df.iterrows():

    road_number = index + 1

    latitude = row["traffic_latitude"]
    longitude = row["traffic_longitude"]

    print(
        f"[{road_number}/10] "
        f"Road {row['osm_u']} → {row['osm_v']} "
        f"@ {latitude:.6f}, {longitude:.6f}"
    )

    try:

        flow = get_traffic(
            latitude,
            longitude
        )

        current_speed = flow.get(
            "currentSpeed"
        )

        free_flow_speed = flow.get(
            "freeFlowSpeed"
        )

        current_travel_time = flow.get(
            "currentTravelTime"
        )

        free_flow_travel_time = flow.get(
            "freeFlowTravelTime"
        )

        confidence = flow.get(
            "confidence"
        )

        road_closure = flow.get(
            "roadClosure"
        )

        congestion = calculate_congestion(
            current_speed,
            free_flow_speed
        )

        traffic_risk = (
            congestion * 100
            if congestion is not None
            else None
        )

        results.append({

            "osm_u": row["osm_u"],
            "osm_v": row["osm_v"],
            "osm_key": row["osm_key"],

            "road_name": row["road_name"],
            "highway": row["highway"],

            "historical_risk": (
                row["historical_risk"]
            ),

            "traffic_latitude": latitude,
            "traffic_longitude": longitude,

            "current_speed_kmh": current_speed,
            "free_flow_speed_kmh": free_flow_speed,

            "current_travel_time_sec": (
                current_travel_time
            ),

            "free_flow_travel_time_sec": (
                free_flow_travel_time
            ),

            "traffic_confidence": confidence,

            "road_closure": road_closure,

            "congestion_ratio": congestion,

            "traffic_risk": traffic_risk,

            "traffic_status": "SUCCESS"

        })

        print(
            f"    Speed: "
            f"{current_speed} km/h | "
            f"Free flow: "
            f"{free_flow_speed} km/h | "
            f"Risk: "
            f"{traffic_risk:.2f}"
            if traffic_risk is not None
            else "    Traffic data incomplete"
        )

    except Exception as e:

        print(
            f"    ERROR: {e}"
        )

        results.append({

            "osm_u": row["osm_u"],
            "osm_v": row["osm_v"],
            "osm_key": row["osm_key"],

            "road_name": row["road_name"],
            "highway": row["highway"],

            "historical_risk": (
                row["historical_risk"]
            ),

            "traffic_latitude": latitude,
            "traffic_longitude": longitude,

            "current_speed_kmh": None,
            "free_flow_speed_kmh": None,

            "current_travel_time_sec": None,
            "free_flow_travel_time_sec": None,

            "traffic_confidence": None,

            "road_closure": None,

            "congestion_ratio": None,
            "traffic_risk": None,

            "traffic_status": "FAILED"

        })

    # Small delay to avoid hammering API
    time.sleep(0.2)


# ============================================================
# SAVE
# ============================================================

print()
print("[3/4] Saving test results...")

result_df = pd.DataFrame(results)

result_df.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("[4/4] Test summary")
print("-" * 70)

print(
    f"Total tested : "
    f"{len(result_df)}"
)

print(
    f"Successful   : "
    f"{(result_df['traffic_status'] == 'SUCCESS').sum()}"
)

print(
    f"Failed       : "
    f"{(result_df['traffic_status'] == 'FAILED').sum()}"
)

if result_df["traffic_risk"].notna().any():

    print()
    print(
        "Traffic risk statistics:"
    )

    print(
        result_df["traffic_risk"]
        .describe()
        .to_string()
    )

print()
print(
    f"Saved: {OUTPUT_FILE}"
)

print()
print("=" * 70)
print("ROAD TRAFFIC TEST COMPLETE")
print("=" * 70)
