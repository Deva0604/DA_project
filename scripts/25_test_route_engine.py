import os
import math
import pandas as pd
import networkx as nx
import osmnx as ox


GRAPH_FILE = "data/processed/saferoute_routing_graph.graphml"


print("=" * 70)
print("SAFEROUTE - ROUTE ENGINE TEST")
print("=" * 70)


# ============================================================
# CONFIGURATION
# ============================================================

# Chennai Central Railway Station
ORIGIN_LAT = 13.0827
ORIGIN_LON = 80.2707

# Anna Nagar approximate point
DEST_LAT = 13.0850
DEST_LON = 80.2101


# ============================================================
# 1. LOAD GRAPH
# ============================================================

print("\n[1/8] Loading routing graph...")

if not os.path.exists(GRAPH_FILE):
    raise FileNotFoundError(
        f"Graph not found: {GRAPH_FILE}"
    )

G = ox.load_graphml(GRAPH_FILE)

print(f"Nodes : {len(G.nodes):,}")
print(f"Edges : {len(G.edges):,}")


# ============================================================
# 2. PREPARE GRAPH
# ============================================================

print("\n[2/8] Preparing routing graph...")

# GraphML stores all attributes as strings.
# NetworkX Dijkstra needs numeric weights (float), otherwise:
#   TypeError: unsupported operand type(s) for +: 'int' and 'str'
# So coerce edge (and node coordinate) attributes back to numbers.

def _to_float(value, default=0.0):
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            f = float(value)
            return f if math.isfinite(f) else f
        s = str(value).strip()
        if s.lower() in ("", "none", "null", "na", "n/a", "nan"):
            return default
        return float(s)
    except (ValueError, TypeError):
        return default


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).strip().lower()
    return s in ("true", "1", "t", "yes", "y")


# Node coordinates can also come back as strings; nearest_nodes needs floats.
for n, data in G.nodes(data=True):
    if "x" in data:
        data["x"] = _to_float(data["x"], 0.0)
    if "y" in data:
        data["y"] = _to_float(data["y"], 0.0)

FLOAT_EDGE_ATTRS = {
    # attr_name: fallback_default
    "length": 1.0,
    "routing_travel_time": 1.0,
    "safety_weight": 1.0,
    "dynamic_risk": 0.0,
    "historical_risk": 0.0,
    "traffic_risk": 0.0,
    "weather_risk": 0.0,
    "accident_count": 0.0,
    "risk_penalty": 1.0,
}

for _, _, _, data in G.edges(keys=True, data=True):
    for attr, default in FLOAT_EDGE_ATTRS.items():
        if attr in data:
            data[attr] = _to_float(data[attr], default)

    if "road_closure" in data:
        data["road_closure"] = _to_bool(data["road_closure"])


# ============================================================
# 3. FIND NEAREST NODES
# ============================================================

print("\n[3/8] Finding nearest road nodes...")

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

print(f"Origin node      : {origin_node}")
print(f"Destination node : {destination_node}")


# ============================================================
# 4. ROUTE GENERATION FUNCTION
# ============================================================

print("\n[4/8] Preparing route functions...")


def generate_route(
    graph,
    origin,
    destination,
    weight
):

    try:

        route = nx.shortest_path(
            graph,
            origin,
            destination,
            weight=weight
        )

        return route

    except nx.NetworkXNoPath:

        return None


# ============================================================
# 5. ROUTE METRICS
# ============================================================

def calculate_route_metrics(
    graph,
    route
):

    if route is None or len(route) < 2:
        return None


    total_distance = 0.0
    total_time = 0.0

    historical_risk_sum = 0.0
    traffic_risk_sum = 0.0
    weather_risk_sum = 0.0
    dynamic_risk_sum = 0.0

    closed_edges = 0
    observed_edges = 0


    for u, v in zip(
        route[:-1],
        route[1:]
    ):

        # A MultiDiGraph can contain multiple edges
        # between the same two nodes.
        #
        # Choose the edge with the lowest routing weight.

        edge_data = graph.get_edge_data(
            u,
            v
        )

        if edge_data is None:
            continue


        best_key = None
        best_data = None
        best_weight = float("inf")


        for key, data in edge_data.items():

            weight = data.get(
                "routing_travel_time",
                data.get("length", 0)
            )

            try:
                weight = float(weight)
            except:
                weight = float("inf")


            if weight < best_weight:

                best_weight = weight
                best_key = key
                best_data = data


        if best_data is None:
            continue


        # ----------------------------------------------------
        # Distance
        # ----------------------------------------------------

        distance = float(
            best_data.get(
                "length",
                0
            )
        )

        total_distance += distance


        # ----------------------------------------------------
        # Travel time
        # ----------------------------------------------------

        travel_time = best_data.get(
            "routing_travel_time"
        )

        if travel_time is not None:

            travel_time = float(
                travel_time
            )

            if math.isfinite(travel_time):
                total_time += travel_time


        # ----------------------------------------------------
        # Risk metrics
        # ----------------------------------------------------

        historical = float(
            best_data.get(
                "historical_risk",
                0
            )
        )

        traffic = float(
            best_data.get(
                "traffic_risk",
                0
            )
        )

        weather = float(
            best_data.get(
                "weather_risk",
                0
            )
        )

        dynamic = float(
            best_data.get(
                "dynamic_risk",
                0
            )
        )


        historical_risk_sum += historical
        traffic_risk_sum += traffic
        weather_risk_sum += weather
        dynamic_risk_sum += dynamic


        # ----------------------------------------------------
        # Closure
        # ----------------------------------------------------

        if best_data.get(
            "road_closure",
            False
        ):

            closed_edges += 1


        # ----------------------------------------------------
        # Risk observation coverage
        # ----------------------------------------------------

        if best_data.get(
            "risk_source"
        ) == "observed":

            observed_edges += 1


    edge_count = max(
        len(route) - 1,
        1
    )


    return {

        "nodes": len(route),

        "edges": edge_count,

        "distance_km":
            total_distance / 1000,

        "travel_time_min":
            total_time / 60,

        "avg_historical_risk":
            historical_risk_sum / edge_count,

        "avg_traffic_risk":
            traffic_risk_sum / edge_count,

        "avg_weather_risk":
            weather_risk_sum / edge_count,

        "avg_dynamic_risk":
            dynamic_risk_sum / edge_count,

        "total_dynamic_risk":
            dynamic_risk_sum,

        "closed_edges":
            closed_edges,

        "observed_edges":
            observed_edges,

        "risk_coverage_percent":
            observed_edges
            / edge_count
            * 100,

    }


