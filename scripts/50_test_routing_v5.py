import math
import time
import networkx as nx
import osmnx as ox
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRAPH_FILE = ROOT / "data/processed/saferoute_routing_graph_v5.graphml"

print("=" * 65)
print("SAFEROUTE — V5 ROUTING TEST")
print("=" * 65)

start = time.time()

print("Loading graph...")
G = nx.read_graphml(
    GRAPH_FILE,
    node_type=int,
    force_multigraph=True,
)

print(f"Nodes: {G.number_of_nodes():,}")
print(f"Edges: {G.number_of_edges():,}")

# Build a directed graph containing only usable, open roads.
R = nx.DiGraph()
R.add_nodes_from(G.nodes(data=True))

closed_count = 0
invalid_count = 0

for u, v, key, data in G.edges(keys=True, data=True):
    closure = str(data.get("road_closure", "false")).strip().lower()
    source = str(data.get("risk_source", "")).strip().lower()

    if closure in {"true", "1", "yes", "y", "t"} or "closed" in source:
        closed_count += 1
        continue

    try:
        travel_time = float(data.get("routing_travel_time", 0))
        distance = float(data.get("length", 0))
        risk = float(data.get("dynamic_risk", 5))
    except (TypeError, ValueError):
        invalid_count += 1
        continue

    if not all(math.isfinite(x) for x in (travel_time, distance, risk)):
        invalid_count += 1
        continue

    if travel_time <= 0 or distance < 0:
        invalid_count += 1
        continue

    weight = travel_time * (1 + 0.75 * max(0, risk) / 100)

    if not math.isfinite(weight) or weight <= 0:
        invalid_count += 1
        continue

    existing = R.get_edge_data(u, v)

    if existing is None or weight < existing["weight"]:
        R.add_edge(
            u,
            v,
            weight=weight,
            travel_time=travel_time,
            length=distance,
        )

print(f"Closed edges excluded: {closed_count:,}")
print(f"Invalid edges excluded: {invalid_count:,}")
print(f"Usable directed edges: {R.number_of_edges():,}")

# Test Chennai Central -> Anna Nagar.
origin = ox.distance.nearest_nodes(
    G, X=80.2707, Y=13.0827
)
destination = ox.distance.nearest_nodes(
    G, X=80.2101, Y=13.0850
)

print(f"Origin node: {origin}")
print(f"Destination node: {destination}")

if origin not in R or destination not in R:
    print("RESULT: FAIL — origin or destination is missing.")
elif not nx.has_path(R, origin, destination):
    print("RESULT: FAIL — no path exists after excluding closed roads.")
else:
    path = nx.shortest_path(
        R, origin, destination, weight="weight"
    )

    distance_m = sum(
        R[u][v]["length"] for u, v in zip(path[:-1], path[1:])
    )
    travel_time_s = sum(
        R[u][v]["travel_time"] for u, v in zip(path[:-1], path[1:])
    )

    print(f"RESULT: PASS — route found with {len(path)} nodes.")
    print(f"Distance: {distance_m / 1000:.2f} km")
    print(f"Estimated travel time: {travel_time_s / 60:.2f} minutes")

print(f"Elapsed time: {time.time() - start:.1f} seconds")
