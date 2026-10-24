import itertools
import math
import runpy
from pathlib import Path

import networkx as nx
import pandas as pd

# Reuse the existing project's routing rules and journey definitions.
ns = runpy.run_path(
    "scripts/35b_generate_diverse_routes_v2.py",
    run_name="saferoute_edge_penalty_experiment",
)

load_graph_fast = ns["load_graph_fast"]
path_edges = ns["path_edges"]
jaccard_similarity = ns["jaccard_similarity"]
parse_bool = ns["parse_bool"]
normalize_source = ns["normalize_source"]
get_attr = ns["get_attr"]

GRAPH_FILE = ns["GRAPH_FILE"]
TESTS = ns["TESTS"]
RISK_WEIGHT = ns["RISK_WEIGHT"]
MAX_CANDIDATES = 10

# Experimental penalty multipliers. These affect route discovery only.
PENALTIES = [1.5, 2.0, 3.0, 5.0]

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "processed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

print(f"Loading graph: {GRAPH_FILE}")
graph = load_graph_fast(GRAPH_FILE)

routing = nx.DiGraph()
routing.add_nodes_from(graph.nodes(data=True))

for u, v, key, data in graph.edges(keys=True, data=True):
    if parse_bool(data.get("road_closure", False)):
        continue

    if normalize_source(data.get("risk_source", "")) == "closed":
        continue

    travel_time = get_attr(data, "routing_travel_time", 0.0)
    distance = get_attr(data, "length", 0.0)
    risk = get_attr(data, "dynamic_risk", 5.0)

    if not all(math.isfinite(x) for x in (travel_time, distance, risk)):
        continue
    if travel_time <= 0 or distance < 0:
        continue

    base_weight = travel_time * (
        1.0 + RISK_WEIGHT * max(0.0, risk) / 100.0
    )

    if not math.isfinite(base_weight) or base_weight <= 0:
        continue

    edge_data = dict(data)
    edge_data["original_key"] = key
    edge_data["travel_time"] = travel_time
    edge_data["length"] = distance
    edge_data["dynamic_risk"] = risk
    edge_data["base_weight"] = base_weight

    old = routing.get_edge_data(u, v)
    if old is None or base_weight < old.get(
        "base_weight", float("inf")
    ):
        routing.add_edge(u, v, **edge_data)

coordinates = {}
for node, data in graph.nodes(data=True):
    try:
        coordinates[node] = (float(data["x"]), float(data["y"]))
    except (KeyError, TypeError, ValueError):
        continue


def nearest_node(lon, lat):
    return min(
        coordinates,
        key=lambda node: (
            (coordinates[node][0] - lon) ** 2
            + (coordinates[node][1] - lat) ** 2
        ),
    )


def calculate_metrics(path):
    edges = path_edges(routing, path)

    travel_time = sum(
        routing[u][v]["travel_time"]
        for u, v in zip(path[:-1], path[1:])
    )

    distance = sum(
        routing[u][v]["length"]
        for u, v in zip(path[:-1], path[1:])
    )

    risks = [
        max(0.0, routing[u][v]["dynamic_risk"])
        for u, v in zip(path[:-1], path[1:])
    ]

    if distance > 0:
        weighted_risk = sum(
            risk * routing[u][v]["length"]
            for (u, v), risk in zip(
                zip(path[:-1], path[1:]), risks
            )
        ) / distance
    else:
        weighted_risk = 0.0

    return {
        "edges": edges,
        "travel_time_min": travel_time / 60.0,
        "distance_km": distance / 1000.0,
        "avg_historical_risk": sum(
            routing[u][v].get("historical_risk", 10.0)
            for u, v in zip(path[:-1], path[1:])
        ) / max(len(path) - 1, 1),
        "avg_traffic_risk": sum(
            routing[u][v].get("traffic_risk", 0.0)
            for u, v in zip(path[:-1], path[1:])
        ) / max(len(path) - 1, 1),
        "avg_weather_risk": sum(
            routing[u][v].get("weather_risk", 0.0)
            for u, v in zip(path[:-1], path[1:])
        ) / max(len(path) - 1, 1),
        "avg_dynamic_risk": sum(
            routing[u][v]["dynamic_risk"]
            for u, v in zip(path[:-1], path[1:])
        ) / max(len(path) - 1, 1),
        "distance_weighted_dynamic_risk": weighted_risk,
        "edge_count": len(edges),
    }


candidate_rows = []
pair_rows = []