# ============================================================
# 6. GENERATE THREE ROUTES
# ============================================================

print("\n[5/8] Generating candidate routes...")


# ------------------------------------------------------------
# FASTEST
# ------------------------------------------------------------

fastest_route = generate_route(
    G,
    origin_node,
    destination_node,
    "routing_travel_time"
)


# ------------------------------------------------------------
# SAFEST
# ------------------------------------------------------------

safest_route = generate_route(
    G,
    origin_node,
    destination_node,
    "safety_weight"
)


# ------------------------------------------------------------
# BALANCED
# ------------------------------------------------------------

# First generate candidates using both objectives.
#
# For the prototype we use:
#
# balanced weight =
# travel time × (1 + 0.40 × risk/100)
#
# This gives safety meaningful influence while keeping
# travel time as the dominant practical factor.

for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    travel_time = float(
        data.get(
            "routing_travel_time",
            1
        )
    )

    dynamic_risk = float(
        data.get(
            "dynamic_risk",
            0
        )
    )


    if math.isinf(travel_time):

        data["balanced_weight"] = float(
            "inf"
        )

    else:

        data["balanced_weight"] = (
            travel_time
            * (
                1
                + 0.40
                * dynamic_risk
                / 100
            )
        )


balanced_route = generate_route(
    G,
    origin_node,
    destination_node,
    "balanced_weight"
)


# ============================================================
# 7. CALCULATE METRICS
# ============================================================

print("\n[6/8] Calculating route metrics...")


routes = {

    "FASTEST":
        calculate_route_metrics(
            G,
            fastest_route
        ),

    "SAFEST":
        calculate_route_metrics(
            G,
            safest_route
        ),

    "BALANCED":
        calculate_route_metrics(
            G,
            balanced_route
        ),

}


# ============================================================
# 8. DISPLAY RESULTS
# ============================================================

print("\n[7/8] Route comparison...")

print("\n" + "=" * 70)
print("ROUTE RESULTS")
print("=" * 70)


for name, metrics in routes.items():

    print(f"\n{name}")
    print("-" * 50)


    if metrics is None:

        print("NO ROUTE FOUND")
        continue


    print(
        f"Distance              : "
        f"{metrics['distance_km']:.2f} km"
    )

    print(
        f"Travel time           : "
        f"{metrics['travel_time_min']:.2f} min"
    )

    print(
        f"Average historical risk: "
        f"{metrics['avg_historical_risk']:.2f}"
    )

    print(
        f"Average traffic risk   : "
        f"{metrics['avg_traffic_risk']:.2f}"
    )

    print(
        f"Average weather risk   : "
        f"{metrics['avg_weather_risk']:.2f}"
    )

    print(
        f"Average dynamic risk   : "
        f"{metrics['avg_dynamic_risk']:.2f}"
    )

    print(
        f"Total dynamic risk     : "
        f"{metrics['total_dynamic_risk']:.2f}"
    )

    print(
        f"Closed edges           : "
        f"{metrics['closed_edges']}"
    )

    print(
        f"Risk coverage          : "
        f"{metrics['risk_coverage_percent']:.2f}%"
    )

    print(
        f"Road nodes             : "
        f"{metrics['nodes']}"
    )


# ============================================================
# RECOMMENDATION
# ============================================================

print("\n[8/8] Selecting recommended route...")


valid_routes = {
    name: metrics
    for name, metrics in routes.items()
    if metrics is not None
}


if valid_routes:

    # Prefer BALANCED if available.
    recommended = (
        "BALANCED"
        if "BALANCED" in valid_routes
        else list(valid_routes.keys())[0]
    )

    print(
        f"\nRecommended route: "
        f"{recommended}"
    )

else:

    print(
        "\nNo valid route found."
    )


print("\n" + "=" * 70)
print("ROUTE ENGINE TEST COMPLETE")
print("=" * 70)
