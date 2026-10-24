import pandas as pd
import geopandas as gpd

# =========================================================
# SAFEROUTE
# Accident → Road Matching Test
# =========================================================

ACCIDENT_FILE = "data/processed/chennai_accidents.csv"

ROAD_FILE = (
    "data/raw/osm/"
    "saferoute_study_area_roads.geojson"
)

OUTPUT_FILE = (
    "data/processed/"
    "test_accident_road_matching_v2.csv"
)

print("=" * 70)
print("SAFEROUTE - ACCIDENT TO ROAD MATCHING TEST V2")
print("=" * 70)


# =========================================================
# 1. LOAD ACCIDENTS
# =========================================================

print("\n[1/6] Loading accident data...")

accidents = pd.read_csv(ACCIDENT_FILE)

print(f"Total accidents: {len(accidents)}")


# =========================================================
# 2. CREATE POINT GEOMETRY
# =========================================================

print("\n[2/6] Creating accident geometries...")

accidents_gdf = gpd.GeoDataFrame(
    accidents.copy(),
    geometry=gpd.points_from_xy(
        accidents["longitude"],
        accidents["latitude"]
    ),
    crs="EPSG:4326"
)


# =========================================================
# 3. LOAD OSM ROADS
# =========================================================

print("\n[3/6] Loading OSM road network...")

roads = gpd.read_file(ROAD_FILE)

print(f"Total road segments: {len(roads)}")


# =========================================================
# 4. KEEP RELEVANT COLUMNS
# =========================================================

road_columns = [
    "u",
    "v",
    "key",
    "osmid",
    "highway",
    "name",
    "oneway",
    "length",
    "lanes",
    "maxspeed",
    "junction",
    "service",
    "geometry"
]

# Only keep columns that actually exist
road_columns = [
    col for col in road_columns
    if col in roads.columns
]

roads = roads[road_columns].copy()


# =========================================================
# 5. PROJECT TO METRIC CRS
# =========================================================

print("\n[4/6] Projecting to UTM Zone 44N...")

accidents_projected = accidents_gdf.to_crs(
    "EPSG:32644"
)

roads_projected = roads.to_crs(
    "EPSG:32644"
)


# =========================================================
# 6. TEST FIRST 100 ACCIDENTS
# =========================================================

print("\n[5/6] Testing first 100 accidents...")

test_accidents = accidents_projected.head(100).copy()


# =========================================================
# FIND NEAREST ROAD
# =========================================================

matched = gpd.sjoin_nearest(
    test_accidents,
    roads_projected,
    how="left",
    distance_col="distance_to_road_m"
)


# =========================================================
# REMOVE DUPLICATE ACCIDENT MATCHES
# =========================================================

print("\nResolving duplicate nearest-road matches...")

matched = (
    matched
    .sort_values(
        ["accident_id", "distance_to_road_m"]
    )
    .drop_duplicates(
        subset=["accident_id"],
        keep="first"
    )
)


# =========================================================
# RESULTS
# =========================================================

print("\n[6/6] Matching results")

print("-" * 70)

print(f"Input accidents tested : {len(test_accidents)}")
print(f"Matched accidents      : {len(matched)}")

print("\nDistance statistics:")
print(
    matched["distance_to_road_m"].describe()
)


# =========================================================
# DISTANCE QUALITY
# =========================================================

print("\nDistance quality:")

print(
    f"≤ 10 m   : "
    f"{(matched['distance_to_road_m'] <= 10).sum()}"
)

print(
    f"≤ 25 m   : "
    f"{(matched['distance_to_road_m'] <= 25).sum()}"
)

print(
    f"≤ 50 m   : "
    f"{(matched['distance_to_road_m'] <= 50).sum()}"
)

print(
    f"≤ 100 m  : "
    f"{(matched['distance_to_road_m'] <= 100).sum()}"
)

print(
    f"> 100 m  : "
    f"{(matched['distance_to_road_m'] > 100).sum()}"
)


# =========================================================
# SHOW SAMPLE
# =========================================================

print("\nFirst 15 matches:")

columns_to_show = [
    "accident_id",
    "latitude",
    "longitude",
    "accident_severity",
    "highway",
    "name",
    "length",
    "distance_to_road_m"
]

columns_to_show = [
    col for col in columns_to_show
    if col in matched.columns
]

print(
    matched[columns_to_show]
    .head(15)
    .to_string(index=False)
)


# =========================================================
# SAVE
# =========================================================

matched.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\nSaved:")
print(OUTPUT_FILE)

print("\nDone.")