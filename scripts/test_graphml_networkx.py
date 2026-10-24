from pathlib import Path
import networkx as nx

path = Path("data/processed/saferoute_routing_graph_v3.graphml")

print("Loading GraphML with NetworkX...")
print("File size:", round(path.stat().st_size / (1024 * 1024), 2), "MB")

G = nx.read_graphml(
    path,
    node_type=int,
    force_multigraph=True,
)

print("\nGRAPH LOADED SUCCESSFULLY")
print("Nodes:", G.number_of_nodes())
print("Edges:", G.number_of_edges())

print("\nSample edge attributes:")
for u, v, key, data in list(G.edges(keys=True, data=True))[:5]:
    print({
        "length": data.get("length"),
        "dynamic_risk": data.get("dynamic_risk"),
        "risk_source": data.get("risk_source"),
        "road_closure": data.get("road_closure"),
        "travel_time": data.get("travel_time"),
    })

print("\nAttribute type counts:")
for attr in ["length", "dynamic_risk", "risk_source", "road_closure", "travel_time"]:
    counts = {}
    for _, _, _, data in G.edges(keys=True, data=True):
        if attr in data:
            typename = type(data[attr]).__name__
            counts[typename] = counts.get(typename, 0) + 1
    print(attr, counts)

print("\nInspection complete.")
