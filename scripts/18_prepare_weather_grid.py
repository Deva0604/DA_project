import pandas as pd
import numpy as np


# ============================================================
# SAFEROUTE - PREPARE WEATHER GRID
# ============================================================

INPUT_FILE = (
    "data/processed/road_traffic_targets.csv"
)

OUTPUT_FILE = (
    "data/processed/weather_grid.csv"
)


print("=" * 70)
print("SAFEROUTE - WEATHER GRID PREPARATION")
print("=" * 70)


# ============================================================
# LOAD ROAD COORDINATES
# ============================================================

print()
print("[1/4] Loading road coordinates...")

df = pd.read_csv(INPUT_FILE)

lat_min = df["traffic_latitude"].min()
lat_max = df["traffic_latitude"].max()

lon_min = df["traffic_longitude"].min()
lon_max = df["traffic_longitude"].max()

print(f"Latitude : {lat_min:.6f} → {lat_max:.6f}")
print(f"Longitude: {lon_min:.6f} → {lon_max:.6f}")


# ============================================================
# ADD SMALL BUFFER
# ============================================================

print()
print("[2/4] Creating study-area buffer...")

lat_min -= 0.02
lat_max += 0.02

lon_min -= 0.02
lon_max += 0.02


# ============================================================
# CREATE GRID
# ============================================================

print()
print("[3/4] Creating weather grid...")


# Approximately 5 × 5 grid
latitudes = np.linspace(
    lat_min,
    lat_max,
    5
)

longitudes = np.linspace(
    lon_min,
    lon_max,
    5
)


grid = []

grid_id = 1

for lat in latitudes:

    for lon in longitudes:

        grid.append({

            "weather_grid_id": grid_id,

            "latitude": round(
                float(lat),
                6
            ),

            "longitude": round(
                float(lon),
                6
            )

        })

        grid_id += 1


grid_df = pd.DataFrame(grid)


# ============================================================
# SAVE
# ============================================================

print()
print("[4/4] Saving weather grid...")

grid_df.to_csv(
    OUTPUT_FILE,
    index=False
)


print()
print("=" * 70)
print("WEATHER GRID CREATED")
print("=" * 70)

print()
print(
    f"Grid points: "
    f"{len(grid_df)}"
)

print()
print(grid_df.to_string(index=False))

print()
print(f"Saved: {OUTPUT_FILE}")

print()
print("=" * 70)
print("DONE")
print("=" * 70)
