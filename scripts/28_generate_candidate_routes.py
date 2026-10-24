import os
import math
import csv

import networkx as nx
import osmnx as ox


# ============================================================
# SAFEROUTE - CANDIDATE ROUTE GENERATOR
# STEP 31 - FIXED RISK SOURCE REPORTING
# ============================================================


GRAPH_FILE = (
    "data/processed/"
    "saferoute_routing_graph_v3.graphml"
)


# ============================================================
# TEST LOCATION
# ============================================================

# Chennai Central
ORIGIN_LAT = 13.0827
ORIGIN_LON = 80.2707

# Anna Nagar
DEST_LAT = 13.0850
DEST_LON = 80.2101


# Number of alternative routes
K_ROUTES = 10


# Output file
ROUTE_RESULTS_FILE = (
    "data/processed/"
    "candidate_routes.csv"
)


# ============================================================
# DISPLAY
# ============================================================

print("=" * 70)
print("SAFEROUTE - CANDIDATE ROUTE GENERATOR")
print("=" * 70)


# ============================================================
# BOOLEAN HELPER
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


# ============================================================
# FLOAT HELPER
# ============================================================

def safe_float(value, default=0.0):

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


# ============================================================
# RISK SOURCE NORMALIZATION
# ============================================================

def normalize_risk_source(value):

    source = str(
        value
    ).strip().lower()

    # Observed directly from accident / live data
    if source in [
        "observed",
        "actual",
        "direct",
    ]:

        return "observed"


    # Spatially propagated from nearby observed roads
    if source in [
        "spatial_propagated",
        "propagated",
        "spatial-propagated",
    ]:

        return "spatial_propagated"


    # No nearby observation
    if source in [
        "baseline_no_observation",
        "baseline",
        "unknown",
        "none",
        "",
    ]:

        return "baseline"


    # Closed roads
    if source in [
        "closed",
    ]:

        return "closed"


    # Safety fallback
    return source


# ============================================================
# RISK CATEGORY
# ============================================================

def normalize_risk_category(value):

    category = str(
        value
    ).strip().upper()

    if category in [
        "LOW",
        "MEDIUM",
        "HIGH",
        "CLOSED",
    ]:

        return category

    return "UNKNOWN"


# ============================================================
# 1. LOAD GRAPH
# ============================================================

