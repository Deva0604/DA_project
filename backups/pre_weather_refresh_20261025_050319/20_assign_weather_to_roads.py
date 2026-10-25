import pandas as pd
import numpy as np


# ============================================================
# SAFEROUTE - ASSIGN WEATHER TO ROADS
# ============================================================

TRAFFIC_FILE = (
    "data/processed/road_live_traffic.csv"
)

WEATHER_FILE = (
    "data/processed/live_weather_grid.csv"
)

OUTPUT_FILE = (
    "data/processed/road_weather_conditions.csv"
)


print("=" * 70)
print("SAFEROUTE - ASSIGN WEATHER TO ROADS")
print("=" * 70)


# ============================================================
# 1. LOAD DATA
# ============================================================

print()
print("[1/5] Loading datasets...")

roads = pd.read_csv(
    TRAFFIC_FILE
)

weather = pd.read_csv(
    WEATHER_FILE
)

print(
    f"Road segments : {len(roads):,}"
)

print(
    f"Weather points : {len(weather):,}"
)


# ============================================================
# 2. PREPARE COORDINATES
# ============================================================

print()
print("[2/5] Preparing coordinates...")

road_lat = roads[
    "traffic_latitude"
].to_numpy()

road_lon = roads[
    "traffic_longitude"
].to_numpy()

weather_lat = weather[
    "latitude"
].to_numpy()

weather_lon = weather[
    "longitude"
].to_numpy()


# ============================================================
# 3. HAVERSINE DISTANCE
# ============================================================

print()
print("[3/5] Finding nearest weather point...")


def haversine_distance(
    lat1,
    lon1,
    lat2,
    lon2
):
    """
    Calculate great-circle distance
    in kilometers.
    """

    earth_radius_km = 6371.0

    lat1 = np.radians(lat1)
    lon1 = np.radians(lon1)

    lat2 = np.radians(lat2)
    lon2 = np.radians(lon2)

    dlat = lat2 - lat1
    dlon = lon2 - lon1

    a = (
        np.sin(dlat / 2) ** 2
        +
        np.cos(lat1)
        *
        np.cos(lat2)
        *
        np.sin(dlon / 2) ** 2
    )

    c = 2 * np.arcsin(
        np.sqrt(a)
    )

    return earth_radius_km * c


nearest_ids = []
nearest_distances = []


for i in range(len(roads)):

    distances = haversine_distance(
        road_lat[i],
        road_lon[i],
        weather_lat,
        weather_lon
    )

    nearest_index = np.argmin(
        distances
    )

    nearest_ids.append(
        weather.iloc[
            nearest_index
        ][
            "weather_grid_id"
        ]
    )

    nearest_distances.append(
        distances[
            nearest_index
        ]
    )


# ============================================================
# 4. ADD WEATHER INFORMATION
# ============================================================

print()
print("[4/5] Joining weather observations...")


roads[
    "weather_grid_id"
] = nearest_ids

roads[
    "weather_distance_km"
] = nearest_distances


weather_columns = [
    "weather_grid_id",
    "observation_time",
    "temperature_c",
    "humidity_percent",
    "precipitation_mm",
    "rain_mm",
    "weather_code",
    "wind_speed_kmh",
    "wind_direction_deg",
    "weather_status"
]


roads = roads.merge(
    weather[
        weather_columns
    ],
    on="weather_grid_id",
    how="left"
)


# ============================================================
# 5. SAVE
# ============================================================

print()
print("[5/5] Saving road-weather dataset...")

roads.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("ROAD-WEATHER DATASET CREATED")
print("=" * 70)

print()
print(
    f"Road segments : "
    f"{len(roads):,}"
)

print(
    f"Weather points: "
    f"{roads['weather_grid_id'].nunique()}"
)

print()
print(
    "Weather assignment distance:"
)

print(
    roads[
        "weather_distance_km"
    ]
    .describe()
    .to_string()
)

print()
print(
    "Missing weather values:"
)

print(
    roads[
        [
            "temperature_c",
            "humidity_percent",
            "rain_mm",
            "weather_code"
        ]
    ]
    .isna()
    .sum()
    .to_string()
)

print()
print(
    "Sample:"
)

print(
    roads[
        [
            "osm_u",
            "osm_v",
            "historical_risk",
            "traffic_risk",
            "weather_grid_id",
            "temperature_c",
            "humidity_percent",
            "rain_mm",
            "weather_code",
            "weather_distance_km"
        ]
    ]
    .head(10)
    .to_string(index=False)
)

print()
print(
    f"Saved: {OUTPUT_FILE}"
)

print()
print("=" * 70)
print("DONE")
print("=" * 70)
