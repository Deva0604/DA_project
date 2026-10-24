import os
import math
import json
import pandas as pd
import networkx as nx
import osmnx as ox


# ============================================================
# SAFEROUTE
# STEP 35 - DIVERSITY-AWARE ROUTE GENERATION
# ============================================================

GRAPH_FILE = (
    "data/processed/"
    "saferoute_routing_graph_v3.graphml"
)

OUTPUT_FILE = (
    "data/processed/"
    "diverse_candidate_routes.csv"
)

DIVERSITY_FILE = (
    "data/processed/"
    "diverse_route_pairwise_similarity.csv"
)

TEST_SUMMARY_FILE = (
    "data/processed/"
    "diverse_route_test_summary.csv"
)


# ============================================================
# ROUTE CONFIGURATION
# ============================================================

# Number of raw candidate paths generated internally.
RAW_CANDIDATES = 50

# Maximum number of final routes shown/selected.
FINAL_ROUTES = 10

# Maximum Jaccard similarity allowed between selected routes.
#
# 0.70 means:
#     if a new route shares more than 70% of its edge structure
#     with ANY already-selected route, reject it.
#
MAX_SIMILARITY = 0.70


# Same weight used by previous route-generation stage.
RISK_WEIGHT = 0.75


# ============================================================
# TEST ROUTES
# ============================================================

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


# ============================================================
# PRINT HEADER
# ============================================================

print("=" * 75)
print("SAFEROUTE - DIVERSITY-AWARE ROUTE GENERATION")
print("=" * 75)


# ============================================================
# HELPER FUNCTIONS
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


def safe_float(
    value,
    default=0.0
):

    try:

        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (
        TypeError,
        ValueError,
    ):

        return default


def normalize_source(value):

    source = str(
        value
    ).strip().lower()


    if source in [
        "observed",
        "actual",
        "direct",
    ]:

        return "observed"


    if source in [
        "spatial_propagated",
        "propagated",
        "spatial-propagated",
    ]:

        return "spatial_propagated"


    if source in [
        "baseline",
        "baseline_no_observation",
        "unknown",
        "none",
        "",
    ]:

        return "baseline"


    if source == "closed":

        return "closed"


    return source


def fix_graph_node_coords(G):
    for _, data in G.nodes(data=True):
        if "x" in data:
            try:
                data["x"] = float(data["x"])
            except (TypeError, ValueError):
                pass
        if "y" in data:
            try:
                data["y"] = float(data["y"])
            except (TypeError, ValueError):
                pass
    try:
        if "crs" in G.graph and G.graph["crs"] is not None:
            G.graph["crs"] = str(G.graph["crs"])
        else:
            G.graph["crs"] = "EPSG:4326"
    except Exception:
        pass


def find_nearest_node(G, lon, lat):
    try:
        return ox.distance.nearest_nodes(
            G,
            X=float(lon),
            Y=float(lat)
        )
    except Exception:
        pass
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


def edge_identifier(
    u,
    v
):

    return (
        str(u),
        str(v)
    )


def route_edges(
    route
):

    return {

        edge_identifier(
            u,
            v
        )

        for u, v in zip(
            route[:-1],
            route[1:]
        )

    }


def jaccard_similarity(
    edges_a,
    edges_b
):

    union = (
        edges_a
        | edges_b
    )


    if not union:

        return 1.0


    intersection = (
        edges_a
        & edges_b
    )


    return (
        len(intersection)
        / len(union)
    )


# ============================================================
# 1. CHECK GRAPH
# ============================================================

print(
    "\n[1/8] Checking graph..."
)


if not os.path.exists(
    GRAPH_FILE
):

    raise FileNotFoundError(
        f"Graph not found: {GRAPH_FILE}"
    )


