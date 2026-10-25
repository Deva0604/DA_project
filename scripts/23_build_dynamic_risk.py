import os
import pandas as pd
import numpy as np

WEATHER_FILE = "data/processed/road_weather_risk.csv"
TRAFFIC_FILE = "data/processed/road_live_traffic_full.csv"
OUTPUT_FILE = "data/processed/dynamic_road_risk.csv"

KEYS = ["osm_u", "osm_v", "osm_key"]

HISTORICAL_WEIGHT = 0.50
TRAFFIC_WEIGHT = 0.30
WEATHER_WEIGHT = 0.20

# Refresh validation safeguards
MIN_COMPLETE_COVERAGE = 0.90
MIN_RISK_SCORE = 0.0
MAX_RISK_SCORE = 100.0

print("=" * 70)
print("SAFEROUTE - DYNAMIC ROAD RISK ENGINE")
print("=" * 70)

# ------------------------------------------------------------
# 1. LOAD INPUTS
# ------------------------------------------------------------
print("\n[1/7] Loading weather-risk and refreshed traffic datasets...")

weather = pd.read_csv(WEATHER_FILE)
traffic = pd.read_csv(TRAFFIC_FILE)

for name, df in [("weather", weather), ("traffic", traffic)]:
    missing = [c for c in KEYS if c not in df.columns]
    if missing:
        raise ValueError(f"{name} dataset missing road keys: {missing}")

    if df[KEYS].isna().any().any():
        raise ValueError(f"{name} dataset contains missing road identifiers.")

    if df.duplicated(KEYS).any():
        raise ValueError(f"{name} dataset contains duplicate road identifiers.")

print("Weather-risk roads:", len(weather))
print("Traffic roads:", len(traffic))

# ------------------------------------------------------------
# 2. REPLACE STALE TRAFFIC DATA
# ------------------------------------------------------------
print("\n[2/7] Merging refreshed traffic readings by road identifiers...")

traffic_columns = [
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "current_travel_time_sec",
    "free_flow_travel_time_sec",
    "traffic_confidence",
    "road_closure",
    "congestion_ratio",
    "traffic_risk",
    "traffic_status",
    "traffic_observation_time",
    "traffic_http_status",
    "traffic_error",
]

missing_traffic_columns = [
    c for c in traffic_columns if c not in traffic.columns
]
if missing_traffic_columns:
    raise ValueError(
        f"Traffic dataset missing columns: {missing_traffic_columns}"
    )

# Remove older traffic fields from the weather dataset.
# Historical risk and weather measurements remain untouched.
stale_traffic_columns = [
    c for c in traffic_columns if c in weather.columns
]
base = weather.drop(columns=stale_traffic_columns)

fresh_traffic = traffic[KEYS + traffic_columns].copy()

df = base.merge(
    fresh_traffic,
    on=KEYS,
    how="left",
    validate="one_to_one",
    indicator=True,
)

unmatched = int((df["_merge"] != "both").sum())
df.drop(columns=["_merge"], inplace=True)

if unmatched:
    raise ValueError(
        f"{unmatched} weather roads have no matching traffic record. "
        "Output was not written."
    )

if len(df) != len(weather):
    raise ValueError("Unexpected row-count change after traffic merge.")

print("Matched roads:", len(df))
print("Unmatched roads: 0")

# ------------------------------------------------------------
# 3. VALIDATE COMPONENTS
# ------------------------------------------------------------
print("\n[3/7] Validating risk components...")

required_components = [
    "historical_risk",
    "traffic_risk",
    "weather_risk",
]

for column in required_components:
    df[column] = pd.to_numeric(df[column], errors="coerce")
    df.loc[~np.isfinite(df[column]), column] = np.nan
    df[column] = df[column].clip(0, 100)

for column in [
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "current_travel_time_sec",
    "free_flow_travel_time_sec",
    "traffic_confidence",
    "congestion_ratio",
    "temperature_c",
    "humidity_percent",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
    "wind_direction_deg",
    "weather_distance_km",
]:
    if column in df.columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

