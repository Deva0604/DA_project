import os
import math
import numpy as np
import pandas as pd
import networkx as nx
import osmnx as ox


# ============================================================
# SAFEROUTE - ROUTE DIVERSITY ANALYSIS
# STEP 34
# ============================================================

GRAPH_FILE = (
    "data/processed/"
    "saferoute_routing_graph_v3.graphml"
)

VALIDATION_FILE = (
    "data/processed/"
    "route_validation_results.csv"
)

OUTPUT_FILE = (
    "data/processed/"
    "route_diversity_analysis.csv"
)

TEST_SUMMARY_FILE = (
    "data/processed/"
    "route_diversity_test_summary.csv"
)


print("=" * 75)
print("SAFEROUTE - ROUTE DIVERSITY ANALYSIS")
print("=" * 75)


# ============================================================
# HELPERS
# ============================================================

def parse_bool(value):

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    return str(value).strip().lower() in [
        "true",
        "1",
        "yes",
        "y",
    ]


def safe_float(value, default=0.0):

    try:

        value = float(value)

        if not math.isfinite(value):
            return default

        return value

    except (TypeError, ValueError):

        return default


def edge_identifier(u, v):

    return (
        str(u),
        str(v)
    )


def fix_graph_node_coords(G):
    # nx.read_graphml loads ALL attributes as strings,
    # so x/y end up as str and ox.distance.nearest_nodes
    # fails with "'str' object has no attribute 'deg2rad'".
    # Coerce them back to float in-place.
    fixed = 0
    for _, data in G.nodes(data=True):
        if "x" in data:
            try:
                data["x"] = float(data["x"])
                fixed += 1
            except (TypeError, ValueError):
                pass
        if "y" in data:
            try:
                data["y"] = float(data["y"])
            except (TypeError, ValueError):
                pass
    return fixed


def find_nearest_node(G, lon, lat):
    # Robust wrapper around ox nearest_nodes with a
    # pure-numpy haversine fallback (works even if node
    # dtypes / crs are messed up by GraphML round-trip).
    try:
        return ox.distance.nearest_nodes(
            G,
            X=float(lon),
            Y=float(lat)
        )
    except Exception:
        pass
    # Fallback: brute-force haversine over all nodes
    lon_r = math.radians(float(lon))
    lat_r = math.radians(float(lat))
    best_node = None
    best_dist = float("inf")
    for n, data in G.nodes(data=True):
        try:
            nx_lon = float(data["x"])
            nx_lat = float(data["y"])
        except (KeyError, TypeError, ValueError):
            continue
        dlon = math.radians(nx_lon) - lon_r
        dlat = math.radians(nx_lat) - lat_r
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat_r)
            * math.cos(math.radians(nx_lat))
            * math.sin(dlon / 2) ** 2
        )
        d = 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))
        if d < best_dist:
            best_dist = d
            best_node = n
    if best_node is None:
        raise RuntimeError("No routable node with x/y found.")
    return best_node


# ============================================================
# 1. CHECK FILES
# ============================================================

print("\n[1/8] Checking input files...")


if not os.path.exists(GRAPH_FILE):

    raise FileNotFoundError(
        f"Graph not found: {GRAPH_FILE}"
    )


if not os.path.exists(VALIDATION_FILE):

    raise FileNotFoundError(
        f"Validation file not found: "
        f"{VALIDATION_FILE}"
    )


print(
    f"Graph     : {GRAPH_FILE}"
)

print(
    f"Validation: {VALIDATION_FILE}"
)


# ============================================================
# 2. LOAD GRAPH
# ============================================================

print(
    "\n[2/8] Loading routing graph..."
)


try:

    G = ox.load_graphml(
        GRAPH_FILE
    )

except Exception:

    print(
        "ox.load_graphml failed."
    )

    print(
        "Using nx.read_graphml..."
    )

    G = nx.read_graphml(
        GRAPH_FILE
    )


# GraphML stores everything as strings -> fix x/y for ox
fix_graph_node_coords(G)


# Normalize CRS key for osmnx
try:
    if "crs" in G.graph and G.graph["crs"] is not None:
        G.graph["crs"] = str(G.graph["crs"])
    else:
        G.graph["crs"] = "EPSG:4326"
except Exception:
    pass


print(
    f"Nodes : {len(G.nodes):,}"
)

print(
    f"Edges : {len(G.edges):,}"
)


# ============================================================
# 3. PREPARE ROUTING GRAPH
# ============================================================

print(
    "\n[3/8] Preparing routing network..."
)


D = nx.DiGraph()


closed_edges = 0


