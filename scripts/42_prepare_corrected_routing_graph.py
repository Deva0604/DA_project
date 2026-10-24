from pathlib import Path
import math
import networkx as nx

INPUT = Path("data/processed/saferoute_routing_graph_v3.graphml")
OUTPUT = Path("data/processed/saferoute_routing_graph_v4.graphml")

print("Loading original graph with NetworkX...")

G = nx.read_graphml(
    INPUT,
    node_type=int,
    force_multigraph=True,
)

print(f"Loaded {G.number_of_nodes():,} nodes and {G.number_of_edges():,} edges.")

def to_float(value):
    try:
        number = float(value)
        if math.isfinite(number):
            return number
    except (TypeError, ValueError):
        pass
    return None

def to_bool(value):
    if isinstance(value, bool):
        return value

    if value is None:
        return False

    text = str(value).strip().lower()

    if text in {"true", "1", "yes"}:
        return True

    if text in {"false", "0", "no", ""}:
        return False

    raise ValueError(f"Unrecognized Boolean value: {value!r}")

converted = 0
closed_edges = 0
recalculated_times = 0
recalculated_weights = 0
invalid_lengths = 0

for u, v, key, data in G.edges(keys=True, data=True):
    # Convert closure flag before doing any routing calculations.
    data["road_closure"] = to_bool(data.get("road_closure", False))

    if data["road_closure"]:
        closed_edges += 1
        # Closed edges remain in the graph for auditability.
        # The routing engine must exclude them.
        continue

    # Convert length to a numeric value.
    length = to_float(data.get("length"))

    if length is None or length <= 0:
        invalid_lengths += 1
        continue

    data["length"] = length
    converted += 1

    # Convert available numeric risk attributes.
    for attr in [
        "dynamic_risk",
        "historical_risk",
        "traffic_risk",
        "weather_risk",
        "routing_travel_time",
        "routing_weight",
        "safety_weight",
        "balanced_weight",
    ]:
        value = to_float(data.get(attr))
        if value is not None:
            data[attr] = value

    # Existing routing time is preserved if valid.
    travel_time = to_float(data.get("routing_travel_time"))

    if travel_time is None or travel_time <= 0:
        # Estimate speed from OSM maxspeed when available.
        # Default to 30 km/h when speed data is missing/unusable.
        speed_kph = None
        maxspeed = data.get("maxspeed")

        if maxspeed is not None:
            digits = "".join(
                ch if ch.isdigit() or ch == "." else " "
                for ch in str(maxspeed)
            ).split()

            if digits:
                candidate = to_float(digits[0])
                if candidate is not None and 5 <= candidate <= 130:
                    speed_kph = candidate

        if speed_kph is None:
            speed_kph = 30.0

        travel_time = length / (speed_kph * 1000 / 3600)
        data["routing_travel_time"] = travel_time
        recalculated_times += 1

    risk = to_float(data.get("dynamic_risk"))
    if risk is None:
        risk = 10.0
        data["dynamic_risk"] = risk

    risk = max(0.0, min(100.0, risk))

    # Risk-adjusted cost, in seconds.
    expected_routing_weight = travel_time * (1.0 + 0.75 * risk / 100.0)

    current_routing_weight = to_float(data.get("routing_weight"))

    if current_routing_weight is None or current_routing_weight <= 0:
        data["routing_weight"] = expected_routing_weight
        recalculated_weights += 1

    # Preserve existing valid safety and balanced weights.
    # Supply values only when they are missing or invalid.
    current_safety_weight = to_float(data.get("safety_weight"))
    if current_safety_weight is None or current_safety_weight <= 0:
        data["safety_weight"] = length * (risk + 1.0)
    
    current_balanced_weight = to_float(data.get("balanced_weight"))
    if current_balanced_weight is None or current_balanced_weight <= 0:
        data["balanced_weight"] = expected_routing_weight

    # Keep the graph's risk scores and source classifications unchanged.
    # Store normalized numeric values for downstream calculations.
    for attr in ["historical_risk", "traffic_risk", "weather_risk"]:
        value = to_float(data.get(attr))
        if value is not None:
            data[attr] = value

print("\nSaving corrected graph...")
nx.write_graphml(G, OUTPUT)

print("\nCORRECTION SUMMARY")
print("-" * 55)
print(f"Nodes:                    {G.number_of_nodes():,}")
print(f"Edges:                    {G.number_of_edges():,}")
print(f"Open edges processed:     {converted:,}")
print(f"Closed edges preserved:   {closed_edges:,}")
print(f"Invalid lengths:          {invalid_lengths:,}")
print(f"Travel times recalculated:{recalculated_times:>5,}")
print(f"Routing weights repaired: {recalculated_weights:,}")
print(f"Output: {OUTPUT}")
print(f"File size: {OUTPUT.stat().st_size / (1024 * 1024):.2f} MB")
print("\nPreparation complete.")
