import os
from pathlib import Path

import numpy as np
import pandas as pd


# ============================================================
# SAFEROUTE - SAFE WEATHER ASSIGNMENT TO ROADS
# ============================================================

TRAFFIC_FILE = Path("data/processed/road_live_traffic_full.csv")
WEATHER_FILE = Path("data/processed/live_weather_grid.csv")
OUTPUT_FILE = Path("data/processed/road_weather_conditions.csv")
TEMP_FILE = OUTPUT_FILE.with_suffix(".csv.tmp")

ROAD_KEYS = ["osm_u", "osm_v", "osm_key"]

WEATHER_COLUMNS = [
    "weather_grid_id",
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

WEATHER_NUMERIC_COLUMNS = [
    "temperature_c",
    "humidity_percent",
    "precipitation_mm",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
    "wind_direction_deg",
]

TRAFFIC_TIMESTAMP = "traffic_observation_time"


def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate great-circle distances in kilometres."""
    earth_radius_km = 6371.0

    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)
    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        np.sin(dlat / 2) ** 2
        + np.cos(lat1)
        * np.cos(lat2)
        * np.sin(dlon / 2) ** 2
    )

    a = np.clip(a, 0.0, 1.0)
    return earth_radius_km * 2 * np.arcsin(np.sqrt(a))


def validate_weather(weather):
    """Reject incomplete, failed, or invalid weather observations."""

    required = set(WEATHER_COLUMNS)
    missing = required - set(weather.columns)

    if missing:
        raise ValueError(f"Weather file missing columns: {sorted(missing)}")

    if weather.empty:
        raise ValueError("Weather dataset is empty.")

    if weather["weather_grid_id"].isna().any():
        raise ValueError("Weather grid contains missing IDs.")

    if weather["weather_grid_id"].duplicated().any():
        raise ValueError("Duplicate weather grid IDs found.")

    if not weather["weather_status"].eq("SUCCESS").all():
        raise ValueError("Weather dataset contains failed requests.")

    timestamps = pd.to_datetime(
        weather["observation_time"], errors="coerce", utc=True
    )

    if timestamps.isna().any():
        raise ValueError("Weather observation timestamps are invalid.")

    # Prevent future-dated or stale observations.
    now = pd.Timestamp.now(tz="UTC")
    age_minutes = (now - timestamps).dt.total_seconds() / 60

    if (age_minutes < -10).any():
        raise ValueError("Weather dataset contains future-dated observations.")

    if (age_minutes > 120).any():
        raise ValueError(
            "Weather observations are older than 120 minutes. "
            "Refresh weather before assigning it to roads."
        )

    for column in WEATHER_NUMERIC_COLUMNS:
        weather[column] = pd.to_numeric(weather[column], errors="coerce")

        if weather[column].isna().any():
            raise ValueError(f"Missing or invalid weather values: {column}")

        if not np.isfinite(weather[column].to_numpy(dtype=float)).all():
            raise ValueError(f"Non-finite weather values: {column}")

    if not weather["humidity_percent"].between(0, 100).all():
        raise ValueError("Humidity must be between 0 and 100 percent.")

    if (weather["precipitation_mm"] < 0).any():
        raise ValueError("Precipitation cannot be negative.")

    if (weather["rain_mm"] < 0).any():
        raise ValueError("Rain cannot be negative.")

    if (weather["wind_speed_kmh"] < 0).any():
        raise ValueError("Wind speed cannot be negative.")

    weather["observation_time"] = timestamps


def validate_roads(roads):
    """Validate road identifiers, coordinates, and traffic freshness."""

    required = set(ROAD_KEYS + [
        "traffic_latitude",
        "traffic_longitude",
        TRAFFIC_TIMESTAMP,
    ])

    missing = required - set(roads.columns)

    if missing:
        raise ValueError(f"Traffic file missing columns: {sorted(missing)}")

    if roads.empty:
        raise ValueError("Traffic dataset is empty.")

    if roads[ROAD_KEYS].isna().any().any():
        raise ValueError("Traffic dataset contains missing road keys.")

    if roads.duplicated(ROAD_KEYS).any():
        raise ValueError("Traffic dataset contains duplicate road keys.")

    for column in ["traffic_latitude", "traffic_longitude"]:
        roads[column] = pd.to_numeric(roads[column], errors="coerce")

        if roads[column].isna().any():
            raise ValueError(f"Missing road coordinates: {column}")

        if not np.isfinite(roads[column].to_numpy(dtype=float)).all():
            raise ValueError(f"Non-finite road coordinates: {column}")

    if not roads["traffic_latitude"].between(-90, 90).all():
        raise ValueError("Invalid road latitude.")

    if not roads["traffic_longitude"].between(-180, 180).all():
        raise ValueError("Invalid road longitude.")

    timestamps = pd.to_datetime(
        roads[TRAFFIC_TIMESTAMP], errors="coerce", utc=True
    )

    if timestamps.isna().any():
        raise ValueError("Traffic dataset contains invalid observation timestamps.")

    now = pd.Timestamp.now(tz="UTC")
    age_minutes = (now - timestamps).dt.total_seconds() / 60

    if (age_minutes < -10).any():
        raise ValueError("Traffic dataset contains future-dated observations.")

    if (age_minutes > 180).any():
        raise ValueError(
            "Traffic observations are older than 180 minutes. "
            "Refresh traffic before assigning weather."
        )

    roads[TRAFFIC_TIMESTAMP] = timestamps


def main():
    print("=" * 70)
    print("SAFEROUTE - SAFE WEATHER ASSIGNMENT TO ROADS")
    print("=" * 70)

    if not TRAFFIC_FILE.exists():
        raise FileNotFoundError(f"Traffic file not found: {TRAFFIC_FILE}")

    if not WEATHER_FILE.exists():
        raise FileNotFoundError(f"Weather file not found: {WEATHER_FILE}")

    roads = pd.read_csv(TRAFFIC_FILE)
    weather = pd.read_csv(WEATHER_FILE)

    print(f"Road segments: {len(roads):,}")
    print(f"Weather points: {len(weather):,}")

    validate_roads(roads)
    validate_weather(weather)

    road_count_before = len(roads)
    original_keys = roads[ROAD_KEYS].copy()
    original_traffic_timestamps = roads[TRAFFIC_TIMESTAMP].copy()

    road_lat = roads["traffic_latitude"].to_numpy(dtype=float)
    road_lon = roads["traffic_longitude"].to_numpy(dtype=float)
    weather_lat = weather["latitude"].to_numpy(dtype=float)
    weather_lon = weather["longitude"].to_numpy(dtype=float)

    if not np.isfinite(weather_lat).all() or not np.isfinite(weather_lon).all():
        raise ValueError("Weather grid contains invalid coordinates.")

    if not weather["latitude"].between(-90, 90).all():
        raise ValueError("Invalid weather-grid latitude.")

    if not weather["longitude"].between(-180, 180).all():
        raise ValueError("Invalid weather-grid longitude.")

    print("Finding nearest weather point for each road...")

    nearest_ids = []
    nearest_distances = []

    for i in range(len(roads)):
        distances = haversine_distance(
            road_lat[i], road_lon[i], weather_lat, weather_lon
        )

        nearest_index = int(np.argmin(distances))
        nearest_ids.append(weather.iloc[nearest_index]["weather_grid_id"])
        nearest_distances.append(float(distances[nearest_index]))

    roads["weather_grid_id"] = nearest_ids
    roads["weather_distance_km"] = nearest_distances

    # One weather record per grid ID is required for a many-to-one join.
    weather_for_join = weather[WEATHER_COLUMNS].copy()

    result = roads.merge(
        weather_for_join,
        on="weather_grid_id",
        how="left",
        validate="many_to_one",
        indicator=True,
    )

    if len(result) != road_count_before:
        raise ValueError("Road count changed during weather assignment.")

    if not result["_merge"].eq("both").all():
        raise ValueError("Some road segments did not receive weather data.")

    result.drop(columns=["_merge"], inplace=True)

    if result[WEATHER_COLUMNS[1:]].isna().any().any():
        raise ValueError("Missing weather values remain after assignment.")

    if result.duplicated(ROAD_KEYS).any():
        raise ValueError("Duplicate road keys appeared after assignment.")

    if not result[TRAFFIC_TIMESTAMP].reset_index(drop=True).equals(
        original_traffic_timestamps.reset_index(drop=True)
    ):
        raise ValueError("Traffic observation timestamps changed unexpectedly.")

    if not result[ROAD_KEYS].reset_index(drop=True).equals(
        original_keys.reset_index(drop=True)
    ):
        raise ValueError("Road identifiers or row order changed unexpectedly.")

    # Publish only after validating the persisted temporary file.
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    try:
        result.to_csv(TEMP_FILE, index=False)

        saved = pd.read_csv(TEMP_FILE)

        if len(saved) != road_count_before:
            raise ValueError("Saved output row count does not match input.")

        if saved.duplicated(ROAD_KEYS).any():
            raise ValueError("Saved output contains duplicate road keys.")

        if saved[TRAFFIC_TIMESTAMP].isna().any():
            raise ValueError("Saved output has missing traffic timestamps.")

        if saved["weather_status"].isna().any():
            raise ValueError("Saved output has missing weather statuses.")

        if not saved["weather_status"].eq("SUCCESS").all():
            raise ValueError("Saved output includes failed weather records.")

        saved_weather_times = pd.to_datetime(
            saved["observation_time"], errors="coerce", utc=True
        )

        if saved_weather_times.isna().any():
            raise ValueError("Saved output has invalid weather timestamps.")

        if saved[WEATHER_COLUMNS[1:]].isna().any().any():
            raise ValueError("Saved output contains missing weather values.")

        os.replace(TEMP_FILE, OUTPUT_FILE)

    except Exception:
        if TEMP_FILE.exists():
            TEMP_FILE.unlink()
        raise

    print()
    print("ROAD-WEATHER DATASET CREATED SUCCESSFULLY")
    print(f"Road segments: {len(result):,}")
    print(f"Weather points used: {result['weather_grid_id'].nunique()}")
    print(f"Output: {OUTPUT_FILE}")
    print("Traffic timestamps preserved.")
    print("All roads received valid weather observations.")
    print("Output was atomically published after validation.")


if __name__ == "__main__":
    main()
