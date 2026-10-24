import pandas as pd
import numpy as np


INPUT_FILE = "data/processed/road_weather_risk.csv"
OUTPUT_FILE = "data/processed/dynamic_road_risk.csv"


print("=" * 70)
print("SAFEROUTE - DYNAMIC ROAD RISK ENGINE")
print("=" * 70)


# ============================================================
# 1. LOAD DATA
# ============================================================

print("\n[1/6] Loading road-weather dataset...")

df = pd.read_csv(INPUT_FILE)

print(f"Road segments: {len(df):,}")


# ============================================================
# 2. CHECK REQUIRED COLUMNS
# ============================================================

print("\n[2/6] Checking required columns...")

required_columns = [
    "osm_u",
    "osm_v",
    "osm_key",
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "road_closure",
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "congestion_ratio",
    "traffic_confidence",
    "temperature_c",
    "humidity_percent",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
]

missing_columns = [
    column
    for column in required_columns
    if column not in df.columns
]

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )

print("All required columns present.")


# ============================================================
# 3. CLEAN NUMERIC VALUES
# ============================================================

print("\n[3/6] Preparing risk components...")

numeric_columns = [
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "congestion_ratio",
    "traffic_confidence",
    "temperature_c",
    "humidity_percent",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
]

for column in numeric_columns:
    df[column] = pd.to_numeric(
        df[column],
        errors="coerce"
    )


# Fill missing risk components safely
df["historical_risk"] = (
    df["historical_risk"]
    .fillna(0)
    .clip(0, 100)
)

df["traffic_risk"] = (
    df["traffic_risk"]
    .fillna(0)
    .clip(0, 100)
)

df["weather_risk"] = (
    df["weather_risk"]
    .fillna(0)
    .clip(0, 100)
)


# Convert road closure to boolean
df["road_closure"] = (
    df["road_closure"]
    .astype(str)
    .str.lower()
    .isin(["true", "1", "yes"])
)


# ============================================================
# 4. CALCULATE COMPONENT CONTRIBUTIONS
# ============================================================

print("\n[4/6] Calculating dynamic risk...")


# ------------------------------------------------------------
# WEIGHTS
# ------------------------------------------------------------
#
# Historical road risk = 50%
# Traffic risk         = 30%
# Weather risk         = 20%
#
# These are prototype engineering weights.
# They are NOT statistically calibrated probabilities.
# ------------------------------------------------------------

HISTORICAL_WEIGHT = 0.50
TRAFFIC_WEIGHT = 0.30
WEATHER_WEIGHT = 0.20


df["historical_contribution"] = (
    df["historical_risk"]
    * HISTORICAL_WEIGHT
)

df["traffic_contribution"] = (
    df["traffic_risk"]
    * TRAFFIC_WEIGHT
)

df["weather_contribution"] = (
    df["weather_risk"]
    * WEATHER_WEIGHT
)


# Base dynamic risk
df["dynamic_risk"] = (
    df["historical_contribution"]
    + df["traffic_contribution"]
    + df["weather_contribution"]
)


# ============================================================
# 5. HANDLE ROAD CLOSURES
# ============================================================

# A road closure is a hard constraint rather than simply
# another risk factor.

df.loc[
    df["road_closure"],
    "dynamic_risk"
] = 100.0


# Keep risk in 0-100 range
df["dynamic_risk"] = (
    df["dynamic_risk"]
    .clip(0, 100)
    .round(2)
)


# ============================================================
# 6. RISK CLASSIFICATION
# ============================================================

def classify_dynamic_risk(row):

    if row["road_closure"]:
        return "CLOSED"

    risk = row["dynamic_risk"]

    if risk < 20:
        return "LOW"

    elif risk < 40:
        return "MEDIUM"

    elif risk < 70:
        return "HIGH"

    else:
        return "SEVERE"


df["dynamic_risk_category"] = (
    df.apply(
        classify_dynamic_risk,
        axis=1
    )
)


