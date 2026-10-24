from pathlib import Path
import math
import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/saferoute_routing_graph_v5.graphml"
OUTPUT = ROOT / "data/processed/saferoute_routing_graph_v6.graphml"

# Conservative modeling assumptions for urban Chennai.
# These are not measured or live traffic speeds.
DEFAULT_SPEEDS_KPH = {
    "motorway": 60.0,
    "motorway_link": 35.0,
    "trunk": 45.0,
    "trunk_link": 30.0,
    "primary": 35.0,
    "primary_link": 25.0,
    "secondary": 30.0,
    "secondary_link": 22.0,
    "tertiary": 25.0,
    "tertiary_link": 20.0,
    "residential": 20.0,
    "living_street": 10.0,
    "unclassified": 20.0,
    "service": 10.0,
    "road": 20.0,
}

def finite_float(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None

def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}

def parse_maxspeed(value):
    """Parse a plausible numeric speed; ignore unusable or ambiguous values."""
    if value is None:
        return None

    if isinstance(value, (list, tuple)):
        candidates = [parse_maxspeed(item) for item in value]
        candidates = [speed for speed in candidates if speed is not None]
        return min(candidates) if candidates else None

    text = str(value).strip().lower()
    if not text:
        return None

    mph = "mph" in text
    digits = "".join(ch if ch.isdigit() or ch == "." else " " for ch in text).split()
    if not digits:
        return None

    speed = finite_float(digits[0])
    if speed is None:
        return None

    if mph:
        speed *= 1.60934

    if not 5 <= speed <= 100:
        return None

    return speed

def highway_types(value):
    if isinstance(value, (list, tuple)):
        return [str(item).strip().lower() for item in value]
    return [part.strip().lower() for part in str(value or "").split(",")]

if not INPUT.exists():
    raise SystemExit(f"Input graph not found: {INPUT}")

print(f"Loading {INPUT.name}...")
G = nx.read_graphml(INPUT, node_type=int, force_multigraph=True)
print(f"Loaded {G.number_of_nodes():,} nodes and {G.number_of_edges():,} edges.")

changed = 0
closed = 0
invalid_length = 0
used_maxspeed = 0
used_road_default = 0
used_unknown_default = 0
speed_samples = []

for _, _, _, data in G.edges(keys=True, data=True):
    # Preserve and normalize the closure marker.
    is_closed = parse_bool(data.get("road_closure", False))
    data["road_closure"] = is_closed

    if is_closed:
        closed += 1
        # Keep closed edges for auditability; routing code must exclude them.
        continue

    length = finite_float(data.get("length"))
    if length is None or length <= 0:
        invalid_length += 1
        continue

    road_types = highway_types(data.get("highway"))
    road_default = next(
        (DEFAULT_SPEEDS_KPH[t] for t in road_types if t in DEFAULT_SPEEDS_KPH),
        None,
    )

    maxspeed = parse_maxspeed(data.get("maxspeed"))

    if maxspeed is not None:
        speed = maxspeed
        used_maxspeed += 1
    elif road_default is not None:
        speed = road_default
        used_road_default += 1
    else:
        speed = 20.0
        used_unknown_default += 1

    # Recalculate the travel-time field instead of preserving the old 50 km/h
    # fallback. This is a modeled free-flow estimate, not live traffic time.
    travel_time = length / (speed * 1000.0 / 3600.0)
    data["routing_travel_time"] = travel_time
    data["model_speed_kph"] = speed

    # Recalculate time-based weights while preserving risk scores.
    risk = finite_float(data.get("dynamic_risk"))
    if risk is None:
        risk = 10.0
        data["dynamic_risk"] = risk

    risk = max(0.0, min(100.0, risk))
    data["routing_weight"] = travel_time * (1.0 + 0.75 * risk / 100.0)
    data["balanced_weight"] = data["routing_weight"]

    changed += 1
    speed_samples.append(speed)

if invalid_length:
    raise SystemExit(
        f"STOP: {invalid_length} open edges have missing/invalid lengths. "
        "No output graph was saved."
    )

print(f"Saving new graph to {OUTPUT.name}...")
nx.write_graphml(G, OUTPUT)

print("\nGRAPH V6 SUMMARY")
print("-" * 48)
print(f"Nodes:                         {G.number_of_nodes():,}")
print(f"Edges:                         {G.number_of_edges():,}")
print(f"Open edges recalculated:       {changed:,}")
print(f"Closed edges preserved:       {closed:,}")
print(f"Edges using OSM maxspeed:      {used_maxspeed:,}")
print(f"Edges using road-type speeds:  {used_road_default:,}")
print(f"Edges using unknown fallback:  {used_unknown_default:,}")
print(f"Median modeled speed:          {sorted(speed_samples)[len(speed_samples)//2]:.1f} km/h")
print(f"Output size:                   {OUTPUT.stat().st_size / (1024*1024):.1f} MB")
print("\nIMPORTANT: These are modeled speed assumptions, not live traffic speeds.")
print("Next: validate route times and connectivity before switching the dashboard.")
