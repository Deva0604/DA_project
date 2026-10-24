import os
import sys
import time

import pandas as pd
import requests
from dotenv import load_dotenv


# ============================================================
# SAFEROUTE - FULL LIVE TRAFFIC COLLECTION
# ============================================================

INPUT_FILE = (
    "data/processed/road_traffic_targets.csv"
)

OUTPUT_FILE = (
    "data/processed/road_live_traffic.csv"
)

TOMTOM_URL = (
    "https://api.tomtom.com/traffic/services/4/"
    "flowSegmentData/absolute/10/json"
)

# Number of roads processed before saving progress
SAVE_EVERY = 25

# Delay between API requests
REQUEST_DELAY = 0.25


# ============================================================
# LOAD API KEY
# ============================================================

load_dotenv()

API_KEY = os.getenv("TOMTOM_API_KEY")

if not API_KEY:
    print("ERROR: TOMTOM_API_KEY not found in .env")
    sys.exit(1)


# ============================================================
# LOAD INPUT
# ============================================================

print("=" * 70)
print("SAFEROUTE - FULL LIVE TRAFFIC COLLECTION")
print("=" * 70)

print()
print("[1/5] Loading road targets...")

df = pd.read_csv(INPUT_FILE)

print(f"Total road segments: {len(df):,}")


# ============================================================
# RESUME SUPPORT
# ============================================================

if os.path.exists(OUTPUT_FILE):

    existing = pd.read_csv(OUTPUT_FILE)

    completed_keys = set(
        zip(
            existing["osm_u"].astype(str),
            existing["osm_v"].astype(str),
            existing["osm_key"].astype(str)
        )
    )

    print(
        f"Existing traffic records: "
        f"{len(existing):,}"
    )

else:

    existing = pd.DataFrame()

    completed_keys = set()

    print("No previous traffic dataset found.")


# ============================================================
# TOMTOM REQUEST
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

    return data.get(
        "flowSegmentData",
        {}
    )


# ============================================================
# CONGESTION
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
        current_speed / free_flow_speed
    )

    return max(
        0.0,
        min(1.0, congestion)
    )


# ============================================================
# COLLECT
# ============================================================

print()
print("[2/5] Starting TomTom collection...")

results = []

processed = 0
successful = 0
failed = 0


for _, row in df.iterrows():

    key = (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"])
    )

    # Skip roads already collected
    if key in completed_keys:
        continue

    processed += 1

    latitude = row["traffic_latitude"]
    longitude = row["traffic_longitude"]

    print(
        f"[{processed}/{len(df) - len(completed_keys)}] "
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

            "road_length_m": row[
                "road_length_m"
            ],

            "accident_count": row[
                "accident_count"
            ],

            "fatal_count": row[
                "fatal_count"
            ],

            "major_count": row[
                "major_count"
            ],

            "minor_count": row[
                "minor_count"
            ],

            "historical_risk": row[
                "historical_risk"
            ],

            "risk_category": row[
                "risk_category"
            ],

            "traffic_latitude": latitude,
            "traffic_longitude": longitude,

            "current_speed_kmh": current_speed,

            "free_flow_speed_kmh": (
                free_flow_speed
            ),

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

        successful += 1

        if traffic_risk is not None:

            print(
                f"    Speed: "
                f"{current_speed} km/h | "
                f"Free flow: "
                f"{free_flow_speed} km/h | "
                f"Traffic risk: "
                f"{traffic_risk:.2f}"
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

            "road_length_m": row[
                "road_length_m"
            ],

            "accident_count": row[
                "accident_count"
            ],

            "fatal_count": row[
                "fatal_count"
            ],

            "major_count": row[
                "major_count"
            ],

            "minor_count": row[
                "minor_count"
            ],

            "historical_risk": row[
                "historical_risk"
            ],

            "risk_category": row[
                "risk_category"
            ],

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

        failed += 1


    # ========================================================
    # PERIODIC SAVE
    # ========================================================

    if (
        len(results) >= SAVE_EVERY
    ):

        new_df = pd.DataFrame(results)

        if len(existing) > 0:

            combined = pd.concat(
                [
                    existing,
                    new_df
                ],
                ignore_index=True
            )

        else:

            combined = new_df

        combined.to_csv(
            OUTPUT_FILE,
            index=False
        )

        existing = combined

        completed_keys.update(
            set(
                zip(
                    new_df["osm_u"].astype(str),
                    new_df["osm_v"].astype(str),
                    new_df["osm_key"].astype(str)
                )
            )
        )

        results = []

        print()
        print(
            f"Progress saved: "
            f"{len(existing):,} roads"
        )
        print()

    time.sleep(REQUEST_DELAY)


# ============================================================
# FINAL SAVE
# ============================================================

print()
print("[3/5] Saving final results...")

if results:

    new_df = pd.DataFrame(results)

    if len(existing) > 0:

        final_df = pd.concat(
            [
                existing,
                new_df
            ],
            ignore_index=True
        )

    else:

        final_df = new_df

else:

    final_df = existing


final_df.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("[4/5] Collection summary")
print("-" * 70)

print(
    f"Road targets       : "
    f"{len(df):,}"
)

print(
    f"Traffic records    : "
    f"{len(final_df):,}"
)

print(
    f"Successful records : "
    f"{(final_df['traffic_status'] == 'SUCCESS').sum():,}"
)

print(
    f"Failed records     : "
    f"{(final_df['traffic_status'] == 'FAILED').sum():,}"
)

valid_risk = final_df[
    "traffic_risk"
].dropna()

if len(valid_risk) > 0:

    print()
    print("Traffic risk statistics:")
    print(
        valid_risk.describe()
        .to_string()
    )


print()
print("[5/5] Output")
print("-" * 70)

print(
    f"Saved: {OUTPUT_FILE}"
)

print()
print("=" * 70)
print("FULL TRAFFIC COLLECTION COMPLETE")
print("=" * 70)
