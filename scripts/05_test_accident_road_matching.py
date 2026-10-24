import pandas as pd
import geopandas as gpd

# ---------------------------------------------------------
# FILES
# ---------------------------------------------------------

ACCIDENT_FILE = "data/processed/chennai_accidents.csv"
ROAD_FILE = "data/raw/osm/chennai_roads.geojson"

OUTPUT_FILE = "data/processed/test_accident_road_matching.csv"


# ---------------------------------------------------------
# 1. LOAD ACCIDENT DATA
# ---------------------------------------------------------

print("=" * 70)
print("SAFEROUTE - ACCIDENT TO ROAD MATCHING TEST")
print("=" * 70)

print("\nLoading accident data...")

accidents = pd.read_csv(ACCIDENT_FILE)

print(f"Total Chennai accidents: {len(accidents)}")


# ---------------------------------------------------------
# 2. CONVERT ACCIDENTS TO GEODATAFRAME
# ---------------------------------------------------------

accidents_gdf = gpd.GeoDataFrame(
    accidents,
    geometry=gpd.points_from_xy(
        accidents["longitude"],
        accidents["latitude"]
    ),
    crs="EPSG:4326"
)


# ---------------------------------------------------------
# 3. LOAD OSM ROADS
# ---------------------------------------------------------

print("\nLoading Chennai road network...")

roads = gpd.read_file(ROAD_FILE)

print(f"Total road segments: {len(roads)}")


# ---------------------------------------------------------
# 4. KEEP ONLY USEFUL ROAD COLUMNS
# ---------------------------------------------------------

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

roads = roads[road_columns]


# ---------------------------------------------------------
# 5. PROJECT TO METRIC CRS
# ---------------------------------------------------------

print("\nProjecting data to UTM Zone 44N...")

accidents_projected = accidents_gdf.to_crs(
    "EPSG:32644"
)

roads_projected = roads.to_crs(
    "EPSG:32644"
)


# ---------------------------------------------------------
# 6. TEST WITH 100 ACCIDENTS
# ---------------------------------------------------------

test_accidents = accidents_projected.head(100).copy()

print("\nMatching first 100 accidents...")


# ---------------------------------------------------------
# 7. FIND NEAREST ROAD
# ---------------------------------------------------------

matched = gpd.sjoin_nearest(
    test_accidents,
    roads_projected,
    how="left",
    distance_col="distance_to_road_meters"
)


# ---------------------------------------------------------
# 8. RESULTS
# ---------------------------------------------------------

print("\nMatching complete.")

print("\nResult shape:")
print(matched.shape)

print("\nDistance statistics:")
print(
    matched["distance_to_road_meters"].describe()
)

print("\nFirst 10 matches:")

print(
    matched[
        [
            "accident_id",
            "latitude",
            "longitude",
            "accident_severity",
            "highway",
            "name",
            "length",
            "distance_to_road_meters"
        ]
    ].head(10).to_string(index=False)
)


# ---------------------------------------------------------
# 9. SAVE TEST RESULTS
# ---------------------------------------------------------

matched.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\nSaved test results:")
print(OUTPUT_FILE)