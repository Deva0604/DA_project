import os
import sys

import pandas as pd
import geopandas as gpd
import osmnx as ox


# ============================================================
# SAFEROUTE - PREPARE TRAFFIC TARGET ROADS
# ============================================================

RISK_FILE = "data/processed/road_accident_risk.csv"

OSM_FILE = "data/raw/osm/saferoute_study_area.graphml"

OUTPUT_FILE = (
    "data/processed/road_traffic_targets.csv"
)


print("=" * 70)
print("SAFEROUTE - TRAFFIC TARGET PREPARATION")
print("=" * 70)


# ============================================================
# 1. LOAD HISTORICAL ROAD RISK
# ============================================================

print()
print("[1/5] Loading historical road-risk dataset...")

try:
    risk_df = pd.read_csv(RISK_FILE)
except Exception as e:
    print(f"ERROR loading risk dataset: {e}")
    sys.exit(1)

print(f"Road segments with historical accidents: {len(risk_df)}")


# ============================================================
# 2. LOAD OSM GRAPH
# ============================================================

print()
print("[2/5] Loading OSM study-area graph...")

try:
    G = ox.load_graphml(OSM_FILE)
except Exception as e:
    print(f"ERROR loading OSM graph: {e}")
    sys.exit(1)

print(f"OSM nodes : {len(G.nodes):,}")
print(f"OSM edges : {len(G.edges):,}")

print(f"Graph CRS : {G.graph.get('crs')}")


# ============================================================
# 3. CONVERT OSM EDGES TO GEODATAFRAME
# ============================================================

print()
print("[3/5] Converting OSM edges to GeoDataFrame...")

edges = ox.graph_to_gdfs(
    G,
    nodes=False,
    edges=True
)

edges = edges.reset_index()

print(f"OSM edge records: {len(edges):,}")

print()
print("Available edge columns:")
print(edges.columns.tolist())


# ============================================================
# 4. MATCH HISTORICAL ROADS TO OSM GEOMETRY
# ============================================================

print()
print("[4/5] Matching historical roads to OSM geometry...")


# Make sure IDs use the same datatype
risk_df["osm_u"] = risk_df["osm_u"].astype(str)
risk_df["osm_v"] = risk_df["osm_v"].astype(str)
risk_df["osm_key"] = risk_df["osm_key"].astype(str)

edges["u"] = edges["u"].astype(str)
edges["v"] = edges["v"].astype(str)
edges["key"] = edges["key"].astype(str)


# Rename OSM identifiers
edges = edges.rename(
    columns={
        "u": "osm_u",
        "v": "osm_v",
        "key": "osm_key"
    }
)


# Keep only columns needed for traffic targeting
geometry_columns = [
    "osm_u",
    "osm_v",
    "osm_key",
    "geometry"
]

edges_small = edges[
    geometry_columns
].copy()


# Merge historical risk with road geometry
merged = risk_df.merge(
    edges_small,
    on=[
        "osm_u",
        "osm_v",
        "osm_key"
    ],
    how="left"
)


matched = merged["geometry"].notna().sum()

print()
print(f"Historical roads : {len(merged):,}")
print(f"Geometry matched : {matched:,}")
print(f"Geometry missing : {len(merged) - matched:,}")


# ============================================================
# 5. CREATE REPRESENTATIVE TRAFFIC POINT
# ============================================================

print()
print("[5/5] Creating representative traffic coordinates...")


# Convert to GeoDataFrame
gdf = gpd.GeoDataFrame(
    merged,
    geometry="geometry",
    crs="EPSG:4326"
)


# Project to metric CRS
gdf_metric = gdf.to_crs(
    "EPSG:32644"
)


# Representative point is safer than blindly using
# the first coordinate of a long road.
gdf_metric["traffic_point"] = (
    gdf_metric.geometry.representative_point()
)


# Convert representative points back to WGS84
points = gpd.GeoSeries(
    gdf_metric["traffic_point"],
    crs="EPSG:32644"
).to_crs("EPSG:4326")


gdf["traffic_point"] = points


# Extract coordinates
gdf["traffic_longitude"] = (
    gdf["traffic_point"].x
)

gdf["traffic_latitude"] = (
    gdf["traffic_point"].y
)


# Remove geometry columns from CSV
output_columns = [
    "osm_u",
    "osm_v",
    "osm_key",

    "road_name",
    "highway",

    "road_length_m",

    "accident_count",
    "fatal_count",
    "major_count",
    "minor_count",

    "historical_risk",
    "risk_category",

    "traffic_latitude",
    "traffic_longitude"
]


output = gdf[
    output_columns
].copy()


# Only keep roads with valid coordinates
output = output.dropna(
    subset=[
        "traffic_latitude",
        "traffic_longitude"
    ]
)


# Save
output.to_csv(
    OUTPUT_FILE,
    index=False
)


# ============================================================
# SUMMARY
# ============================================================

print()
print("=" * 70)
print("TRAFFIC TARGET DATASET CREATED")
print("=" * 70)

print()
print(
    f"Traffic target roads : "
    f"{len(output):,}"
)

print(
    f"Latitude range      : "
    f"{output['traffic_latitude'].min():.6f} "
    f"to "
    f"{output['traffic_latitude'].max():.6f}"
)

print(
    f"Longitude range     : "
    f"{output['traffic_longitude'].min():.6f} "
    f"to "
    f"{output['traffic_longitude'].max():.6f}"
)

print()
print("Sample traffic targets:")
print(
    output[
        [
            "osm_u",
            "osm_v",
            "historical_risk",
            "traffic_latitude",
            "traffic_longitude"
        ]
    ]
    .head(10)
    .to_string(index=False)
)

print()
print(f"Saved:")
print(OUTPUT_FILE)

print()
print("=" * 70)
print("DONE")
print("=" * 70)
