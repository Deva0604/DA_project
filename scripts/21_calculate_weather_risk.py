import pandas as pd
import numpy as np

INPUT_FILE = "data/processed/road_weather_conditions.csv"
OUTPUT_FILE = "data/processed/road_weather_risk.csv"


print("=" * 70)
print("SAFEROUTE - CALCULATE WEATHER RISK")
print("=" * 70)


# ============================================================
# 1. LOAD DATA
# ============================================================

print("\n[1/5] Loading road-weather dataset...")

df = pd.read_csv(INPUT_FILE)

print(f"Road segments: {len(df):,}")


# ============================================================
# 2. CHECK REQUIRED COLUMNS
# ============================================================

required_columns = [
    "temperature_c",
    "humidity_percent",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
]

missing_columns = [
    col for col in required_columns
    if col not in df.columns
]

if missing_columns:
    raise ValueError(
        f"Missing required columns: {missing_columns}"
    )


# ============================================================
# 3. CALCULATE WEATHER RISK COMPONENTS
# ============================================================

print("\n[2/5] Calculating weather risk components...")


# ------------------------------------------------------------
# Rain Risk
# ------------------------------------------------------------
#
# Prototype thresholds:
#
# 0 mm       -> 0
# 0-2 mm     -> low
# 2-5 mm     -> moderate
# 5-10 mm    -> high
# >10 mm     -> severe
#
# This is an engineering prototype scale, NOT an official
# accident-probability model.
# ------------------------------------------------------------

def calculate_rain_risk(rain):
    if rain <= 0:
        return 0.0
    elif rain <= 2:
        return 20.0
    elif rain <= 5:
        return 40.0
    elif rain <= 10:
        return 70.0
    else:
        return 100.0


df["rain_risk"] = df["rain_mm"].apply(calculate_rain_risk)


# ------------------------------------------------------------
# Weather Code Risk
# ------------------------------------------------------------
#
# Open-Meteo uses WMO weather codes.
#
# Important prototype groups:
#
# 0-3      clear/cloudy
# 45-48    fog
# 51-67    drizzle/rain
# 71-77    snow
# 80-82    rain showers
# 85-86    snow showers
# 95-99    thunderstorm
# ------------------------------------------------------------

def calculate_weather_code_risk(code):

    code = int(code)

    # Clear / mainly clear / cloudy
    if code in [0, 1, 2, 3]:
        return 0.0

    # Fog
    elif code in [45, 48]:
        return 35.0

    # Drizzle
    elif code in [51, 53, 55, 56, 57]:
        return 40.0

    # Rain
    elif code in [61, 63, 65, 66, 67]:
        return 60.0

    # Snow
    elif code in [71, 73, 75, 77, 85, 86]:
        return 70.0

    # Rain showers
    elif code in [80, 81, 82]:
        return 65.0

    # Thunderstorm
    elif code in [95, 96, 99]:
        return 90.0

    # Unknown weather condition
    else:
        return 25.0


df["weather_code_risk"] = df["weather_code"].apply(
    calculate_weather_code_risk
)


# ------------------------------------------------------------
# Wind Risk
# ------------------------------------------------------------

def calculate_wind_risk(wind):
    if wind < 20:
        return 0.0
    elif wind < 30:
        return 25.0
    elif wind < 40:
        return 50.0
    elif wind < 60:
        return 75.0
    else:
        return 100.0


df["wind_risk"] = df["wind_speed_kmh"].apply(
    calculate_wind_risk
)


# ------------------------------------------------------------
# Humidity Risk
# ------------------------------------------------------------
#
# High humidity alone should have relatively small influence.
# We use it as a minor environmental component.
# ------------------------------------------------------------

def calculate_humidity_risk(humidity):
    if humidity < 70:
        return 0.0
    elif humidity < 80:
        return 10.0
    elif humidity < 90:
        return 20.0
    else:
        return 30.0


df["humidity_risk"] = df["humidity_percent"].apply(
    calculate_humidity_risk
)


# ============================================================
# 4. COMBINE WEATHER COMPONENTS
# ============================================================

print("\n[3/5] Combining weather risk components...")


# Weighted combination
#
# Weather condition = 50%
# Rain             = 30%
# Wind             = 15%
# Humidity         = 5%
#

df["weather_risk"] = (
    df["weather_code_risk"] * 0.50
    + df["rain_risk"] * 0.30
    + df["wind_risk"] * 0.15
    + df["humidity_risk"] * 0.05
)


# Keep range 0-100
df["weather_risk"] = (
    df["weather_risk"]
    .clip(0, 100)
    .round(2)
)


# ============================================================
# 5. CLASSIFY WEATHER RISK
# ============================================================

def classify_weather_risk(risk):

    if risk < 15:
        return "LOW"

    elif risk < 35:
        return "MEDIUM"

    elif risk < 60:
        return "HIGH"

    else:
        return "SEVERE"


df["weather_risk_category"] = df["weather_risk"].apply(
    classify_weather_risk
)


# ============================================================
# SAVE
# ============================================================

print("\n[4/5] Saving weather-risk dataset...")

df.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

print("\n[5/5] Weather risk summary...")

print("\nWeather risk statistics:")

print(
    df["weather_risk"].describe()
)


print("\nWeather risk categories:")

print(
    df["weather_risk_category"]
    .value_counts()
    .sort_index()
)


print("\nWeather components:")

print(
    df[
        [
            "rain_risk",
            "weather_code_risk",
            "wind_risk",
            "humidity_risk",
            "weather_risk",
        ]
    ].describe()
)


print("\nSample:")

print(
    df[
        [
            "osm_u",
            "osm_v",
            "temperature_c",
            "humidity_percent",
            "rain_mm",
            "weather_code",
            "wind_speed_kmh",
            "weather_risk",
            "weather_risk_category",
        ]
    ].head(10).to_string(index=False)
)


print("\n" + "=" * 70)
print("WEATHER RISK DATASET CREATED")
print("=" * 70)

print(f"\nRoad segments : {len(df):,}")
print(f"Output file   : {OUTPUT_FILE}")

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
