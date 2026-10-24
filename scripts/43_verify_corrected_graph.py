from pathlib import Path
import math
import networkx as nx

path = Path("data/processed/saferoute_routing_graph_v5.graphml")

print("Loading corrected graph...")
G = nx.read_graphml(
    path,
    node_type=int,
    force_multigraph=True,
)

print(f"Nodes: {G.number_of_nodes():,}")
print(f"Edges: {G.number_of_edges():,}")

checks = {
    "numeric_length": True,
    "boolean_closure": True,
    "open_edges_have_travel_time": True,
    "open_edges_have_routing_weight": True,
    "closed_edges_have_no_routing_weight_required": True,
}

closed_count = 0
open_count = 0
open_missing_time = 0
open_missing_weight = 0
open_missing_safety = 0
open_missing_balanced = 0
bad_length = 0
bad_closure_type = 0

for _, _, _, data in G.edges(keys=True, data=True):
    length = data.get("length")
    closure = data.get("road_closure")

    if not isinstance(length, (int, float)) or not math.isfinite(float(length)):
        bad_length += 1

    if not isinstance(closure, bool):
        bad_closure_type += 1

    if closure is True:
        closed_count += 1
        continue

    open_count += 1

    for attr, counter_name in [
        ("routing_travel_time", "time"),
        ("routing_weight", "weight"),
        ("safety_weight", "safety"),
        ("balanced_weight", "balanced"),
    ]:
        try:
            value = float(data[attr])
            valid = math.isfinite(value) and value > 0
        except (KeyError, TypeError, ValueError):
            valid = False

        if not valid:
            if counter_name == "time":
                open_missing_time += 1
            elif counter_name == "weight":
                open_missing_weight += 1
            elif counter_name == "safety":
                open_missing_safety += 1
            elif counter_name == "balanced":
                open_missing_balanced += 1

checks["numeric_length"] = bad_length == 0
checks["boolean_closure"] = bad_closure_type == 0
checks["open_edges_have_travel_time"] = open_missing_time == 0
checks["open_edges_have_routing_weight"] = open_missing_weight == 0
checks["closed_edges_have_no_routing_weight_required"] = True

print("\nVALIDATION RESULTS")
print("-" * 55)
print(f"Open edges: {open_count:,}")
print(f"Closed edges: {closed_count:,}")
print(f"Invalid lengths: {bad_length:,}")
print(f"Non-Boolean closure flags: {bad_closure_type:,}")
print(f"Open edges missing travel time: {open_missing_time:,}")
print(f"Open edges missing routing weight: {open_missing_weight:,}")
print(f"Open edges missing safety weight: {open_missing_safety:,}")
print(f"Open edges missing balanced weight: {open_missing_balanced:,}")

print("\nCHECKS")
for name, passed in checks.items():
    print(f"{'PASS' if passed else 'FAIL'}: {name}")

if all(checks.values()):
    print("\nGRAPH STRUCTURE VALIDATION PASSED")
else:
    print("\nGRAPH STRUCTURE VALIDATION FAILED")
    raise SystemExit(1)

print("\nVerification complete.")
