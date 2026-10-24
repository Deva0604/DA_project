import pandas as pd
import osmnx as ox

ACCIDENT_FILE = "data/processed/chennai_accidents.csv"

OUTPUT_GRAPH = "data/raw/osm/saferoute_study_area.graphml"
OUTPUT_GEOJSON = "data/raw/osm/saferoute_study_area_roads.geojson"

# ---------------------------------------------------------
# Load accident coordinates
# ---------------------------------------------------------

df = pd.read_csv(ACCIDENT_FILE)

min_lat = df["latitude"].min()
max_lat = df["latitude"].max()

min_lon = df["longitude"].min()
max_lon = df["longitude"].max()

# Small geographic buffer
BUFFER = 0.01

south = min_lat - BUFFER
north = max_lat + BUFFER
west = min_lon - BUFFER
east = max_lon + BUFFER

print("=" * 70)
print("SAFEROUTE - STUDY AREA OSM DOWNLOAD")
print("=" * 70)

print("\nAccident area:")
print(f"South : {min_lat}")
print(f"North : {max_lat}")
print(f"West  : {min_lon}")
print(f"East  : {max_lon}")

print("\nOSM download area:")
print(f"South : {south}")
print(f"North : {north}")
print(f"West  : {west}")
print(f"East  : {east}")

# ---------------------------------------------------------
# Download OSM driving network
# ---------------------------------------------------------

print("\nDownloading road network...")
print("This may take several minutes.")

# OSMnx versions differ in function naming.
# This works with current OSMnx versions.

graph = ox.graph.graph_from_bbox(
    bbox=(west, south, east, north),
    network_type="drive",
    simplify=True
)

print("\nDownload complete.")
print("Nodes:", len(graph.nodes))
print("Edges:", len(graph.edges))

# ---------------------------------------------------------
# Save graph
# ---------------------------------------------------------

ox.io.save_graphml(
    graph,
    OUTPUT_GRAPH
)

# ---------------------------------------------------------
# Convert to GeoDataFrames
# ---------------------------------------------------------

nodes, edges = ox.convert.graph_to_gdfs(graph)

edges.to_file(
    OUTPUT_GEOJSON,
    driver="GeoJSON"
)

print("\nFiles saved:")
print(OUTPUT_GRAPH)
print(OUTPUT_GEOJSON)