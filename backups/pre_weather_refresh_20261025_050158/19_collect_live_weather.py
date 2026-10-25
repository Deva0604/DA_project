import os
import sys
import time

import pandas as pd
import requests


# ============================================================
# SAFEROUTE - LIVE WEATHER GRID COLLECTION
# ============================================================

INPUT_FILE = (
    "data/processed/weather_grid.csv"
)

OUTPUT_FILE = (
    "data/processed/live_weather_grid.csv"
)

OPEN_METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
)

REQUEST_DELAY = 0.2


# ============================================================
# LOAD WEATHER GRID
# ============================================================

print("=" * 70)
print("SAFEROUTE - LIVE WEATHER GRID COLLECTION")
print("=" * 70)

print()
print("[1/5] Loading weather grid...")

df = pd.read_csv(INPUT_FILE)

print(
    f"Weather grid points: "
    f"{len(df)}"
)


# ============================================================
# OPEN-METEO REQUEST
# ============================================================

def get_weather(latitude, longitude):

    params = {
        "latitude": latitude,
        "longitude": longitude,

        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "rain",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m"
        ]),

        "timezone": "Asia/Kolkata"
    }

    response = requests.get(
        OPEN_METEO_URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# WEATHER COLLECTION
# ============================================================

print()
print("[2/5] Requesting live weather...")

results = []

successful = 0
failed = 0


for index, row in df.iterrows():

    grid_id = row["weather_grid_id"]

    latitude = row["latitude"]
    longitude = row["longitude"]

    print(
        f"[{index + 1}/{len(df)}] "
        f"Grid {grid_id} "
        f"@ {latitude:.6f}, {longitude:.6f}"
    )

    try:

        data = get_weather(
            latitude,
            longitude
        )

        current = data["current"]

        results.append({

            "weather_grid_id": grid_id,

            "latitude": latitude,
            "longitude": longitude,

            "observation_time": current.get(
                "time"
            ),

            "temperature_c": current.get(
                "temperature_2m"
            ),

            "humidity_percent": current.get(
                "relative_humidity_2m"
            ),

            "precipitation_mm": current.get(
                "precipitation"
            ),

            "rain_mm": current.get(
                "rain"
            ),

            "weather_code": current.get(
                "weather_code"
            ),

            "wind_speed_kmh": current.get(
                "wind_speed_10m"
            ),

            "wind_direction_deg": current.get(
                "wind_direction_10m"
            ),

            "weather_status": "SUCCESS"

        })

        successful += 1

        print(
            f"    Temperature: "
            f"{current.get('temperature_2m')} °C | "
            f"Rain: "
            f"{current.get('rain')} mm | "
            f"Wind: "
            f"{current.get('wind_speed_10m')} km/h | "
            f"Code: "
            f"{current.get('weather_code')}"
        )

    except Exception as e:

        print(
            f"    ERROR: {e}"
        )

        results.append({

            "weather_grid_id": grid_id,

            "latitude": latitude,
            "longitude": longitude,

            "observation_time": None,

            "temperature_c": None,
            "humidity_percent": None,

            "precipitation_mm": None,
            "rain_mm": None,

            "weather_code": None,

            "wind_speed_kmh": None,
            "wind_direction_deg": None,

            "weather_status": "FAILED"

        })

        failed += 1

    time.sleep(REQUEST_DELAY)


# ============================================================
# SAVE
# ============================================================

print()
print("[3/5] Saving weather dataset...")

result_df = pd.DataFrame(results)

result_df.to_csv(
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
    f"Grid points       : "
    f"{len(df)}"
)

print(
    f"Successful        : "
    f"{successful}"
)

print(
    f"Failed            : "
    f"{failed}"
)

print()
print("Weather status:")

print(
    result_df[
        "weather_status"
    ].value_counts()
    .to_string()
)


# ============================================================
# STATISTICS
# ============================================================

print()
print("Weather statistics:")

print(
    result_df[
        [
            "temperature_c",
            "humidity_percent",
            "rain_mm",
            "wind_speed_kmh"
        ]
    ]
    .describe()
    .to_string()
)


# ============================================================
# OUTPUT
# ============================================================

print()
print("[5/5] Output")
print("-" * 70)

print(
    f"Saved: {OUTPUT_FILE}"
)

print()
print("=" * 70)
print("LIVE WEATHER COLLECTION COMPLETE")
print("=" * 70)
