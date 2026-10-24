import os
import math
import csv

import networkx as nx
import osmnx as ox


# ============================================================
# SAFEROUTE - MULTI-ROUTE VALIDATION
# STEP 32
# ============================================================


GRAPH_FILE = (
    "data/processed/"
    "saferoute_routing_graph_v3.graphml"
)


OUTPUT_FILE = (
    "data/processed/"
    "route_validation_results.csv"
)


# ============================================================
# VALIDATION ROUTES
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


# Number of alternatives
K_ROUTES = 10


# ============================================================
# DISPLAY
# ============================================================

print("=" * 75)
print("SAFEROUTE - MULTI-ROUTE VALIDATION")
print("=" * 75)


# ============================================================
# HELPERS
# ============================================================

def parse_bool(value):

    if isinstance(value, bool):
        return value

    if value is None:
        return False

    value = str(value).strip().lower()

    return value in [
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


# ============================================================
# LOAD GRAPH
# ============================================================

print(
    "\n[1/6] Loading routing graph..."
)


if not os.path.exists(
    GRAPH_FILE
):

    raise FileNotFoundError(
        f"Graph not found: {GRAPH_FILE}"
    )


try:

    G = ox.load_graphml(
        GRAPH_FILE
    )

except Exception:

    print(
        "ox.load_graphml failed, "
        "using nx.read_graphml..."
    )

    G = nx.read_graphml(
        GRAPH_FILE
    )


    # Normalize coordinates
    for _, data in G.nodes(
        data=True
    ):

        if "x" in data:

            try:

                data["x"] = float(
                    data["x"]
                )

            except (
                TypeError,
                ValueError,
            ):

                pass


        if "y" in data:

            try:

                data["y"] = float(
                    data["y"]
                )

            except (
                TypeError,
                ValueError,
            ):

                pass


    if "crs" not in G.graph:

        G.graph["crs"] = (
            "epsg:4326"
        )

# Normalize node coordinates - ox.distance.nearest_nodes requires floats
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


print(
    f"Nodes : {len(G.nodes):,}"
)

print(
    f"Edges : {len(G.edges):,}"
)


# ============================================================
# PREPARE ROUTING GRAPH
# ============================================================

print(
    "\n[2/6] Preparing routing network..."
)


D = nx.DiGraph()


closed_edges_removed = 0


for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    # --------------------------------------------------------
    # Remove closed roads
    # --------------------------------------------------------

    road_closure = parse_bool(
        data.get(
            "road_closure",
            False
        )
    )


    if road_closure:

        closed_edges_removed += 1

        continue


    # --------------------------------------------------------
    # Travel time
    # --------------------------------------------------------

    travel_time = safe_float(
        data.get(
            "routing_travel_time",
            0
        ),
        0.0
    )


    if travel_time <= 0:

        travel_time = safe_float(
            data.get(
                "travel_time",
                0
            ),
            0.0
        )


    # --------------------------------------------------------
    # Fallback travel time
    # --------------------------------------------------------

    if travel_time <= 0:

        length = safe_float(
            data.get(
                "length",
                0
            ),
            0.0
        )


        if length > 0:

            # Approximately 50 km/h
            travel_time = (
                length / 13.89
            )


    if travel_time <= 0:

        continue


    if not math.isfinite(
        travel_time
    ):

        continue


    # --------------------------------------------------------
    # Risk
    # --------------------------------------------------------

    historical_risk = safe_float(
        data.get(
            "historical_risk",
            10
        ),
        10
    )


    traffic_risk = safe_float(
        data.get(
            "traffic_risk",
            0
        ),
        0
    )


    weather_risk = safe_float(
        data.get(
            "weather_risk",
            0
        ),
        0
    )


    dynamic_risk = safe_float(
        data.get(
            "dynamic_risk",
            5
        ),
        5
    )


    # --------------------------------------------------------
    # Source
    # --------------------------------------------------------

    risk_source = normalize_source(
        data.get(
            "risk_source",
            "baseline"
        )
    )


    risk_confidence = str(
        data.get(
            "risk_confidence",
            "LOW"
        )
    ).strip().upper()


    # --------------------------------------------------------
    # Candidate weight
    # --------------------------------------------------------

    candidate_weight = (
        travel_time
        * (
            1.0
            + 0.75
            * dynamic_risk
            / 100.0
        )
    )


    # --------------------------------------------------------
    # Keep fastest edge between node pair
    # --------------------------------------------------------

    if D.has_edge(
        u,
        v
    ):

        existing = D[u][v]


        if travel_time >= safe_float(
            existing.get(
                "routing_travel_time",
                float("inf")
            ),
            float("inf")
        ):

            continue


    D.add_edge(

        u,
        v,

        length=safe_float(
            data.get(
                "length",
                0
            )
        ),

        routing_travel_time=travel_time,

        candidate_weight=candidate_weight,

        historical_risk=historical_risk,

        traffic_risk=traffic_risk,

        weather_risk=weather_risk,

        dynamic_risk=dynamic_risk,

        risk_source=risk_source,

        risk_confidence=risk_confidence,
    )


print(
    f"Routing edges       : "
    f"{len(D.edges):,}"
)

print(
    f"Closed edges removed: "
    f"{closed_edges_removed:,}"
)


# ============================================================
# ROUTE METRICS
# ============================================================

def calculate_metrics(
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
    closed_edges = 0


    high_confidence = 0
    medium_confidence = 0
    low_confidence = 0


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


        # ----------------------------------------------------
        # Risk source
        # ----------------------------------------------------

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

            closed_edges += 1


        # ----------------------------------------------------
        # Confidence
        # ----------------------------------------------------

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


    edge_count = max(
        len(route) - 1,
        1
    )


    risk_informed = (
        observed_edges
        + propagated_edges
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
            closed_edges,

        "risk_informed_edges":
            risk_informed,

        "risk_coverage_percent":
            (
                risk_informed
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
# RUN ONE TEST
# ============================================================

def validate_route(
    test
):

    print(
        "\n"
        + "=" * 75
    )

    print(
        f"TEST {test['test_id']}"
    )

    print(
        f"{test['origin']} "
        f"→ "
        f"{test['destination']}"
    )

    print(
        "=" * 75
    )


    # --------------------------------------------------------
    # Find nearest nodes
    # --------------------------------------------------------

    origin_node = ox.distance.nearest_nodes(
        G,
        X=test["origin_lon"],
        Y=test["origin_lat"]
    )


    destination_node = ox.distance.nearest_nodes(
        G,
        X=test["dest_lon"],
        Y=test["dest_lat"]
    )


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
    # Generate candidate routes
    # --------------------------------------------------------

    routes = []


    try:

        generator = (
            nx.shortest_simple_paths(
                D,
                origin_node,
                destination_node,
                weight="candidate_weight"
            )
        )


        for route in generator:

            routes.append(
                route
            )


            if len(routes) >= K_ROUTES:

                break


    except nx.NetworkXNoPath:

        print(
            "NO PATH FOUND"
        )

        return []


    print(
        f"Candidate routes : "
        f"{len(routes)}"
    )


    # --------------------------------------------------------
    # Calculate metrics
    # --------------------------------------------------------

    results = []


    for route_id, route in enumerate(
        routes,
        start=1
    ):

        metrics = calculate_metrics(
            route
        )


        metrics["route_id"] = (
            route_id
        )


        results.append(
            metrics
        )


    # --------------------------------------------------------
    # Recommendations
    # --------------------------------------------------------

    if not results:

        return []


    fastest = min(
        results,
        key=lambda x:
        x["travel_time_min"]
    )


    safest = min(
        results,
        key=lambda x:
        (
            x["avg_dynamic_risk"],
            x["travel_time_min"]
        )
    )


    min_time = min(
        x["travel_time_min"]
        for x in results
    )


    max_time = max(
        x["travel_time_min"]
        for x in results
    )


    min_risk = min(
        x["avg_dynamic_risk"]
        for x in results
    )


    max_risk = max(
        x["avg_dynamic_risk"]
        for x in results
    )


    for result in results:

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


        result["balanced_score"] = (
            0.60 * time_score
            + 0.40 * risk_score
        )


    balanced = min(
        results,
        key=lambda x:
        x["balanced_score"]
    )


    # --------------------------------------------------------
    # Print summary
    # --------------------------------------------------------

    print(
        "\n"
        + "-" * 75
    )

    print(
        "ROUTE SUMMARY"
    )

    print(
        "-" * 75
    )


    for result in results:

        print(
            f"Route {result['route_id']:2d} | "
            f"Time: "
            f"{result['travel_time_min']:6.2f} min | "
            f"Distance: "
            f"{result['distance_km']:6.2f} km | "
            f"Risk: "
            f"{result['avg_dynamic_risk']:6.2f} | "
            f"Coverage: "
            f"{result['risk_coverage_percent']:6.2f}%"
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


    # --------------------------------------------------------
    # Save recommendation into every row
    # --------------------------------------------------------

    for result in results:

        result["fastest_route"] = (
            fastest["route_id"]
        )

        result["safest_route"] = (
            safest["route_id"]
        )

        result["balanced_route"] = (
            balanced["route_id"]
        )


    return results


# ============================================================
# 3. RUN VALIDATION
# ============================================================

print(
    "\n[3/6] Running validation tests..."
)


all_results = []


for test in TEST_ROUTES:

    results = validate_route(
        test
    )


    for result in results:

        result["test_id"] = (
            test["test_id"]
        )

        result["origin"] = (
            test["origin"]
        )

        result["destination"] = (
            test["destination"]
        )


        all_results.append(
            result
        )


# ============================================================
# SAVE RESULTS
# ============================================================

print(
    "\n[4/6] Saving validation results..."
)


os.makedirs(
    os.path.dirname(
        OUTPUT_FILE
    ),
    exist_ok=True
)


columns = [

    "test_id",

    "origin",

    "destination",

    "route_id",

    "distance_km",

    "travel_time_min",

    "avg_historical_risk",

    "avg_traffic_risk",

    "avg_weather_risk",

    "avg_dynamic_risk",

    "total_dynamic_risk",

    "observed_edges",

    "propagated_edges",

    "baseline_edges",

    "closed_edges",

    "risk_informed_edges",

    "risk_coverage_percent",

    "high_confidence_edges",

    "medium_confidence_edges",

    "low_confidence_edges",

    "edge_count",

    "node_count",

    "balanced_score",

    "fastest_route",

    "safest_route",

    "balanced_route",
]


with open(
    OUTPUT_FILE,
    "w",
    newline=""
) as file:

    writer = csv.DictWriter(
        file,
        fieldnames=columns
    )


    writer.writeheader()


    for result in all_results:

        writer.writerow({

            column:
                result.get(
                    column,
                    0
                )

            for column in columns

        })


print(
    f"Saved: "
    f"{OUTPUT_FILE}"
)


# ============================================================
# 5. GLOBAL SUMMARY
# ============================================================

print(
    "\n[5/6] Validation summary..."
)


print(
    "\n"
    + "=" * 75
)

print(
    "GLOBAL VALIDATION SUMMARY"
)

print(
    "=" * 75
)


if all_results:

    test_ids = sorted(
        set(
            result["test_id"]
            for result in all_results
        )
    )


    print(
        f"Tests completed : "
        f"{len(test_ids)}"
    )


    print(
        f"Total routes    : "
        f"{len(all_results)}"
    )


    average_coverage = (
        sum(
            result[
                "risk_coverage_percent"
            ]
            for result in all_results
        )
        / len(all_results)
    )


    average_risk = (
        sum(
            result[
                "avg_dynamic_risk"
            ]
            for result in all_results
        )
        / len(all_results)
    )


    print(
        f"Average risk coverage : "
        f"{average_coverage:.2f}%"
    )


    print(
        f"Average route risk    : "
        f"{average_risk:.2f}"
    )


    total_closed = sum(
        result[
            "closed_edges"
        ]
        for result in all_results
    )


    print(
        f"Closed edges in routes: "
        f"{total_closed}"
    )


else:

    print(
        "No validation routes "
        "were successfully generated."
    )


# ============================================================
# COMPLETE
# ============================================================

print(
    "\n[6/6] Validation complete."
)


print(
    "\n"
    + "=" * 75
)

print(
    "STEP 32 COMPLETE"
)

print(
    "=" * 75
)
