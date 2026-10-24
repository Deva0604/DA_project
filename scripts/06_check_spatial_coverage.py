import pandas as pd
import geopandas as gpd

ACCIDENT_FILE = "data/processed/chennai_accidents.csv"
ROAD_FILE = "data/raw/osm/chennai_roads.geojson"

print("=" * 70)
print("SAFEROUTE - SPATIAL COVERAGE CHECK")
print("=" * 70)

# ---------------------------------------------------------
# Load accidents
# ---------------------------------------------------------

accidents = pd.read_csv(ACCIDENT_FILE)

accidents_gdf = gpd.GeoDataFrame(
    accidents,
    geometry=gpd.points_from_xy(
        accidents["longitude"],
        accidents["latitude"]
    ),
    crs="EPSG:4326"
)

# ---------------------------------------------------------
# Load roads
# ---------------------------------------------------------

roads = gpd.read_file(ROAD_FILE)

print("\nAccident bounding box:")
print(accidents_gdf.total_bounds)

print("\nRoad bounding box:")
print(roads.total_bounds)

print("\nAccident CRS:")
print(accidents_gdf.crs)

print("\nRoad CRS:")
print(roads.crs)

# ---------------------------------------------------------
# Calculate centers
# ---------------------------------------------------------

print("\nAccident center:")
print(
    accidents_gdf.geometry.x.mean(),
    accidents_gdf.geometry.y.mean()
)

print("\nRoad center:")
print(
    roads.geometry.centroid.x.mean(),
    roads.geometry.centroid.y.mean()
)

# ---------------------------------------------------------
# Count accidents within road bounding box
# ---------------------------------------------------------

minx, miny, maxx, maxy = roads.total_bounds

inside = (
    (accidents["longitude"] >= minx) &
    (accidents["longitude"] <= maxx) &
    (accidents["latitude"] >= miny) &
    (accidents["latitude"] <= maxy)
)

print("\nAccidents inside OSM road bounding box:")
print(inside.sum())

print("Accidents outside:")
print((~inside).sum())

print("\nPercentage inside:")
print(round(inside.mean() * 100, 2), "%")