traffic_ok = (
    df["traffic_status"].eq("SUCCESS")
    & df["current_speed_kmh"].notna()
    & df["free_flow_speed_kmh"].notna()
    & df["free_flow_speed_kmh"].gt(0)
    & df["traffic_risk"].notna()
)

weather_ok = (
    df["weather_status"].eq("SUCCESS")
    & df["weather_risk"].notna()
)

historical_ok = df["historical_risk"].notna()

# Risk components cannot be trusted if the corresponding source failed.
df.loc[~traffic_ok, "traffic_risk"] = np.nan
df.loc[~weather_ok, "weather_risk"] = np.nan

# ------------------------------------------------------------
# 4. CALCULATE COMPONENT CONTRIBUTIONS
# ------------------------------------------------------------
print("\n[4/7] Calculating weighted dynamic risk...")

df["historical_contribution"] = (
    df["historical_risk"] * HISTORICAL_WEIGHT
)
df["traffic_contribution"] = (
    df["traffic_risk"] * TRAFFIC_WEIGHT
)
df["weather_contribution"] = (
    df["weather_risk"] * WEATHER_WEIGHT
)

all_components_available = (
    historical_ok & traffic_ok & weather_ok
)

df["dynamic_risk"] = np.nan

df.loc[all_components_available, "dynamic_risk"] = (
    df.loc[all_components_available, "historical_contribution"]
    + df.loc[all_components_available, "traffic_contribution"]
    + df.loc[all_components_available, "weather_contribution"]
)

# Parse boolean values robustly, including CSV strings.
closure_text = df["road_closure"].astype(str).str.strip().str.lower()
closed = closure_text.isin(["true", "1", "yes"])

df["road_closure"] = closed

# A confirmed closure is a routing constraint, not a normal risk score.
df.loc[closed, "dynamic_risk"] = 100.0

df["dynamic_risk"] = df["dynamic_risk"].clip(0, 100).round(2)

# ------------------------------------------------------------
# 5. CLASSIFY RISK AND DATA AVAILABILITY
# ------------------------------------------------------------
print("\n[5/7] Classifying risk and data availability...")

def classify_dynamic(row):
    if row["road_closure"]:
        return "CLOSED"
    if pd.isna(row["dynamic_risk"]):
        return "UNAVAILABLE"

    risk = row["dynamic_risk"]
    if risk < 20:
        return "LOW"
    if risk < 40:
        return "MEDIUM"
    if risk < 70:
        return "HIGH"
    return "SEVERE"

def classify_component(value):
    if pd.isna(value):
        return "UNAVAILABLE"
    if value < 15:
        return "LOW"
    if value < 35:
        return "MEDIUM"
    if value < 60:
        return "HIGH"
    return "SEVERE"

df["dynamic_risk_category"] = df.apply(classify_dynamic, axis=1)
df["traffic_status_calculated"] = df["traffic_risk"].apply(classify_component)
df["weather_status_calculated"] = df["weather_risk"].apply(classify_component)

df["risk_data_status"] = np.select(
    [
        closed,
        all_components_available,
    ],
    [
        "CLOSED",
        "COMPLETE",
    ],
    default="INCOMPLETE",
)

# ------------------------------------------------------------
# 6. BUILD FINAL OUTPUT
# ------------------------------------------------------------
print("\n[6/7] Preparing output dataset...")

final_columns = [
    "osm_u", "osm_v", "osm_key",
    "road_name", "highway", "road_length_m",
    "accident_count", "fatal_count", "major_count", "minor_count",
    "historical_risk", "risk_category",
    "current_speed_kmh", "free_flow_speed_kmh",
    "current_travel_time_sec", "free_flow_travel_time_sec",
    "traffic_confidence", "road_closure", "congestion_ratio",
    "traffic_risk", "traffic_status", "traffic_observation_time",
    "traffic_http_status", "traffic_error",
    "traffic_status_calculated",
    "weather_grid_id", "weather_distance_km", "observation_time",
    "temperature_c", "humidity_percent", "precipitation_mm",
    "rain_mm", "weather_code", "wind_speed_kmh", "wind_direction_deg",
    "weather_status", "rain_risk", "weather_code_risk",
    "wind_risk", "humidity_risk", "weather_risk",
    "weather_risk_category", "weather_status_calculated",
    "historical_contribution", "traffic_contribution",
    "weather_contribution", "dynamic_risk",
    "dynamic_risk_category", "risk_data_status",
]

