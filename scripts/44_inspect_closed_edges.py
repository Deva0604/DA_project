import networkx as nx
from collections import Counter

path = "data/processed/saferoute_routing_graph_v4.graphml"

print("Loading corrected graph...")
G = nx.read_graphml(
    path,
    node_type=int,
    force_multigraph=True,
)

closed = []
length_types = Counter()

for u, v, key, data in G.edges(keys=True, data=True):
    if data.get("road_closure") is True:
        length = data.get("length")
        length_types[type(length).__name__] += 1

        closed.append({
            "from": u,
            "to": v,
            "key": key,
            "length": length,
            "length_type": type(length).__name__,
            "dynamic_risk": data.get("dynamic_risk"),
            "routing_weight": data.get("routing_weight"),
            "routing_travel_time": data.get("routing_travel_time"),
            "road_closure": data.get("road_closure"),
        })

print("\nClosed edges:", len(closed))
print("Closed-edge length types:", dict(length_types))

print("\nFirst 5 closed edges:")
for edge in closed[:5]:
    print(edge)

print("\nInspection complete.")
