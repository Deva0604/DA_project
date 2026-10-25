import os
import time
from pathlib import Path

import pandas as pd
import requests


# ============================================================
# SAFEROUTE - SAFE LIVE WEATHER GRID COLLECTION
# ============================================================

INPUT_FILE = Path("data/processed/weather_grid.csv")
OUTPUT_FILE = Path("data/processed/live_weather_grid.csv")
TEMP_FILE = OUTPUT_FILE.with_suffix(".csv.tmp")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_DELAY = 0.2

GRID_COLUMNS = ["weather_grid_id", "latitude", "longitude"]

WEATHER_COLUMNS = [
    "weather_grid_id",
    "latitude",
    "longitude",
    "observation_time",
    "temperature_c",
    "humidity_percent",
    "precipitation_mm",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
    "wind_direction_deg",
    "weather_status",
]

NUMERIC_WEATHER_COLUMNS = [
    "temperature_c",
    "humidity_percent",
    "precipitation_mm",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
    "wind_direction_deg",
]


def validate_weather(df, expected_ids):
    """Raise an error if weather observations are incomplete or invalid."""

    if df.empty:
        raise ValueError("Weather dataset is empty.")

    if list(df.columns) != WEATHER_COLUMNS:
        raise ValueError("Weather columns do not match the expected schema.")

    if df["weather_grid_id"].duplicated().any():
        raise ValueError("Duplicate weather grid IDs found.")

    if set(df["weather_grid_id"]) != set(expected_ids):
        raise ValueError("Weather grid IDs do not match the input grid.")

    if not df["weather_status"].eq("SUCCESS").all():
        raise ValueError("At least one weather request failed.")

    timestamps = pd.to_datetime(
        df["observation_time"], errors="coerce", utc=True
    )
    if timestamps.isna().any():
        raise ValueError("Missing or invalid observation timestamps.")

    for column in NUMERIC_WEATHER_COLUMNS:
        values = pd.to_numeric(df[column], errors="coerce")
        if values.isna().any():
            raise ValueError(f"Missing or invalid values in {column}.")
        if not values.map(lambda x: pd.notna(x) and abs(x) != float("inf")).all():
            raise ValueError(f"Non-finite values found in {column}.")

    if not df["humidity_percent"].between(0, 100).all():
        raise ValueError("Humidity must be between 0 and 100 percent.")

    if (df["precipitation_mm"] < 0).any() or (df["rain_mm"] < 0).any():
        raise ValueError("Precipitation and rain cannot be negative.")

    if (df["wind_speed_kmh"] < 0).any():
        raise ValueError("Wind speed cannot be negative.")


def get_weather(session, latitude, longitude):
    params = {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "current": ",".join([
            "temperature_2m",
            "relative_humidity_2m",
            "precipitation",
            "rain",
            "weather_code",
            "wind_speed_10m",
            "wind_direction_10m",
        ]),
        "timezone": "Asia/Kolkata",
    }

    response = session.get(
        OPEN_METEO_URL,
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    current = payload.get("current")

    if not isinstance(current, dict):
        raise ValueError("API response does not contain current weather.")

    return current


def main():
    print("=" * 70)
    print("SAFEROUTE - SAFE LIVE WEATHER COLLECTION")
    print("=" * 70)

    if not INPUT_FILE.exists():
        raise FileNotFoundError(f"Weather grid not found: {INPUT_FILE}")

    grid = pd.read_csv(INPUT_FILE)

    missing = set(GRID_COLUMNS) - set(grid.columns)
    if missing:
        raise ValueError(f"Weather grid missing columns: {sorted(missing)}")

    grid = grid[GRID_COLUMNS].copy()

    if grid.empty:
        raise ValueError("Weather grid contains no points.")

    if grid.isna().any().any():
        raise ValueError("Weather grid contains missing values.")

    if grid["weather_grid_id"].duplicated().any():
        raise ValueError("Weather grid IDs must be unique.")

    for column in ["latitude", "longitude"]:
        grid[column] = pd.to_numeric(grid[column], errors="raise")

    if not grid["latitude"].between(-90, 90).all():
        raise ValueError("Invalid latitude in weather grid.")

    if not grid["longitude"].between(-180, 180).all():
        raise ValueError("Invalid longitude in weather grid.")

    print(f"Weather grid points: {len(grid)}")
    print("Collecting observations; the existing output will not be changed yet.")

    results = []

    with requests.Session() as session:
        for index, row in grid.iterrows():
            grid_id = row["weather_grid_id"]
            print(f"[{index + 1}/{len(grid)}] Requesting grid {grid_id}...")

            current = get_weather(
                session,
                row["latitude"],
                row["longitude"],
            )

            record = {
                "weather_grid_id": grid_id,
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "observation_time": (    pd.Timestamp(current.get("time"))    .tz_localize("Asia/Kolkata")    .tz_convert("UTC")    .isoformat()),
                "temperature_c": current.get("temperature_2m"),
                "humidity_percent": current.get("relative_humidity_2m"),
                "precipitation_mm": current.get("precipitation"),
                "rain_mm": current.get("rain"),
                "weather_code": current.get("weather_code"),
                "wind_speed_kmh": current.get("wind_speed_10m"),
                "wind_direction_deg": current.get("wind_direction_10m"),
                "weather_status": "SUCCESS",
            }

            results.append(record)
            print(
                f"    Temp: {record['temperature_c']} °C | "
                f"Rain: {record['rain_mm']} mm | "
                f"Wind: {record['wind_speed_kmh']} km/h"
            )

            time.sleep(REQUEST_DELAY)

    result = pd.DataFrame(results, columns=WEATHER_COLUMNS)

    # Convert numeric fields before validation and publication.
    for column in NUMERIC_WEATHER_COLUMNS:
        result[column] = pd.to_numeric(result[column], errors="coerce")

    validate_weather(result, grid["weather_grid_id"].tolist())

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        result.to_csv(TEMP_FILE, index=False)

        # Read back the temporary file and validate the persisted values.
        check = pd.read_csv(TEMP_FILE)
        for column in NUMERIC_WEATHER_COLUMNS:
            check[column] = pd.to_numeric(check[column], errors="coerce")

        validate_weather(check, grid["weather_grid_id"].tolist())

        if len(check) != len(grid):
            raise ValueError("Saved weather row count does not match the grid.")

        os.replace(TEMP_FILE, OUTPUT_FILE)

    except Exception:
        if TEMP_FILE.exists():
            TEMP_FILE.unlink()
        raise

    print()
    print("WEATHER COLLECTION SUCCESSFUL")
    print(f"Grid points: {len(result)}")
    print(f"Successful: {len(result)}")
    print(f"Failed: 0")
    print(f"Published: {OUTPUT_FILE}")
    print("The output was replaced only after validation.")


if __name__ == "__main__":
    main()
