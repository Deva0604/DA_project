import pandas as pd
import geopandas as gpd

# =========================================================
# SAFEROUTE
# FINAL ACCIDENT → ROAD MATCHING
# =========================================================

ACCIDENT_FILE = (
    "data/processed/chennai_accidents.csv"
)

ROAD_FILE = (
    "data/raw/osm/"
    "saferoute_study_area_roads.geojson"
)

OUTPUT_FILE = (
    "data/processed/"
    "accident_road_matches.csv"
)


print("=" * 70)
print("SAFEROUTE - FINAL ACCIDENT TO ROAD MATCHING")
print("=" * 70)


# =========================================================
# 1. LOAD ACCIDENTS
# =========================================================

print("\n[1/7] Loading accidents...")

accidents = pd.read_csv(
    ACCIDENT_FILE
)

print(
    f"Accidents loaded: {len(accidents)}"
)


# =========================================================
# 2. CREATE POINT GEOMETRY
# =========================================================

print("\n[2/7] Creating accident geometries...")

accidents_gdf = gpd.GeoDataFrame(
    accidents.copy(),
    geometry=gpd.points_from_xy(
        accidents["longitude"],
        accidents["latitude"]
    ),
    crs="EPSG:4326"
)


# =========================================================
# 3. LOAD ROADS
# =========================================================

print("\n[3/7] Loading OSM roads...")

roads = gpd.read_file(
    ROAD_FILE
)

print(
    f"Road segments loaded: {len(roads)}"
)


# =========================================================
# 4. SELECT USEFUL COLUMNS
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

road_columns = [
    c for c in road_columns
    if c in roads.columns
]

roads = roads[
    road_columns
].copy()


# =========================================================
# 5. PROJECT TO METRIC CRS
# =========================================================

print("\n[4/7] Projecting to UTM Zone 44N...")

accidents_projected = accidents_gdf.to_crs(
    "EPSG:32644"
)

roads_projected = roads.to_crs(
    "EPSG:32644"
)


# =========================================================
# 6. FIND NEAREST ROAD
# =========================================================

print("\n[5/7] Matching accidents to roads...")

matched = gpd.sjoin_nearest(
    accidents_projected,
    roads_projected,
    how="left",
    distance_col="distance_to_road_m"
)

print(
    f"Raw spatial matches: {len(matched)}"
)


# =========================================================
# 7. KEEP ONE ROAD PER ACCIDENT
# =========================================================

print("\n[6/7] Removing duplicate nearest matches...")

matched = (
    matched
    .sort_values(
        [
            "accident_id",
            "distance_to_road_m"
        ]
    )
    .drop_duplicates(
        subset=["accident_id"],
        keep="first"
    )
    .copy()
)


# =========================================================
# MATCH QUALITY
# =========================================================

def classify_match(distance):

    if pd.isna(distance):
        return "REJECTED"

    if distance <= 50:
        return "HIGH"

    elif distance <= 100:
        return "MEDIUM"

    elif distance <= 250:
        return "LOW"

    else:
        return "REJECTED"


matched["match_quality"] = (
    matched["distance_to_road_m"]
    .apply(classify_match)
)


# =========================================================
# MATCH ACCEPTANCE
# =========================================================

matched["match_accepted"] = (
    matched["distance_to_road_m"] <= 250
)


# =========================================================
# RESULTS
# =========================================================

print("\n[7/7] MATCHING RESULTS")
print("-" * 70)

print(
    f"Original accidents : {len(accidents)}"
)

print(
    f"Unique matches     : {len(matched)}"
)

print("\nMatch quality:")

print(
    matched["match_quality"]
    .value_counts()
    .reindex(
        [
            "HIGH",
            "MEDIUM",
            "LOW",
            "REJECTED"
        ]
    )
    .fillna(0)
    .astype(int)
)


# =========================================================
# PERCENTAGES
# =========================================================

print("\nMatch quality percentage:")

percentages = (
    matched["match_quality"]
    .value_counts(normalize=True)
    .reindex(
        [
            "HIGH",
            "MEDIUM",
            "LOW",
            "REJECTED"
        ]
    )
    .fillna(0)
    * 100
)

for category, value in percentages.items():

    print(
        f"{category:10s}: "
        f"{value:.2f}%"
    )


# =========================================================
# DISTANCE STATISTICS
# =========================================================

print("\nDistance statistics:")

print(
    matched[
        "distance_to_road_m"
    ].describe()
)


# =========================================================
# ACCEPTED DATA
# =========================================================

accepted = matched[
    matched["match_accepted"]
].copy()

print(
    f"\nAccepted matches: "
    f"{len(accepted)}"
)

print(
    f"Rejected matches: "
    f"{len(matched) - len(accepted)}"
)


# =========================================================
# SAVE ALL MATCHES
# =========================================================

matched.to_csv(
    OUTPUT_FILE,
    index=False
)

print("\nSaved complete matching dataset:")

print(
    OUTPUT_FILE
)


# =========================================================
# SAVE ACCEPTED MATCHES
# =========================================================

accepted_file = (
    "data/processed/"
    "accepted_accident_road_matches.csv"
)

accepted.to_csv(
    accepted_file,
    index=False
)

print("\nSaved accepted matches:")

print(
    accepted_file
)


print("\nDone.")