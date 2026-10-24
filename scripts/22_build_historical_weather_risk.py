import pandas as pd
import numpy as np

INPUT_FILE = "data/processed/chennai_accidents.csv"
OUTPUT_FILE = "data/processed/historical_weather_risk.csv"

print("=" * 70)
print("SAFEROUTE - HISTORICAL WEATHER RISK")
print("=" * 70)


# ============================================================
# 1. LOAD ACCIDENT DATA
# ============================================================

print("\n[1/5] Loading accident dataset...")

df = pd.read_csv(INPUT_FILE)

print(f"Accident records: {len(df):,}")


# ============================================================
# 2. CHECK REQUIRED COLUMNS
# ============================================================

required_columns = [
    "weather",
    "accident_severity",
    "casualties",
]

missing = [
    col for col in required_columns
    if col not in df.columns
]

if missing:
    raise ValueError(
        f"Missing required columns: {missing}"
    )


# ============================================================
# 3. CLEAN WEATHER VALUES
# ============================================================

print("\n[2/5] Preparing weather categories...")

df["weather"] = (
    df["weather"]
    .astype(str)
    .str.strip()
    .str.lower()
)


# ============================================================
# 4. CALCULATE SEVERITY WEIGHT
# ============================================================

severity_weights = {
    "minor": 1,
    "major": 2,
    "fatal": 4,
}

df["severity_weight"] = (
    df["accident_severity"]
    .astype(str)
    .str.strip()
    .str.lower()
    .map(severity_weights)
    .fillna(1)
)


# Severity-weighted accident contribution
df["weighted_risk"] = (
    df["severity_weight"]
    + df["casualties"].fillna(0) * 0.25
)


# ============================================================
# 5. AGGREGATE BY WEATHER
# ============================================================

print("\n[3/5] Calculating weather statistics...")

weather_stats = (
    df.groupby("weather")
    .agg(
        accident_count=("accident_severity", "count"),
        total_casualties=("casualties", "sum"),
        weighted_risk=("weighted_risk", "sum"),
        avg_severity_weight=("severity_weight", "mean"),
    )
    .reset_index()
)


# Average risk per accident
weather_stats["risk_per_accident"] = (
    weather_stats["weighted_risk"]
    / weather_stats["accident_count"]
)


# ============================================================
# 6. NORMALIZE WEATHER RISK
# ============================================================

print("\n[4/5] Normalizing weather risk...")

max_risk = weather_stats["risk_per_accident"].max()

if max_risk > 0:
    weather_stats["historical_weather_risk"] = (
        weather_stats["risk_per_accident"]
        / max_risk
        * 100
    )
else:
    weather_stats["historical_weather_risk"] = 0


weather_stats["historical_weather_risk"] = (
    weather_stats["historical_weather_risk"]
    .round(2)
)


# ============================================================
# 7. CLASSIFICATION
# ============================================================

def classify_risk(value):

    if value < 25:
        return "LOW"

    elif value < 50:
        return "MEDIUM"

    elif value < 75:
        return "HIGH"

    else:
        return "SEVERE"


weather_stats["risk_category"] = (
    weather_stats["historical_weather_risk"]
    .apply(classify_risk)
)


# ============================================================
# 8. SAVE
# ============================================================

print("\n[5/5] Saving historical weather risk...")

weather_stats.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# OUTPUT
# ============================================================

print("\n" + "=" * 70)
print("HISTORICAL WEATHER RISK CREATED")
print("=" * 70)

print("\nWeather statistics:")

print(
    weather_stats.to_string(index=False)
)

print("\nSaved:")
print(OUTPUT_FILE)

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