missing_final = [c for c in final_columns if c not in df.columns]
if missing_final:
    raise ValueError(f"Missing output columns: {missing_final}")

result = df[final_columns].copy()

# ------------------------------------------------------------
# VALIDATE BEFORE PUBLISHING
# ------------------------------------------------------------

# Preserve the existing output unless the new dataset passes checks.
if result.empty:
    raise ValueError(
        "Refusing to publish an empty dynamic-risk dataset."
    )

if len(result) != len(weather):
    raise ValueError(
        "Output row count differs from weather input. "
        "Existing output preserved."
    )

if result[KEYS].isna().any().any():
    raise ValueError(
        "Output contains missing road identifiers. "
        "Existing output preserved."
    )

if result.duplicated(KEYS).any():
    raise ValueError(
        "Output contains duplicate road identifiers. "
        "Existing output preserved."
    )

complete_count = int(result["risk_data_status"].eq("COMPLETE").sum())
coverage = complete_count / len(result)

if coverage < MIN_COMPLETE_COVERAGE:
    raise ValueError(
        f"Complete risk coverage {coverage:.1%} is below "
        f"required {MIN_COMPLETE_COVERAGE:.0%}. "
        "Existing output preserved."
    )

available_risk = result["dynamic_risk"].dropna()

if available_risk.empty:
    raise ValueError(
        "No usable dynamic-risk scores available. "
        "Existing output preserved."
    )

if not np.isfinite(available_risk.to_numpy(dtype=float)).all():
    raise ValueError(
        "Output contains invalid dynamic-risk scores. "
        "Existing output preserved."
    )

if not available_risk.between(MIN_RISK_SCORE, MAX_RISK_SCORE).all():
    raise ValueError(
        "Dynamic-risk scores are outside the allowed range. "
        "Existing output preserved."
    )

# Write to a temporary file, then atomically replace the output.
temporary_file = OUTPUT_FILE + ".tmp"

try:
    result.to_csv(temporary_file, index=False)

    check_df = pd.read_csv(temporary_file)

    if len(check_df) != len(result):
        raise ValueError(
            "Temporary dynamic-risk dataset has an unexpected row count. "
            "Existing output preserved."
        )

    if check_df.duplicated(KEYS).any():
        raise ValueError(
            "Temporary dynamic-risk dataset contains duplicate road identifiers. "
            "Existing output preserved."
        )

    os.replace(temporary_file, OUTPUT_FILE)

finally:
    if os.path.exists(temporary_file):
        os.remove(temporary_file)

# ------------------------------------------------------------
# 7. SUMMARY
# ------------------------------------------------------------
print("\n[7/7] Validation summary")

print("\nRisk-data status:")
print(result["risk_data_status"].value_counts(dropna=False))

print("\nDynamic-risk categories:")
print(result["dynamic_risk_category"].value_counts(dropna=False))

print("\nComponent missing values:")
print(result[required_components].isna().sum())

print("\nDynamic risk statistics (available scores):")
print(result["dynamic_risk"].describe().round(2))

print("\nTraffic observation range:")
print(result["traffic_observation_time"].min(), "to",
      result["traffic_observation_time"].max())

print("\nWeather observation range:")
print(result["observation_time"].min(), "to",
      result["observation_time"].max())

print("\nOutput:", OUTPUT_FILE)
print("Road segments:", len(result))
print("Confirmed closed roads:", int(result["road_closure"].sum()))
print("\nWeights: historical 50%, traffic 30%, weather 20%")
print("These are prototype engineering weights, not calibrated probabilities.")
print("\nDYNAMIC RISK DATASET CREATED")
