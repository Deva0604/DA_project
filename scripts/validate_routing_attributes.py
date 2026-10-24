from pathlib import Path
import math
import networkx as nx

path = Path("data/processed/saferoute_routing_graph_v3.graphml")

print("Loading graph...")
G = nx.read_graphml(
    path,
    node_type=int,
    force_multigraph=True,
)

print(f"Nodes: {G.number_of_nodes():,}")
print(f"Edges: {G.number_of_edges():,}")

numeric_fields = [
    "length",
    "dynamic_risk",
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "routing_travel_time",
    "routing_weight",
    "safety_weight",
    "balanced_weight",
]

stats = {
    field: {
        "present": 0,
        "invalid": 0,
        "minimum": float("inf"),
        "maximum": float("-inf"),
        "nonpositive": 0,
    }
    for field in numeric_fields
}

closure_counts = {}
risk_sources = {}
closed_edges = 0

for _, _, _, data in G.edges(keys=True, data=True):
    closure_value = str(data.get("road_closure", "False")).strip().lower()

    closure_counts[closure_value] = closure_counts.get(closure_value, 0) + 1

    if closure_value == "true":
        closed_edges += 1

    source = data.get("risk_source", "MISSING")
    risk_sources[source] = risk_sources.get(source, 0) + 1

    for field in numeric_fields:
        value = data.get(field)

        if value is None:
            stats[field]["invalid"] += 1
            continue

        try:
            number = float(value)
        except (ValueError, TypeError):
            stats[field]["invalid"] += 1
            continue

        if not math.isfinite(number):
            stats[field]["invalid"] += 1
            continue

        stats[field]["present"] += 1
        stats[field]["minimum"] = min(stats[field]["minimum"], number)
        stats[field]["maximum"] = max(stats[field]["maximum"], number)

        if number <= 0:
            stats[field]["nonpositive"] += 1

print("\nNUMERIC FIELD VALIDATION")
print("-" * 65)

for field, result in stats.items():
    minimum = result["minimum"]
    maximum = result["maximum"]

    if result["present"] == 0:
        minimum_text = "N/A"
        maximum_text = "N/A"
    else:
        minimum_text = f"{minimum:.6f}"
        maximum_text = f"{maximum:.6f}"

    print(f"\n{field}")
    print(f"  Valid numeric values: {result['present']:,}")
    print(f"  Missing/invalid:      {result['invalid']:,}")
    print(f"  Minimum:              {minimum_text}")
    print(f"  Maximum:              {maximum_text}")
    print(f"  Nonpositive values:   {result['nonpositive']:,}")

print("\nROAD CLOSURE VALUES")
print("-" * 65)
print(closure_counts)
print("Closed edges:", closed_edges)

print("\nRISK SOURCE COUNTS")
print("-" * 65)

for source, count in sorted(
    risk_sources.items(),
    key=lambda item: item[1],
    reverse=True,
):
    print(f"{source}: {count:,}")

print("\nVALIDATION COMPLETE")