for test in TESTS:
    test_id = test["test_id"]
    origin = nearest_node(
        test["origin_lon"], test["origin_lat"]
    )
    destination = nearest_node(
        test["destination_lon"], test["destination_lat"]
    )

    print(
        f"\nJourney {test_id}: "
        f"{test['origin']} -> {test['destination']}"
    )

    if not nx.has_path(routing, origin, destination):
        print("  No available route.")
        continue

    # Store original weights; penalties are temporary.
    original_weights = {
        (u, v): data["base_weight"]
        for u, v, data in routing.edges(data=True)
    }

    selected = []
    seen_paths = set()

    try:
        # First candidate is the unmodified fastest risk-aware route.
        for attempt, penalty in enumerate(
            [1.0] + PENALTIES, start=1
        ):
            if len(selected) >= MAX_CANDIDATES:
                break

            # Reset all search weights before each attempt.
            for u, v, data in routing.edges(data=True):
                data["candidate_weight"] = original_weights[(u, v)]

            # Discourage reusing directed edges from prior candidates.
            if penalty > 1.0:
                for candidate in selected:
                    for u, v in zip(
                        candidate["path"][:-1],
                        candidate["path"][1:],
                    ):
                        routing[u][v]["candidate_weight"] *= penalty

            try:
                path = nx.shortest_path(
                    routing,
                    origin,
                    destination,
                    weight="candidate_weight",
                    method="dijkstra",
                )
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                print(f"  Attempt {attempt}: no path found.")
                continue

            path_signature = tuple(path)
            if path_signature in seen_paths:
                continue

            seen_paths.add(path_signature)
            metrics = calculate_metrics(path)

            selected.append({
                "path": path,
                **metrics,
                "discovery_penalty": penalty,
            })

            print(
                f"  Candidate {len(selected)}: "
                f"{metrics['travel_time_min']:.2f} min, "
                f"{metrics['distance_km']:.2f} km, "
                f"dynamic risk {metrics['avg_dynamic_risk']:.2f}, "
                f"penalty {penalty:.1f}x"
            )

        # Restore original weights even after candidate generation.
        for u, v, data in routing.edges(data=True):
            data["candidate_weight"] = original_weights[(u, v)]

    finally:
        for u, v, data in routing.edges(data=True):
            data["candidate_weight"] = original_weights[(u, v)]

    for index, candidate in enumerate(selected, start=1):
        candidate_rows.append({
            "test_id": test_id,
            "origin": test["origin"],
            "destination": test["destination"],
            "candidate_rank": index,
            "node_path": "|".join(map(str, candidate["path"])),
            "discovery_penalty": candidate["discovery_penalty"],
            "travel_time_min": candidate["travel_time_min"],
            "distance_km": candidate["distance_km"],
            "avg_historical_risk": candidate["avg_historical_risk"],
            "avg_traffic_risk": candidate["avg_traffic_risk"],
            "avg_weather_risk": candidate["avg_weather_risk"],
            "avg_dynamic_risk": candidate["avg_dynamic_risk"],
            "distance_weighted_dynamic_risk": candidate["distance_weighted_dynamic_risk"],
            "edge_count": candidate["edge_count"],
        })

    overlaps = []
    for (i, a), (j, b) in itertools.combinations(
        enumerate(selected, start=1), 2
    ):
        similarity = jaccard_similarity(a["edges"], b["edges"])
        overlaps.append(similarity)

        pair_rows.append({
            "test_id": test_id,
            "origin": test["origin"],
            "destination": test["destination"],
            "route_a": i,
            "route_b": j,
            "jaccard_similarity": similarity,
            "overlap_percent": similarity * 100,
        })

    if overlaps:
        print(
            f"  Pairwise overlap: min={min(overlaps):.1%}, "
            f"median={pd.Series(overlaps).median():.1%}, "
            f"max={max(overlaps):.1%}"
        )

        for threshold in (0.50, 0.60, 0.70):
            count = sum(value <= threshold for value in overlaps)
            print(
                f"  Pairs at or below {threshold:.0%} overlap: "
                f"{count}/{len(overlaps)}"
            )
    else:
        print("  Only one unique route found; no pairwise overlap.")

candidate_file = OUTPUT_DIR / "edge_penalty_candidates.csv"
pair_file = OUTPUT_DIR / "edge_penalty_pairs.csv"

pd.DataFrame(candidate_rows).to_csv(candidate_file, index=False)
pd.DataFrame(pair_rows).to_csv(pair_file, index=False)

print("\nExperiment complete.")
print(f"Candidate metrics: {candidate_file}")
print(f"Pairwise overlaps:  {pair_file}")