print(
    "\n[1/8] Loading improved routing graph..."
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
        "falling back to nx.read_graphml..."
    )

    G = nx.read_graphml(
        GRAPH_FILE
    )

    # Normalize node coordinates
    for _, node_data in G.nodes(
        data=True
    ):

        if "x" in node_data:

            try:

                node_data["x"] = float(
                    node_data["x"]
                )

            except (
                TypeError,
                ValueError,
            ):

                pass


        if "y" in node_data:

            try:

                node_data["y"] = float(
                    node_data["y"]
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


print(
    f"Nodes : {len(G.nodes):,}"
)

print(
    f"Edges : {len(G.edges):,}"
)


# ============================================================
# 2. FIND ORIGIN / DESTINATION
# ============================================================

print(
    "\n[2/8] Finding nearest road nodes..."
)


origin_node = ox.distance.nearest_nodes(
    G,
    X=ORIGIN_LON,
    Y=ORIGIN_LAT
)


destination_node = ox.distance.nearest_nodes(
    G,
    X=DEST_LON,
    Y=DEST_LAT
)


# Normalize node ID types
if (
    origin_node not in G
    and str(origin_node) in G
):

    origin_node = str(
        origin_node
    )


if (
    destination_node not in G
    and str(destination_node) in G
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


# ============================================================
# 3. PREPARE DIRECTED ROUTING GRAPH
# ============================================================

print(
    "\n[3/8] Preparing routing network..."
)


D = nx.DiGraph()


closed_edges_removed = 0
normal_edges_added = 0


for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    # --------------------------------------------------------
    # CLOSED ROAD
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
    # TRAVEL TIME
    # --------------------------------------------------------

    travel_time = safe_float(
        data.get(
            "routing_travel_time",
            0
        ),
        0.0
    )


    # Some graphs may have travel_time
    # instead of routing_travel_time.

    if travel_time <= 0:

        travel_time = safe_float(
            data.get(
                "travel_time",
                0
            ),
            0.0
        )


    # --------------------------------------------------------
    # FALLBACK TRAVEL TIME
    # --------------------------------------------------------

    if travel_time <= 0:

        length = safe_float(
            data.get(
                "length",
                0
            ),
            0.0
        )


        # Approximately 50 km/h fallback.
        if length > 0:

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
    # RISK VALUES
    # --------------------------------------------------------

    historical_risk = safe_float(
        data.get(
            "historical_risk",
            10.0
        ),
        10.0
    )


    traffic_risk = safe_float(
        data.get(
            "traffic_risk",
            0.0
        ),
        0.0
    )


    weather_risk = safe_float(
        data.get(
            "weather_risk",
            0.0
        ),
        0.0
    )


    dynamic_risk = safe_float(
        data.get(
            "dynamic_risk",
            5.0
        ),
        5.0
    )


    # --------------------------------------------------------
    # RISK SOURCE
    # --------------------------------------------------------

    risk_source = normalize_risk_source(
        data.get(
            "risk_source",
            "baseline_no_observation"
        )
    )


    # --------------------------------------------------------
    # RISK CONFIDENCE
    # --------------------------------------------------------

    risk_confidence = str(
        data.get(
            "risk_confidence",
            "LOW"
        )
    ).strip().upper()


    # --------------------------------------------------------
    # RISK CATEGORY
    # --------------------------------------------------------

    risk_category = normalize_risk_category(
        data.get(
            "risk_category",
            ""
        )
    )


    # --------------------------------------------------------
    # MULTIPLE EDGES BETWEEN SAME NODES
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


    # --------------------------------------------------------
    # ADD ROUTING EDGE
    # --------------------------------------------------------

    D.add_edge(

        u,
        v,

        original_key=str(
            key
        ),

        length=safe_float(
            data.get(
                "length",
                0
            )
        ),

        routing_travel_time=travel_time,

        historical_risk=historical_risk,

        traffic_risk=traffic_risk,

        weather_risk=weather_risk,

        dynamic_risk=dynamic_risk,

        road_closure=False,

        risk_source=risk_source,

        risk_confidence=risk_confidence,

        risk_category=risk_category,
    )


    normal_edges_added += 1


print(
    f"Routing edges       : "
    f"{len(D.edges):,}"
)

print(
    f"Closed edges removed: "
    f"{closed_edges_removed:,}"
)


# ============================================================
# 4. CREATE CANDIDATE WEIGHT
# ============================================================

print(
    "\n[4/8] Creating candidate-route weight..."
)


for u, v, data in D.edges(
    data=True
):

    travel_time = safe_float(
        data[
            "routing_travel_time"
        ],
        1.0
    )


    dynamic_risk = safe_float(
        data[
            "dynamic_risk"
        ],
        5.0
    )


    # --------------------------------------------------------
    # ROUTE WEIGHT
    #
    # Time is primary.
    # Risk adds a penalty.
    #
    # weight =
    # travel_time ×
    # (1 + 0.75 × risk / 100)
    # --------------------------------------------------------

    data[
        "candidate_weight"
    ] = (
        travel_time
        * (
            1.0
            + 0.75
            * dynamic_risk
            / 100.0
        )
    )


# ============================================================
# 5. GENERATE CANDIDATE ROUTES
# ============================================================

print(
    f"\n[5/8] Generating up to "
    f"{K_ROUTES} candidate routes..."
)


candidate_routes = []


try:

    generator = nx.shortest_simple_paths(

        D,

        origin_node,

        destination_node,

        weight="candidate_weight"
    )


    for route in generator:

        candidate_routes.append(
            route
        )


        if (
            len(candidate_routes)
            >= K_ROUTES
        ):

            break


except nx.NetworkXNoPath:

    candidate_routes = []


print(
    f"Routes generated: "
    f"{len(candidate_routes)}"
)


# ============================================================
# 6. CALCULATE ROUTE METRICS
# ============================================================

print(
    "\n[6/8] Calculating candidate metrics..."
)


def calculate_metrics(
    route
):

    distance = 0.0
    travel_time = 0.0

    historical_sum = 0.0
    traffic_sum = 0.0
    weather_sum = 0.0
    dynamic_sum = 0.0


    # --------------------------------------------------------
    # SOURCE COUNTERS
    # --------------------------------------------------------

    observed_edges = 0
    propagated_edges = 0
    baseline_edges = 0
    closed_edges = 0


    # --------------------------------------------------------
    # CONFIDENCE COUNTERS
    # --------------------------------------------------------

    high_confidence_edges = 0
    medium_confidence_edges = 0
    low_confidence_edges = 0


    # --------------------------------------------------------
    # ROUTE EDGES
    # --------------------------------------------------------

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


        # ----------------------------------------------------
        # DISTANCE
        # ----------------------------------------------------

        distance += safe_float(
            data.get(
                "length",
                0
            )
        )


        # ----------------------------------------------------
        # TRAVEL TIME
        # ----------------------------------------------------

        travel_time += safe_float(
            data.get(
                "routing_travel_time",
                0
            )
        )


        # ----------------------------------------------------
        # RISK VALUES
        # ----------------------------------------------------

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
        # RISK SOURCE
        # ----------------------------------------------------

        source = normalize_risk_source(
            data.get(
                "risk_source",
                "baseline_no_observation"
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
        # CONFIDENCE
        # ----------------------------------------------------

        confidence = str(
            data.get(
                "risk_confidence",
                "LOW"
            )
        ).strip().upper()


        if confidence == "HIGH":

            high_confidence_edges += 1


        elif confidence == "MEDIUM":

            medium_confidence_edges += 1


        else:

            low_confidence_edges += 1


    # --------------------------------------------------------
    # EDGE COUNT
    # --------------------------------------------------------

    edge_count = max(
        len(route) - 1,
        1
    )


    # --------------------------------------------------------
    # RISK COVERAGE
    #
    # Observed + propagated = roads
    # with meaningful risk information.
    # --------------------------------------------------------

    risk_informed_edges = (
        observed_edges
        + propagated_edges
    )


    risk_coverage = (
        risk_informed_edges
        / edge_count
        * 100.0
    )


    # --------------------------------------------------------
    # SOURCE PERCENTAGES
    # --------------------------------------------------------

    observed_percent = (
        observed_edges
        / edge_count
        * 100.0
    )


    propagated_percent = (
        propagated_edges
        / edge_count
        * 100.0
    )


    baseline_percent = (
        baseline_edges
        / edge_count
        * 100.0
    )


    # --------------------------------------------------------
    # AVERAGES
    # --------------------------------------------------------

    avg_historical = (
        historical_sum
        / edge_count
    )


    avg_traffic = (
        traffic_sum
        / edge_count
    )


    avg_weather = (
        weather_sum
        / edge_count
    )


    avg_dynamic = (
        dynamic_sum
        / edge_count
    )


    # --------------------------------------------------------
    # RETURN
    # --------------------------------------------------------

    return {

        "distance_km":
            distance / 1000.0,

        "travel_time_min":
            travel_time / 60.0,

        "avg_historical_risk":
            avg_historical,

        "avg_traffic_risk":
            avg_traffic,

        "avg_weather_risk":
            avg_weather,

        "avg_dynamic_risk":
            avg_dynamic,

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
            risk_informed_edges,

        "risk_coverage_percent":
            risk_coverage,

        "observed_percent":
            observed_percent,

        "propagated_percent":
            propagated_percent,

        "baseline_percent":
            baseline_percent,

        "high_confidence_edges":
            high_confidence_edges,

        "medium_confidence_edges":
            medium_confidence_edges,

        "low_confidence_edges":
            low_confidence_edges,

        "nodes":
            len(route),

        "edges":
            edge_count,
    }


# ============================================================
# CALCULATE ALL ROUTES
# ============================================================

route_results = []


for route_id, route in enumerate(
    candidate_routes,
    start=1
):

    metrics = calculate_metrics(
        route
    )


    metrics[
        "route_id"
    ] = route_id


    metrics[
        "route_nodes"
    ] = route


    route_results.append(
        metrics
    )


# ============================================================
# 7. DISPLAY ROUTES
# ============================================================

print(
    "\n[7/8] Route comparison..."
)


print(
    "\n"
    + "=" * 70
)

print(
    "CANDIDATE ROUTES"
)

print(
    "=" * 70
)


if not route_results:

    print(
        "\nNO ROUTE FOUND."
    )


else:

    for result in route_results:

        print(
            f"\nROUTE "
            f"{result['route_id']}"
        )


        print(
            "-" * 50
        )


        print(
            f"Distance              : "
            f"{result['distance_km']:.2f} km"
        )


        print(
            f"Travel time           : "
            f"{result['travel_time_min']:.2f} min"
        )


        print(
            f"Avg historical risk   : "
            f"{result['avg_historical_risk']:.2f}"
        )


        print(
            f"Avg traffic risk      : "
            f"{result['avg_traffic_risk']:.2f}"
        )


        print(
            f"Avg weather risk      : "
            f"{result['avg_weather_risk']:.2f}"
        )


        print(
            f"Avg dynamic risk      : "
            f"{result['avg_dynamic_risk']:.2f}"
        )


        print(
            f"Total dynamic risk    : "
            f"{result['total_dynamic_risk']:.2f}"
        )


        print(
            f"Observed risk edges   : "
            f"{result['observed_edges']}"
        )


        print(
            f"Propagated risk edges : "
            f"{result['propagated_edges']}"
        )


        print(
            f"Baseline edges        : "
            f"{result['baseline_edges']}"
        )


        print(
            f"Closed edges          : "
            f"{result['closed_edges']}"
        )


        print(
            f"Risk coverage         : "
            f"{result['risk_coverage_percent']:.2f}%"
        )


        print(
            f"Risk confidence       : "
            f"HIGH={result['high_confidence_edges']} "
            f"MEDIUM={result['medium_confidence_edges']} "
            f"LOW={result['low_confidence_edges']}"
        )


# ============================================================
# 8. SELECT RECOMMENDATIONS
# ============================================================

print(
    "\n[8/8] Selecting route recommendations..."
)


if route_results:

    # ========================================================
    # FASTEST
    # ========================================================

    fastest = min(
        route_results,
        key=lambda x:
        x[
            "travel_time_min"
        ]
    )


    # ========================================================
    # SAFEST
    # ========================================================

    safest = min(
        route_results,
        key=lambda x:
        (
            x[
                "avg_dynamic_risk"
            ],

            x[
                "travel_time_min"
            ]
        )
    )


    # ========================================================
    # BALANCED
    # ========================================================

    min_time = min(
        x[
            "travel_time_min"
        ]
        for x in route_results
    )


    max_time = max(
        x[
            "travel_time_min"
        ]
        for x in route_results
    )


    min_risk = min(
        x[
            "avg_dynamic_risk"
        ]
        for x in route_results
    )


    max_risk = max(
        x[
            "avg_dynamic_risk"
        ]
        for x in route_results
    )


    for result in route_results:

        if max_time > min_time:

            time_score = (
                result[
                    "travel_time_min"
                ]
                - min_time
            ) / (
                max_time
                - min_time
            )

        else:

            time_score = 0.0


        if max_risk > min_risk:

            risk_score = (
                result[
                    "avg_dynamic_risk"
                ]
                - min_risk
            ) / (
                max_risk
                - min_risk
            )

        else:

            risk_score = 0.0


        # ----------------------------------------------------
        # Balanced score
        #
        # 60% travel time
        # 40% risk
        # ----------------------------------------------------

        result[
            "balanced_score"
        ] = (
            0.60
            * time_score
            + 0.40
            * risk_score
        )


    balanced = min(
        route_results,
        key=lambda x:
        x[
            "balanced_score"
        ]
    )


    # ========================================================
    # DISPLAY RECOMMENDATIONS
    # ========================================================

    print(
        "\n"
        + "=" * 70
    )

    print(
        "ROUTE RECOMMENDATIONS"
    )

    print(
        "=" * 70
    )


    # --------------------------------------------------------
    # FASTEST
    # --------------------------------------------------------

    print(
        f"\nFASTEST  → Route "
        f"{fastest['route_id']}"
    )


    print(
        f"Time     : "
        f"{fastest['travel_time_min']:.2f} min"
    )


    print(
        f"Distance : "
        f"{fastest['distance_km']:.2f} km"
    )


    print(
        f"Risk     : "
        f"{fastest['avg_dynamic_risk']:.2f}"
    )


    # --------------------------------------------------------
    # SAFEST
    # --------------------------------------------------------

    print(
        f"\nSAFEST   → Route "
        f"{safest['route_id']}"
    )


    print(
        f"Time     : "
        f"{safest['travel_time_min']:.2f} min"
    )


    print(
        f"Distance : "
        f"{safest['distance_km']:.2f} km"
    )


    print(
        f"Risk     : "
        f"{safest['avg_dynamic_risk']:.2f}"
    )


    # --------------------------------------------------------
    # BALANCED
    # --------------------------------------------------------

    print(
        f"\nBALANCED → Route "
        f"{balanced['route_id']}"
    )


    print(
        f"Time     : "
        f"{balanced['travel_time_min']:.2f} min"
    )


    print(
        f"Distance : "
        f"{balanced['distance_km']:.2f} km"
    )


    print(
        f"Risk     : "
        f"{balanced['avg_dynamic_risk']:.2f}"
    )


    # ========================================================
    # SAVE ROUTE RESULTS
    # ========================================================

    print(
        "\nSaving route results..."
    )


    os.makedirs(
        os.path.dirname(
            ROUTE_RESULTS_FILE
        ),
        exist_ok=True
    )


    csv_columns = [
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
        "observed_percent",
        "propagated_percent",
        "baseline_percent",
        "high_confidence_edges",
        "medium_confidence_edges",
        "low_confidence_edges",
        "balanced_score",
    ]


    with open(
        ROUTE_RESULTS_FILE,
        "w",
        newline=""
    ) as file:

        writer = csv.DictWriter(
            file,
            fieldnames=csv_columns
        )


        writer.writeheader()


        for result in route_results:

            writer.writerow({

                column:
                    result.get(
                        column,
                        0
                    )

                for column
                in csv_columns

            })


    print(
        f"Saved: "
        f"{ROUTE_RESULTS_FILE}"
    )


else:

    print(
        "\nNo route recommendations "
        "available."
    )


# ============================================================
# COMPLETE
# ============================================================

print(
    "\n"
    + "=" * 70
)

print(
    "CANDIDATE ROUTE GENERATION COMPLETE"
)

print(
    "=" * 70
)