# ============================================================
# 7. TRAFFIC STATUS
# ============================================================

def classify_traffic_status(risk):

    if risk < 15:
        return "LOW"

    elif risk < 35:
        return "MEDIUM"

    elif risk < 60:
        return "HIGH"

    else:
        return "SEVERE"


df["traffic_status_calculated"] = (
    df["traffic_risk"]
    .apply(classify_traffic_status)
)


# ============================================================
# 8. WEATHER STATUS
# ============================================================

def classify_weather_status(risk):

    if risk < 15:
        return "LOW"

    elif risk < 35:
        return "MEDIUM"

    elif risk < 60:
        return "HIGH"

    else:
        return "SEVERE"


df["weather_status_calculated"] = (
    df["weather_risk"]
    .apply(classify_weather_status)
)


# ============================================================
# 9. SELECT FINAL COLUMNS
# ============================================================

final_columns = [
    "osm_u",
    "osm_v",
    "osm_key",

    # Road information
    "road_name",
    "highway",
    "road_length_m",

    # Historical risk
    "accident_count",
    "fatal_count",
    "major_count",
    "minor_count",
    "historical_risk",
    "risk_category",

    # Traffic
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "current_travel_time_sec",
    "free_flow_travel_time_sec",
    "traffic_confidence",
    "road_closure",
    "congestion_ratio",
    "traffic_risk",
    "traffic_status_calculated",

    # Weather
    "weather_grid_id",
    "weather_distance_km",
    "observation_time",
    "temperature_c",
    "humidity_percent",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
    "wind_direction_deg",
    "weather_risk",
    "weather_status_calculated",

    # Dynamic risk
    "historical_contribution",
    "traffic_contribution",
    "weather_contribution",
    "dynamic_risk",
    "dynamic_risk_category",
]


# Make sure every final column exists
missing_final = [
    column
    for column in final_columns
    if column not in df.columns
]

if missing_final:
    raise ValueError(
        f"Missing final columns: {missing_final}"
    )


result = df[final_columns].copy()


# ============================================================
# 10. SAVE DATASET
# ============================================================

print("\n[5/6] Saving dynamic risk dataset...")

result.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# 11. ANALYSIS
# ============================================================

print("\n[6/6] Dynamic risk analysis...")


print("\nDynamic risk statistics:")

print(
    result["dynamic_risk"].describe()
)


print("\nDynamic risk categories:")

print(
    result["dynamic_risk_category"]
    .value_counts()
)


print("\nRoad closures:")

print(
    result["road_closure"]
    .value_counts()
)


print("\nRisk component statistics:")

print(
    result[
        [
            "historical_risk",
            "traffic_risk",
            "weather_risk",
            "dynamic_risk",
        ]
    ].describe()
)


print("\nSample:")

print(
    result[
        [
            "osm_u",
            "osm_v",
            "historical_risk",
            "traffic_risk",
            "weather_risk",
            "dynamic_risk",
            "dynamic_risk_category",
            "road_closure",
        ]
    ]
    .head(15)
    .to_string(index=False)
)


# ============================================================
# 12. EXTREME-RISK ROADS
# ============================================================

print("\nHighest-risk roads:")

highest_risk = (
    result[
        [
            "osm_u",
            "osm_v",
            "road_name",
            "historical_risk",
            "traffic_risk",
            "weather_risk",
            "dynamic_risk",
            "dynamic_risk_category",
            "road_closure",
        ]
    ]
    .sort_values(
        "dynamic_risk",
        ascending=False
    )
    .head(10)
)

print(
    highest_risk.to_string(index=False)
)


print("\n" + "=" * 70)
print("DYNAMIC ROAD RISK DATASET CREATED")
print("=" * 70)

print(f"\nRoad segments : {len(result):,}")
print(f"Output file   : {OUTPUT_FILE}")

print("\nRisk weights:")
print("Historical : 50%")
print("Traffic   : 30%")
print("Weather   : 20%")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