for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    if parse_bool(
        data.get(
            "road_closure",
            False
        )
    ):

        closed_edges += 1

        continue


    travel_time = safe_float(
        data.get(
            "routing_travel_time",
            0
        )
    )


    if travel_time <= 0:

        travel_time = safe_float(
            data.get(
                "travel_time",
                0
            )
        )


    if travel_time <= 0:

        length = safe_float(
            data.get(
                "length",
                0
            )
        )


        if length > 0:

            travel_time = (
                length / 13.89
            )


    if travel_time <= 0:

        continue


    dynamic_risk = safe_float(
        data.get(
            "dynamic_risk",
            5
        ),
        5
    )


    candidate_weight = (
        travel_time
        * (
            1
            + 0.75
            * dynamic_risk
            / 100
        )
    )


    # Keep only the fastest edge
    # for each directed node pair.

    if D.has_edge(u, v):

        existing_time = safe_float(
            D[u][v].get(
                "routing_travel_time",
                float("inf")
            ),
            float("inf")
        )


        if travel_time >= existing_time:

            continue


    D.add_edge(

        u,
        v,

        routing_travel_time=travel_time,

        candidate_weight=candidate_weight,

    )


print(
    f"Routing edges       : "
    f"{len(D.edges):,}"
)

print(
    f"Closed edges removed: "
    f"{closed_edges:,}"
)


# ============================================================
# 4. LOAD VALIDATION DATA
# ============================================================

print(
    "\n[4/8] Loading validation results..."
)


df = pd.read_csv(
    VALIDATION_FILE
)


print(
    f"Validation rows : "
    f"{len(df):,}"
)


print(
    f"Validation tests: "
    f"{df['test_id'].nunique()}"
)


# ============================================================
# IMPORTANT:
#
# Step 32 saved route metrics but did not save the actual
# node sequence of every route.
#
# Therefore we reconstruct the same candidate routes using
# the same routing graph and same candidate weight.
# ============================================================

print(
    "\nReconstructing candidate routes..."
)


all_route_records = []


# ============================================================
# 5. RECONSTRUCT ROUTES
# ============================================================

print(
    "\n[5/8] Generating route edge sets..."
)


# Coordinates used in Step 32

TEST_ROUTES = [

    {
        "test_id": 1,
        "origin": "Chennai Central",
        "origin_lat": 13.0827,
        "origin_lon": 80.2707,
        "destination": "Anna Nagar",
        "dest_lat": 13.0850,
        "dest_lon": 80.2101,
    },

    {
        "test_id": 2,
        "origin": "Guindy",
        "origin_lat": 13.0067,
        "origin_lon": 80.2206,
        "destination": "T Nagar",
        "dest_lat": 13.0418,
        "dest_lon": 80.2341,
    },

    {
        "test_id": 3,
        "origin": "Adyar",
        "origin_lat": 13.0012,
        "origin_lon": 80.2565,
        "destination": "Perambur",
        "dest_lat": 13.1160,
        "dest_lon": 80.2330,
    },

    {
        "test_id": 4,
        "origin": "Velachery",
        "origin_lat": 12.9815,
        "origin_lon": 80.2180,
        "destination": "Tambaram",
        "dest_lat": 12.9249,
        "dest_lon": 80.1000,
    },

    {
        "test_id": 5,
        "origin": "Chennai Airport",
        "origin_lat": 12.9941,
        "origin_lon": 80.1709,
        "destination": "Marina Beach",
        "dest_lat": 13.0499,
        "dest_lon": 80.2824,
    },
]


K_ROUTES = 10


for test in TEST_ROUTES:

    print(
        f"\nTest {test['test_id']}: "
        f"{test['origin']} → "
        f"{test['destination']}"
    )


    origin_node = find_nearest_node(
        G,
        test["origin_lon"],
        test["origin_lat"]
    )


    destination_node = find_nearest_node(
        G,
        test["dest_lon"],
        test["dest_lat"]
    )


    # Handle GraphML string node IDs.

    if (
        origin_node not in D
        and str(origin_node) in D
    ):

        origin_node = str(
            origin_node
        )


    if (
        destination_node not in D
        and str(destination_node) in D
    ):

        destination_node = str(
            destination_node
        )


    routes = []


    try:

        generator = nx.shortest_simple_paths(

            D,

            origin_node,

            destination_node,

            weight="candidate_weight"

        )


        for route in generator:

            routes.append(
                route
            )


            if len(routes) >= K_ROUTES:

                break


    except nx.NetworkXNoPath:

        print(
            "  No path found."
        )

        continue


    print(
        f"  Routes generated: "
        f"{len(routes)}"
    )


    for route_id, route in enumerate(
        routes,
        start=1
    ):

        edges = set()


        for u, v in zip(
            route[:-1],
            route[1:]
        ):

            edges.add(
                edge_identifier(
                    u,
                    v
                )
            )


        all_route_records.append({

            "test_id":
                test["test_id"],

            "origin":
                test["origin"],

            "destination":
                test["destination"],

            "route_id":
                route_id,

            "nodes":
                route,

            "edges":
                edges,

        })


