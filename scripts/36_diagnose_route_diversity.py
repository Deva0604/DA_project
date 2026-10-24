import itertools
import runpy
import networkx as nx
import pandas as pd

# Load the existing generator definitions without running main().
ns = runpy.run_path(
    "scripts/35b_generate_diverse_routes_v2.py",
    run_name="saferoute_diversity_diagnostic",
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
MAX_RAW_CANDIDATES = ns["MAX_RAW_CANDIDATES"]
THRESHOLDS = ns["DIVERSITY_THRESHOLDS"]

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

    if travel_time <= 0 or distance < 0:
        continue

    weight = travel_time * (
        1.0 + RISK_WEIGHT * max(0.0, risk) / 100.0
    )

    if weight <= 0:
        continue

    edge_data = dict(data)
    edge_data["original_key"] = key
    edge_data["travel_time"] = travel_time
    edge_data["length"] = distance
    edge_data["dynamic_risk"] = risk
    edge_data["candidate_weight"] = weight

    old = routing.get_edge_data(u, v)
    if old is None or weight < old.get("candidate_weight", float("inf")):
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

pair_rows = []
candidate_rows = []

for test in TESTS:
    test_id = test["test_id"]
    origin = nearest_node(test["origin_lon"], test["origin_lat"])
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

    generator = nx.shortest_simple_paths(
        routing, origin, destination, weight="candidate_weight"
    )

    candidates = []
    for rank, path in enumerate(
        itertools.islice(generator, MAX_RAW_CANDIDATES), start=1
    ):
        edges = path_edges(routing, path)
        travel_time = sum(
            routing[u][v]["travel_time"]
            for u, v in zip(path[:-1], path[1:])
        )
        distance = sum(
            routing[u][v]["length"]
            for u, v in zip(path[:-1], path[1:])
        )

        candidate = {
            "test_id": test_id,
            "rank": rank,
            "path": path,
            "edges": edges,
            "travel_time_min": travel_time,
            "distance_km": distance / 1000,
        }
        candidates.append(candidate)

        candidate_rows.append({
            "test_id": test_id,
            "origin": test["origin"],
            "destination": test["destination"],
            "candidate_rank": rank,
            "travel_time_min": travel_time,
            "distance_km": distance / 1000,
            "edge_count": len(edges),
        })

    if not candidates:
        print("  No candidates generated.")
        continue

    overlaps = []
    for a, b in itertools.combinations(candidates, 2):
        similarity = jaccard_similarity(a["edges"], b["edges"])
        overlaps.append(similarity)
        pair_rows.append({
            "test_id": test_id,
            "route_a": a["rank"],
            "route_b": b["rank"],
            "jaccard_similarity": similarity,
            "overlap_percent": similarity * 100,
        })

    print(f"  Candidates generated: {len(candidates)}")
    print(
        f"  Pairwise overlap: min={min(overlaps):.1%}, "
        f"median={pd.Series(overlaps).median():.1%}, "
        f"max={max(overlaps):.1%}"
    )

    for threshold in THRESHOLDS:
        eligible = sum(value <= threshold for value in overlaps)
        print(
            f"  Candidate pairs at or below {threshold:.0%} overlap: "
            f"{eligible}/{len(overlaps)}"
        )

pd.DataFrame(candidate_rows).to_csv(
    "data/processed/route_diversity_diagnostic_candidates.csv",
    index=False,
)
pd.DataFrame(pair_rows).to_csv(
    "data/processed/route_diversity_diagnostic_pairs.csv",
    index=False,
)

print("\nDiagnostic complete.")
print("Candidate metrics: data/processed/route_diversity_diagnostic_candidates.csv")
print("Pairwise overlap:  data/processed/route_diversity_diagnostic_pairs.csv")
