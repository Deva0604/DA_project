from pathlib import Path
import math
import networkx as nx

INPUT = Path("data/processed/saferoute_routing_graph_v4.graphml")
OUTPUT = Path("data/processed/saferoute_routing_graph_v5.graphml")

print("Loading v4 graph...")
G = nx.read_graphml(
    INPUT,
    node_type=int,
    force_multigraph=True,
)

converted_lengths = 0
closed_edges = 0
invalid_lengths = 0
closed_infinite_weights = 0
open_edges = 0

for _, _, _, data in G.edges(keys=True, data=True):
    # Convert every edge length, including closed edges.
    try:
        length = float(data["length"])
        if not math.isfinite(length) or length <= 0:
            invalid_lengths += 1
        else:
            data["length"] = length
            converted_lengths += 1
    except (KeyError, TypeError, ValueError):
        invalid_lengths += 1

    # Normalize the closure flag.
    closure = data.get("road_closure", False)

    if isinstance(closure, bool):
        is_closed = closure
    else:
        is_closed = str(closure).strip().lower() in {
            "true", "1", "yes"
        }

    data["road_closure"] = is_closed

    if is_closed:
        closed_edges += 1

        # Preserve closed-edge infinite weights.
        weight = data.get("routing_weight")
        try:
            if math.isinf(float(weight)):
                closed_infinite_weights += 1
        except (TypeError, ValueError):
            pass
    else:
        open_edges += 1

print("Saving corrected graph...")
nx.write_graphml(G, OUTPUT)

print("\nSTEP 45 SUMMARY")
print("-" * 50)
print(f"Edges with valid numeric lengths: {converted_lengths:,}")
print(f"Invalid lengths: {invalid_lengths:,}")
print(f"Open edges: {open_edges:,}")
print(f"Closed edges: {closed_edges:,}")
print(f"Closed edges with infinite weights: {closed_infinite_weights:,}")
print(f"Output: {OUTPUT}")
print(f"File size: {OUTPUT.stat().st_size / (1024 * 1024):.2f} MB")

if invalid_lengths:
    raise SystemExit("FAILED: Some lengths remain invalid.")

print("\nSTEP 45 PASSED")