# ============================================================
# 6. CALCULATE PAIRWISE ROUTE SIMILARITY
# ============================================================

print(
    "\n[6/8] Calculating route similarity..."
)


diversity_records = []


test_summaries = []


for test in TEST_ROUTES:

    test_id = test["test_id"]


    routes = [

        item

        for item in all_route_records

        if item["test_id"] == test_id

    ]


    if not routes:

        continue


    # --------------------------------------------------------
    # Pairwise similarity
    #
    # Jaccard similarity:
    #
    # intersection / union
    #
    # 1.0 = identical
    # 0.0 = completely different
    # --------------------------------------------------------

    pairwise_values = []


    for i in range(
        len(routes)
    ):

        for j in range(
            i + 1,
            len(routes)
        ):

            route_a = routes[i]

            route_b = routes[j]


            edges_a = route_a[
                "edges"
            ]


            edges_b = route_b[
                "edges"
            ]


            intersection = len(
                edges_a
                & edges_b
            )


            union = len(
                edges_a
                | edges_b
            )


            if union > 0:

                similarity = (
                    intersection
                    / union
                )

            else:

                similarity = 1.0


            pairwise_values.append(
                similarity
            )


            diversity_records.append({

                "test_id":
                    test_id,

                "origin":
                    test["origin"],

                "destination":
                    test["destination"],

                "route_a":
                    route_a["route_id"],

                "route_b":
                    route_b["route_id"],

                "route_a_edges":
                    len(edges_a),

                "route_b_edges":
                    len(edges_b),

                "shared_edges":
                    intersection,

                "union_edges":
                    union,

                "jaccard_similarity":
                    similarity,

                "jaccard_difference":
                    1 - similarity,

            })


    # --------------------------------------------------------
    # Route edge statistics
    # --------------------------------------------------------

    edge_counts = [

        len(route["edges"])

        for route in routes

    ]


    # --------------------------------------------------------
    # Average pairwise similarity
    # --------------------------------------------------------

    if pairwise_values:

        avg_similarity = (
            sum(pairwise_values)
            / len(pairwise_values)
        )

        min_similarity = min(
            pairwise_values
        )

        max_similarity = max(
            pairwise_values
        )

    else:

        avg_similarity = 1.0

        min_similarity = 1.0

        max_similarity = 1.0


    # --------------------------------------------------------
    # Diversity score
    #
    # Higher = more different routes.
    # --------------------------------------------------------

    diversity_score = (
        1
        - avg_similarity
    ) * 100


    # --------------------------------------------------------
    # Unique edge count
    # --------------------------------------------------------

    all_edges = set()


    for route in routes:

        all_edges.update(
            route["edges"]
        )


    # --------------------------------------------------------
    # Most different pair
    # --------------------------------------------------------

    if pairwise_values:

        min_pair = min(

            [

                record

                for record
                in diversity_records

                if record["test_id"]
                == test_id

            ],

            key=lambda x:
            x["jaccard_similarity"]

        )

    else:

        min_pair = {

            "route_a": 1,

            "route_b": 1,

            "jaccard_similarity": 1.0,

        }


    # --------------------------------------------------------
    # Most similar pair
    # --------------------------------------------------------

    if pairwise_values:

        max_pair = max(

            [

                record

                for record
                in diversity_records

                if record["test_id"]
                == test_id

            ],

            key=lambda x:
            x["jaccard_similarity"]

        )

    else:

        max_pair = {

            "route_a": 1,

            "route_b": 1,

            "jaccard_similarity": 1.0,

        }


    test_summaries.append({

        "test_id":
            test_id,

        "origin":
            test["origin"],

        "destination":
            test["destination"],

        "candidate_routes":
            len(routes),

        "average_route_edges":
            sum(edge_counts)
            / len(edge_counts),

        "minimum_route_edges":
            min(edge_counts),

        "maximum_route_edges":
            max(edge_counts),

        "unique_edges_across_routes":
            len(all_edges),

        "average_pairwise_similarity":
            avg_similarity,

        "minimum_pairwise_similarity":
            min_similarity,

        "maximum_pairwise_similarity":
            max_similarity,

        "diversity_score_percent":
            diversity_score,

        "most_different_route_a":
            min_pair["route_a"],

        "most_different_route_b":
            min_pair["route_b"],

        "most_different_similarity":
            min_pair[
                "jaccard_similarity"
            ],

        "most_similar_route_a":
            max_pair["route_a"],

        "most_similar_route_b":
            max_pair["route_b"],

        "most_similar_similarity":
            max_pair[
                "jaccard_similarity"
            ],

    })