print(
    f"Graph: {GRAPH_FILE}"
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


fix_graph_node_coords(G)


print(
    f"Nodes : {len(G.nodes):,}"
)

print(
    f"Edges : {len(G.edges):,}"
)


# ============================================================
# 3. BUILD ROUTING GRAPH
# ============================================================

print(
    "\n[3/8] Preparing routing graph..."
)


D = nx.DiGraph()


closed_edges = 0

usable_edges = 0


for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    # --------------------------------------------------------
    # Remove closed roads
    # --------------------------------------------------------

    if parse_bool(
        data.get(
            "road_closure",
            False
        )
    ):

        closed_edges += 1

        continue


    # --------------------------------------------------------
    # Travel time
    # --------------------------------------------------------

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


    # --------------------------------------------------------
    # Fallback travel time from road length
    # --------------------------------------------------------

    if travel_time <= 0:

        length = safe_float(
            data.get(
                "length",
                0
            )
        )


        if length > 0:

            # Approximately 50 km/h.
            travel_time = (
                length / 13.89
            )


    if travel_time <= 0:

        continue


    # --------------------------------------------------------
    # Dynamic risk
    # --------------------------------------------------------

    dynamic_risk = safe_float(
        data.get(
            "dynamic_risk",
            5
        ),
        5
    )


    # --------------------------------------------------------
    # Candidate path weight
    # --------------------------------------------------------

    candidate_weight = (

        travel_time

        *

        (
            1
            +
            RISK_WEIGHT
            * dynamic_risk
            / 100.0
        )

    )


    # --------------------------------------------------------
    # Multiple OSM edges can connect the same nodes.
    #
    # Keep the fastest usable edge.
    # --------------------------------------------------------

    if D.has_edge(
        u,
        v
    ):

        existing_time = safe_float(
            D[u][v].get(
                "routing_travel_time",
                float("inf")
            ),
            float("inf")
        )


        if travel_time >= existing_time:

            continue


    # --------------------------------------------------------
    # Store edge attributes
    # --------------------------------------------------------

    D.add_edge(

        u,
        v,

        length=safe_float(
            data.get(
                "length",
                0
            )
        ),

        routing_travel_time=
            travel_time,

        candidate_weight=
            candidate_weight,

        historical_risk=
            safe_float(
                data.get(
                    "historical_risk",
                    10
                ),
                10
            ),

        traffic_risk=
            safe_float(
                data.get(
                    "traffic_risk",
                    0
                ),
                0
            ),

        weather_risk=
            safe_float(
                data.get(
                    "weather_risk",
                    0
                ),
                0
            ),

        dynamic_risk=
            dynamic_risk,

        risk_source=
            normalize_source(
                data.get(
                    "risk_source",
                    "baseline"
                )
            ),

        risk_confidence=
            str(
                data.get(
                    "risk_confidence",
                    "LOW"
                )
            ).strip().upper(),

    )


    usable_edges += 1


print(
    f"Usable routing edges : "
    f"{len(D.edges):,}"
)

print(
    f"Closed edges removed : "
    f"{closed_edges:,}"
)


# ============================================================
# ROUTE METRICS
# ============================================================

def calculate_route_metrics(
    route
):

    distance = 0.0

    travel_time = 0.0

    historical_sum = 0.0

    traffic_sum = 0.0

    weather_sum = 0.0

    dynamic_sum = 0.0


    observed_edges = 0

    propagated_edges = 0

    baseline_edges = 0

    closed_edges_in_route = 0


    high_confidence = 0

    medium_confidence = 0

    low_confidence = 0


    edge_count = max(
        len(route) - 1,
        1
    )


    for u, v in zip(
        route[:-1],
        route[1:]
    ):

        data = D.get_edge_data(
            u,
            v
        )


        if data is None:

            continue


        distance += safe_float(
            data.get(
                "length",
                0
            )
        )


        travel_time += safe_float(
            data.get(
                "routing_travel_time",
                0
            )
        )


        historical_sum += safe_float(
            data.get(
                "historical_risk",
                10
            )
        )


        traffic_sum += safe_float(
            data.get(
                "traffic_risk",
                0
            )
        )


        weather_sum += safe_float(
            data.get(
                "weather_risk",
                0
            )
        )


        dynamic_sum += safe_float(
            data.get(
                "dynamic_risk",
                5
            )
        )


        source = normalize_source(
            data.get(
                "risk_source",
                "baseline"
            )
        )


        if source == "observed":

            observed_edges += 1

        elif source == "spatial_propagated":

            propagated_edges += 1

        elif source == "baseline":

            baseline_edges += 1

        elif source == "closed":

            closed_edges_in_route += 1


        confidence = str(
            data.get(
                "risk_confidence",
                "LOW"
            )
        ).strip().upper()


        if confidence == "HIGH":

            high_confidence += 1

        elif confidence == "MEDIUM":

            medium_confidence += 1

        else:

            low_confidence += 1


    risk_informed_edges = (

        observed_edges
        +
        propagated_edges

    )


    return {

        "distance_km":
            distance / 1000.0,

        "travel_time_min":
            travel_time / 60.0,

        "avg_historical_risk":
            historical_sum / edge_count,

        "avg_traffic_risk":
            traffic_sum / edge_count,

        "avg_weather_risk":
            weather_sum / edge_count,

        "avg_dynamic_risk":
            dynamic_sum / edge_count,

        "total_dynamic_risk":
            dynamic_sum,

        "observed_edges":
            observed_edges,

        "propagated_edges":
            propagated_edges,

        "baseline_edges":
            baseline_edges,

        "closed_edges":
            closed_edges_in_route,

        "risk_informed_edges":
            risk_informed_edges,

        "risk_coverage_percent":
            (
                risk_informed_edges
                / edge_count
                * 100.0
            ),

        "high_confidence_edges":
            high_confidence,

        "medium_confidence_edges":
            medium_confidence,

        "low_confidence_edges":
            low_confidence,

        "edge_count":
            edge_count,

        "node_count":
            len(route),

    }


# ============================================================
# 4. GENERATE DIVERSE ROUTES
# ============================================================

print(
    "\n[4/8] Generating diverse routes..."
)


all_route_results = []

all_pairwise_results = []

test_summary_results = []


for test in TEST_ROUTES:

    print(
        "\n"
        + "-" * 75
    )

    print(
        f"TEST {test['test_id']}: "
        f"{test['origin']} → "
        f"{test['destination']}"
    )

    print(
        "-" * 75
    )


    # --------------------------------------------------------
    # Find nearest graph nodes
    # --------------------------------------------------------

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


    # GraphML may return IDs in string form.

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


    print(
        f"Origin node      : "
        f"{origin_node}"
    )

    print(
        f"Destination node : "
        f"{destination_node}"
    )


    # --------------------------------------------------------
    # Generate RAW candidates
    # --------------------------------------------------------

    raw_routes = []


    try:

        generator = nx.shortest_simple_paths(

            D,

            origin_node,

            destination_node,

            weight="candidate_weight"

        )


        for route in generator:

            raw_routes.append(
                route
            )


            if len(raw_routes) >= RAW_CANDIDATES:

                break


    except nx.NetworkXNoPath:

        print(
            "NO PATH FOUND"
        )

        continue


    print(
        f"Raw candidate routes: "
        f"{len(raw_routes)}"
    )


    # --------------------------------------------------------
    # Prepare edge sets
    # --------------------------------------------------------

    raw_route_data = []


    for route in raw_routes:

        edges = route_edges(
            route
        )


        metrics = calculate_route_metrics(
            route
        )


        raw_route_data.append({

            "route":
                route,

            "edges":
                edges,

            "metrics":
                metrics,

        })


    # --------------------------------------------------------
    # Select diverse routes
    #
    # IMPORTANT:
    #
    # The first route is always accepted because it is the
    # best candidate according to the candidate weight.
    #
    # Subsequent routes must not be too similar to ANY route
    # already selected.
    # --------------------------------------------------------

    selected_routes = []


    rejected_similar = 0


    for candidate in raw_route_data:

        if len(
            selected_routes
        ) >= FINAL_ROUTES:

            break


        if not selected_routes:

            selected_routes.append(
                candidate
            )

            continue


        max_similarity_with_selected = 0.0


        for selected in selected_routes:

            similarity = jaccard_similarity(

                candidate["edges"],

                selected["edges"]

            )


            max_similarity_with_selected = max(

                max_similarity_with_selected,

                similarity

            )


        if (
            max_similarity_with_selected
            <=
            MAX_SIMILARITY
        ):

            selected_routes.append(
                candidate
            )

        else:

            rejected_similar += 1


    print(
        f"Selected diverse routes: "
        f"{len(selected_routes)}"
    )


    print(
        f"Rejected similar routes: "
        f"{rejected_similar}"
    )


    # --------------------------------------------------------
    # If diversity threshold is too strict and fewer than
    # 10 routes are found, continue with best remaining routes
    # so the system never unnecessarily loses all candidates.
    # --------------------------------------------------------

    if len(
        selected_routes
    ) < FINAL_ROUTES:

        selected_edge_sets = [

            item["edges"]

            for item in selected_routes

        ]


        for candidate in raw_route_data:

            if len(
                selected_routes
            ) >= FINAL_ROUTES:

                break


            if candidate in selected_routes:

                continue


            # Check whether this candidate was already
            # rejected because of similarity.

            is_duplicate = False


            for selected_edges in selected_edge_sets:

                similarity = jaccard_similarity(

                    candidate["edges"],

                    selected_edges

                )


                if similarity <= MAX_SIMILARITY:

                    selected_routes.append(
                        candidate
                    )

                    selected_edge_sets.append(
                        candidate["edges"]
                    )

                    is_duplicate = True

                    break


            if not is_duplicate:

                continue


    # --------------------------------------------------------
    # Calculate pairwise similarity of FINAL routes
    # --------------------------------------------------------

    pairwise_values = []


    for i in range(
        len(selected_routes)
    ):

        for j in range(
            i + 1,
            len(selected_routes)
        ):

            route_a = selected_routes[i]

            route_b = selected_routes[j]


            similarity = jaccard_similarity(

                route_a["edges"],

                route_b["edges"]

            )


            shared_edges = len(

                route_a["edges"]
                &
                route_b["edges"]

            )


            union_edges = len(

                route_a["edges"]
                |
                route_b["edges"]

            )


            pairwise_values.append(
                similarity
            )


            all_pairwise_results.append({

                "test_id":
                    test["test_id"],

                "origin":
                    test["origin"],

                "destination":
                    test["destination"],

                "route_a":
                    i + 1,

                "route_b":
                    j + 1,

                "route_a_edges":
                    len(
                        route_a["edges"]
                    ),

                "route_b_edges":
                    len(
                        route_b["edges"]
                    ),

                "shared_edges":
                    shared_edges,

                "union_edges":
                    union_edges,

                "jaccard_similarity":
                    similarity,

                "jaccard_difference":
                    1 - similarity,

            })


    # --------------------------------------------------------
    # Route metrics
    # --------------------------------------------------------

    route_metric_list = []


    for route_number, item in enumerate(

        selected_routes,

        start=1

    ):

        metrics = dict(
            item["metrics"]
        )


        metrics["test_id"] = (
            test["test_id"]
        )


        metrics["origin"] = (
            test["origin"]
        )


        metrics["destination"] = (
            test["destination"]
        )


        metrics["route_id"] = (
            route_number
        )


        metrics["raw_candidate_rank"] = (

            raw_route_data.index(
                item
            )
            + 1

        )


        metrics["route_nodes"] = json.dumps(

            [
                str(node)

                for node
                in item["route"]

            ]

        )


        route_metric_list.append(
            metrics
        )


    # --------------------------------------------------------
    # Recommendation calculation
    # --------------------------------------------------------

    if route_metric_list:

        fastest = min(

            route_metric_list,

            key=lambda x:
            x["travel_time_min"]

        )


        safest = min(

            route_metric_list,

            key=lambda x:
            (
                x["avg_dynamic_risk"],
                x["travel_time_min"]
            )

        )


        min_time = min(

            x["travel_time_min"]

            for x
            in route_metric_list

        )


        max_time = max(

            x["travel_time_min"]

            for x
            in route_metric_list

        )


        min_risk = min(

            x["avg_dynamic_risk"]

            for x
            in route_metric_list

        )


        max_risk = max(

            x["avg_dynamic_risk"]

            for x
            in route_metric_list

        )


        for result in route_metric_list:

            # ------------------------------------------------
            # Normalized time
            # ------------------------------------------------

            if max_time > min_time:

                time_score = (

                    result["travel_time_min"]
                    - min_time

                ) / (

                    max_time
                    - min_time

                )

            else:

                time_score = 0.0


            # ------------------------------------------------
            # Normalized risk
            # ------------------------------------------------

            if max_risk > min_risk:

                risk_score = (

                    result["avg_dynamic_risk"]
                    - min_risk

                ) / (

                    max_risk
                    - min_risk

                )

            else:

                risk_score = 0.0


            # ------------------------------------------------
            # Balanced score
            #
            # 60% travel time
            # 40% risk
            # ------------------------------------------------

            result["balanced_score"] = (

                0.60 * time_score

                +

                0.40 * risk_score

            )


        balanced = min(

            route_metric_list,

            key=lambda x:
            x["balanced_score"]

        )


        # ----------------------------------------------------
        # Add recommendations to every route
        # ----------------------------------------------------

        for result in route_metric_list:

            result["fastest_route"] = (

                fastest["route_id"]

            )


            result["safest_route"] = (

                safest["route_id"]

            )


            result["balanced_route"] = (

                balanced["route_id"]

            )


        # ----------------------------------------------------
        # Diversity summary
        # ----------------------------------------------------

        if pairwise_values:

            average_similarity = (

                sum(pairwise_values)
                /
                len(pairwise_values)

            )


            minimum_similarity = min(
                pairwise_values
            )


            maximum_similarity = max(
                pairwise_values
            )

        else:

            average_similarity = 1.0

            minimum_similarity = 1.0

            maximum_similarity = 1.0


        diversity_score = (

            1
            - average_similarity

        ) * 100


        unique_edges = set()


        for item in selected_routes:

            unique_edges.update(
                item["edges"]
            )


        # ----------------------------------------------------
        # Test summary
        # ----------------------------------------------------

        test_summary_results.append({

            "test_id":
                test["test_id"],

            "origin":
                test["origin"],

            "destination":
                test["destination"],

            "raw_candidates":
                len(raw_routes),

            "selected_routes":
                len(selected_routes),

            "rejected_similar_routes":
                rejected_similar,

            "average_pairwise_similarity":
                average_similarity,

            "minimum_pairwise_similarity":
                minimum_similarity,

            "maximum_pairwise_similarity":
                maximum_similarity,

            "diversity_score_percent":
                diversity_score,

            "unique_edges_across_routes":
                len(unique_edges),

            "average_route_edges":
                sum(
                    len(
                        item["edges"]
                    )
                    for item
                    in selected_routes
                )
                /
                len(selected_routes),

            "fastest_route":
                fastest["route_id"],

            "safest_route":
                safest["route_id"],

            "balanced_route":
                balanced["route_id"],

            "fastest_time_min":
                fastest[
                    "travel_time_min"
                ],

            "safest_time_min":
                safest[
                    "travel_time_min"
                ],

            "balanced_time_min":
                balanced[
                    "travel_time_min"
                ],

            "fastest_risk":
                fastest[
                    "avg_dynamic_risk"
                ],

            "safest_risk":
                safest[
                    "avg_dynamic_risk"
                ],

            "balanced_risk":
                balanced[
                    "avg_dynamic_risk"
                ],

            "average_risk_coverage":
                sum(
                    result[
                        "risk_coverage_percent"
                    ]
                    for result
                    in route_metric_list
                )
                /
                len(route_metric_list),

        })


        all_route_results.extend(
            route_metric_list
        )


        # ----------------------------------------------------
        # Print final route summary
        # ----------------------------------------------------

        print(
            "\nFINAL DIVERSE ROUTES"
        )

        print(
            "-" * 75
        )


        for result in route_metric_list:

            print(

                f"Route "
                f"{result['route_id']:2d} | "

                f"Time "
                f"{result['travel_time_min']:6.2f} min | "

                f"Distance "
                f"{result['distance_km']:6.2f} km | "

                f"Risk "
                f"{result['avg_dynamic_risk']:6.2f} | "

                f"Similarity limit "
                f"{MAX_SIMILARITY:.2f}"

            )


        print(
            "\nRECOMMENDATIONS"
        )


        print(

            f"FASTEST  → Route "
            f"{fastest['route_id']} "
            f"("
            f"{fastest['travel_time_min']:.2f} min, "
            f"risk "
            f"{fastest['avg_dynamic_risk']:.2f}"
            f")"

        )


        print(

            f"SAFEST   → Route "
            f"{safest['route_id']} "
            f"("
            f"{safest['travel_time_min']:.2f} min, "
            f"risk "
            f"{safest['avg_dynamic_risk']:.2f}"
            f")"

        )


        print(

            f"BALANCED → Route "
            f"{balanced['route_id']} "
            f"("
            f"{balanced['travel_time_min']:.2f} min, "
            f"risk "
            f"{balanced['avg_dynamic_risk']:.2f}"
            f")"

        )


        print(

            f"Average route similarity: "
            f"{average_similarity:.4f}"

        )


        print(

            f"Diversity score: "
            f"{diversity_score:.2f}%"

        )


        print(

            f"Unique edges across routes: "
            f"{len(unique_edges)}"

        )


# ============================================================
# 5. SAVE ROUTE RESULTS
# ============================================================

print(
    "\n[5/8] Saving diverse route results..."
)


os.makedirs(
    os.path.dirname(
        OUTPUT_FILE
    ),
    exist_ok=True
)


route_results_df = pd.DataFrame(
    all_route_results
)


pairwise_df = pd.DataFrame(
    all_pairwise_results
)


test_summary_df = pd.DataFrame(
    test_summary_results
)


route_results_df.to_csv(
    OUTPUT_FILE,
    index=False
)


pairwise_df.to_csv(
    DIVERSITY_FILE,
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
    f"Saved: {DIVERSITY_FILE}"
)

print(
    f"Saved: {TEST_SUMMARY_FILE}"
)


# ============================================================
# 6. GLOBAL SUMMARY
# ============================================================

print(
    "\n[6/8] Calculating global summary..."
)


print(
    "\n"
    + "=" * 75
)

print(
    "GLOBAL DIVERSITY-AWARE ROUTING SUMMARY"
)

print(
    "=" * 75
)


if not test_summary_df.empty:

    total_selected = (
        test_summary_df[
            "selected_routes"
        ].sum()
    )


    total_raw = (
        test_summary_df[
            "raw_candidates"
        ].sum()
    )


    average_similarity = (
        test_summary_df[
            "average_pairwise_similarity"
        ].mean()
    )


    overall_diversity = (
        1
        - average_similarity
    ) * 100


    average_coverage = (
        test_summary_df[
            "average_risk_coverage"
        ].mean()
    )


    print(
        f"Tests completed            : "
        f"{len(test_summary_df)}"
    )


    print(
        f"Raw candidates generated   : "
        f"{total_raw}"
    )


    print(
        f"Final routes selected      : "
        f"{total_selected}"
    )


    print(
        f"Average pairwise similarity: "
        f"{average_similarity:.4f}"
    )


    print(
        f"Overall diversity score    : "
        f"{overall_diversity:.2f}%"
    )


    print(
        f"Average risk coverage      : "
        f"{average_coverage:.2f}%"
    )


# ============================================================
# 7. QUALITY CHECK
# ============================================================

print(
    "\n[7/8] Running quality checks..."
)


if not test_summary_df.empty:

    all_tests_have_routes = (

        (
            test_summary_df[
                "selected_routes"
            ]
            > 0
        ).all()

    )


    all_tests_have_multiple = (

        (
            test_summary_df[
                "selected_routes"
            ]
            >= 3
        ).all()

    )


    if all_tests_have_routes:

        print(
            "PASS: Every test has at least "
            "one route."
        )

    else:

        print(
            "FAIL: At least one test has "
            "no route."
        )


    if all_tests_have_multiple:

        print(
            "PASS: Every test has at least "
            "three diverse alternatives."
        )

    else:

        print(
            "WARNING: Some tests have fewer "
            "than three diverse alternatives."
        )


    if overall_diversity >= 25:

        print(
            f"PASS: Overall route diversity "
            f"is {overall_diversity:.2f}%."
        )

    elif overall_diversity >= 15:

        print(
            f"MODERATE: Overall route diversity "
            f"is {overall_diversity:.2f}%."
        )

    else:

        print(
            f"LOW: Overall route diversity "
            f"is {overall_diversity:.2f}%."
        )


# ============================================================
# 8. COMPLETE
# ============================================================

print(
    "\n[8/8] Step 35 complete."
)


print(
    "=" * 75
)

print(
    "DIVERSITY-AWARE ROUTE GENERATION COMPLETE"
)

print(
    "=" * 75
)
