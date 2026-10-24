from pathlib import Path
import traceback
import osmnx as ox

path = Path("data/processed/saferoute_routing_graph_v3.graphml")

print("Testing OSMnx GraphML loading...")
print("File size:", round(path.stat().st_size / (1024 * 1024), 2), "MB")
print("OSMnx version:", ox.__version__)

try:
    graph = ox.load_graphml(filepath=path)

    print("\nSUCCESS")
    print("Nodes:", graph.number_of_nodes())
    print("Edges:", graph.number_of_edges())

    for u, v, key, data in list(graph.edges(keys=True, data=True))[:3]:
        print({
            "travel_time": data.get("travel_time"),
            "length": data.get("length"),
            "dynamic_risk": data.get("dynamic_risk"),
            "risk_source": data.get("risk_source"),
            "road_closure": data.get("road_closure"),
        })

except Exception:
    print("\nGraphML loading failed:")
    traceback.print_exc()