# ============================================================
# 7. PRINT RESULTS
# ============================================================

print(
    "\n"
    + "=" * 75
)

print(
    "ROUTE DIVERSITY RESULTS"
)

print(
    "=" * 75
)


for row in test_summaries:

    print(
        f"\nTest {row['test_id']}: "
        f"{row['origin']} → "
        f"{row['destination']}"
    )


    print(
        f"  Candidate routes       : "
        f"{row['candidate_routes']}"
    )


    print(
        f"  Average route edges    : "
        f"{row['average_route_edges']:.2f}"
    )


    print(
        f"  Unique edges           : "
        f"{row['unique_edges_across_routes']}"
    )


    print(
        f"  Average similarity     : "
        f"{row['average_pairwise_similarity']:.4f}"
    )


    print(
        f"  Minimum similarity     : "
        f"{row['minimum_pairwise_similarity']:.4f}"
    )


    print(
        f"  Maximum similarity     : "
        f"{row['maximum_pairwise_similarity']:.4f}"
    )


    print(
        f"  Diversity score        : "
        f"{row['diversity_score_percent']:.2f}%"
    )


    print(
        f"  Most different routes : "
        f"{int(row['most_different_route_a'])} "
        f"vs "
        f"{int(row['most_different_route_b'])}"
    )


# ============================================================
# GLOBAL DIVERSITY
# ============================================================

print(
    "\n"
    + "-" * 75
)

print(
    "GLOBAL DIVERSITY SUMMARY"
)

print(
    "-" * 75
)


test_summary_df = pd.DataFrame(
    test_summaries
)


if not test_summary_df.empty:

    global_similarity = (
        test_summary_df[
            "average_pairwise_similarity"
        ].mean()
    )


    global_diversity = (
        1
        - global_similarity
    ) * 100


    average_unique_edges = (
        test_summary_df[
            "unique_edges_across_routes"
        ].mean()
    )


    average_route_edges = (
        test_summary_df[
            "average_route_edges"
        ].mean()
    )


    print(
        f"Average pairwise similarity : "
        f"{global_similarity:.4f}"
    )


    print(
        f"Overall diversity score     : "
        f"{global_diversity:.2f}%"
    )


    print(
        f"Average route edges         : "
        f"{average_route_edges:.2f}"
    )


    print(
        f"Average unique edges        : "
        f"{average_unique_edges:.2f}"
    )


# ============================================================
# INTERPRETATION
# ============================================================

print(
    "\n"
    + "=" * 75
)

print(
    "DIVERSITY INTERPRETATION"
)

print(
    "=" * 75
)


if not test_summary_df.empty:

    for _, row in test_summary_df.iterrows():

        score = row[
            "diversity_score_percent"
        ]


        if score >= 50:

            interpretation = (
                "HIGH diversity - "
                "candidate routes are substantially different."
            )

        elif score >= 25:

            interpretation = (
                "MODERATE diversity - "
                "candidate routes have meaningful differences."
            )

        elif score >= 10:

            interpretation = (
                "LOW diversity - "
                "candidate routes are mostly similar."
            )

        else:

            interpretation = (
                "VERY LOW diversity - "
                "candidate routes are highly overlapping."
            )


        print(
            f"Test {int(row['test_id'])}: "
            f"{interpretation}"
        )


# ============================================================
# SAVE PAIRWISE RESULTS
# ============================================================

print(
    "\n[7/8] Saving diversity results..."
)


os.makedirs(
    os.path.dirname(
        OUTPUT_FILE
    ),
    exist_ok=True
)


diversity_df = pd.DataFrame(
    diversity_records
)


diversity_df.to_csv(
    OUTPUT_FILE,
    index=False
)


test_summary_df.to_csv(
    TEST_SUMMARY_FILE,
    index=False
)


print(
    f"Saved: {OUTPUT_FILE}"
)

print(
    f"Saved: {TEST_SUMMARY_FILE}"
)


# ============================================================
# FINAL STATUS
# ============================================================

print(
    "\n[8/8] Final validation..."
)


print(
    "=" * 75
)


if len(
    all_route_records
) >= 50:

    print(
        "PASS: 50 candidate routes "
        "were reconstructed."
    )

else:

    print(
        "WARNING: Fewer than 50 "
        "candidate routes were reconstructed."
    )


if not test_summary_df.empty:

    print(
        "PASS: Route diversity analysis "
        "completed for all available tests."
    )


print(
    "\nSTEP 34 COMPLETE"
)

print(
    "=" * 75
)
