import osmnx as ox

PLACE = "Chennai, Tamil Nadu, India"

print("Downloading Chennai road network...")
print("This may take a few minutes.")

graph = ox.graph.graph_from_place(
    PLACE,
    network_type="drive",
    simplify=True
)

print()
print("Download complete.")
print("Nodes:", len(graph.nodes))
print("Edges:", len(graph.edges))

# Save routing graph
ox.io.save_graphml(
    graph,
    "data/raw/osm/chennai_drive_network.graphml"
)

# Convert roads to GeoDataFrame
nodes, edges = ox.convert.graph_to_gdfs(graph)

# Save road network
edges.to_file(
    "data/raw/osm/chennai_roads.geojson",
    driver="GeoJSON"
)

print()
print("Files created:")
print("1. data/raw/osm/chennai_drive_network.graphml")
print("2. data/raw/osm/chennai_roads.geojson")