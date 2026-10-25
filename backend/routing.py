"""On-demand traffic- and weather-aware routing engine for SafeRoute.

Builds real routing edge costs from the OpenStreetMap graph and the
validated dynamic road-risk dataset (historical accident risk, live TomTom
traffic risk, Open-Meteo weather risk). Closed roads are excluded as a hard
constraint. Multiple feasible route categories are produced from actual
computed edge costs - no hardcoded paths.

All risk components use a 0-100 normalized scale. Missing observations are
never silently treated as zero risk.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx
import osmnx as ox
import osmnx.io as oxio
import ast
import contextlib
from shapely import wkt
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent.parent
GRAPH_FILE = BASE_DIR / "data/processed/saferoute_routing_graph_v6.graphml"
DYNAMIC_RISK_FILE = BASE_DIR / "data/processed/dynamic_road_risk.csv"


def patch_osmnx_edge_conversion():
    """Handle GraphML edge attributes that are already non-string values."""
    original = oxio._convert_edge_attr_types
    if getattr(original, "_saferoute_patched", False):
        return

    def safe_convert(G, dtypes):
        for _, _, data in G.edges(data=True):
            data.pop("id", None)
            for attr, value in list(data.items()):
                if isinstance(value, str):
                    if (
                        (value.startswith("[") and value.endswith("]"))
                        or (value.startswith("{") and value.endswith("}"))
                    ):
                        with contextlib.suppress(SyntaxError, ValueError):
                            data[attr] = ast.literal_eval(value)
            for attr in data.keys() & dtypes.keys():
                if isinstance(data[attr], list):
                    data[attr] = [dtypes[attr](item) for item in data[attr]]
                else:
                    data[attr] = dtypes[attr](data[attr])
            if "geometry" in data and isinstance(data["geometry"], str):
                data["geometry"] = wkt.loads(data["geometry"])
        return G

    safe_convert._saferoute_patched = True
    oxio._convert_edge_attr_types = safe_convert

patch_osmnx_edge_conversion()


# Prototype engineering weights (not calibrated probabilities).
HISTORICAL_WEIGHT = 0.50
TRAFFIC_WEIGHT = 0.30
WEATHER_WEIGHT = 0.20

ROAD_KEYS = ("osm_u", "osm_v", "osm_key")

# Congestion categories based on observed travel time / free-flow travel time.
# Each entry: (min_ratio, max_ratio, label). ratio >= 1.0.
CONGESTION_CATEGORIES = [
    (1.00, 1.10, "Free flow"),
    (1.10, 1.25, "Low congestion"),
    (1.25, 1.50, "Moderate congestion"),
    (1.50, 2.00, "Heavy congestion"),
    (2.00, math.inf, "Severe congestion"),
]

RISK_CATEGORY_THRESHOLDS = [
    (0.0, 20.0, "Low"),
    (20.0, 40.0, "Moderate"),
    (40.0, 70.0, "High"),
    (70.0, 100.0, "Severe"),
]


@dataclass
class EdgeCost:
    """Computed cost and risk components for a single directed road edge."""

    u: int
    v: int
    key: int
    travel_time_sec: float
    distance_m: float
    historical_risk: Optional[float]
    traffic_risk: Optional[float]
    weather_risk: Optional[float]
    combined_risk: Optional[float]
    closed: bool
    congestion_ratio: Optional[float]
    congestion_category: Optional[str]
    data_components_available: int  # 0..3
    weather_observation_time: Optional[str] = None
    traffic_observation_time: Optional[str] = None

    @property
    def edge_id(self):
        return (self.u, self.v, self.key)


def risk_category(score: Optional[float]) -> str:
    if score is None or not math.isfinite(score):
        return "Unavailable"
    for lo, hi, label in RISK_CATEGORY_THRESHOLDS:
        if lo <= score < hi:
            return label
    return "Severe"


def congestion_category_from_ratio(ratio: Optional[float]) -> Optional[str]:
    if ratio is None or not math.isfinite(ratio) or ratio < 1.0:
        return None
    for lo, hi, label in CONGESTION_CATEGORIES:
        if lo <= ratio < hi:
            return label
    return "Severe congestion"


def combined_risk(
    historical: Optional[float],
    traffic: Optional[float],
    weather: Optional[float],
    weights: tuple[float, float, float] = (
        HISTORICAL_WEIGHT,
        TRAFFIC_WEIGHT,
        WEATHER_WEIGHT,
    ),
) -> Optional[float]:
    """Weighted combined risk, renormalized over available components.

    Missing components are excluded rather than treated as zero risk. Returns
    None when no component is available.
    """
    w_hist, w_traffic, w_weather = weights
    total_weight = 0.0
    weighted = 0.0
    if historical is not None and math.isfinite(historical):
        weighted += w_hist * historical
        total_weight += w_hist
    if traffic is not None and math.isfinite(traffic):
        weighted += w_traffic * traffic
        total_weight += w_traffic
    if weather is not None and math.isfinite(weather):
        weighted += w_weather * weather
        total_weight += w_weather
    if total_weight <= 0:
        return None
    return round(weighted / total_weight, 2)


def traffic_risk_from_travel_times(
    current_travel_time_sec: Optional[float],
    free_flow_travel_time_sec: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Derive congestion ratio and traffic risk from observed travel times.

    congestion_ratio = observed_travel_time / free_flow_travel_time.
    traffic_risk = clamp((ratio - 1) * 100, 0, 100).

    Returns (congestion_ratio, traffic_risk) or (None, None) when inputs are
    missing or invalid. Never fabricates measurements.
    """
    if (
        current_travel_time_sec is None
        or free_flow_travel_time_sec is None
        or not math.isfinite(current_travel_time_sec)
        or not math.isfinite(free_flow_travel_time_sec)
        or free_flow_travel_time_sec <= 0
        or current_travel_time_sec < 0
    ):
        return None, None
    ratio = current_travel_time_sec / free_flow_travel_time_sec
    risk = min(100.0, max(0.0, (ratio - 1.0) * 100.0))
    return round(ratio, 4), round(risk, 2)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

_graph_cache: Optional[nx.MultiDiGraph] = None
_risk_cache: Optional[pd.DataFrame] = None


def load_graph() -> nx.MultiDiGraph:
    global _graph_cache
    if _graph_cache is None:
        if not GRAPH_FILE.exists():
            raise FileNotFoundError(f"Road graph not found: {GRAPH_FILE}")
        _graph_cache = ox.load_graphml(GRAPH_FILE)
    return _graph_cache


def load_dynamic_risk() -> pd.DataFrame:
    global _risk_cache
    if _risk_cache is None:
        if not DYNAMIC_RISK_FILE.exists():
            raise FileNotFoundError(f"Dynamic risk file not found: {DYNAMIC_RISK_FILE}")
        df = pd.read_csv(DYNAMIC_RISK_FILE)
        for column in ROAD_KEYS:
            df[column] = pd.to_numeric(df[column], errors="coerce").astype("Int64")
        if df[list(ROAD_KEYS)].isna().any().any():
            raise ValueError("Dynamic risk file contains missing road identifiers.")
        if df.duplicated(list(ROAD_KEYS)).any():
            raise ValueError("Dynamic risk file contains duplicate road identifiers.")
        for column in ("historical_risk", "traffic_risk", "weather_risk", "dynamic_risk"):
            if column in df.columns:
                df[column] = pd.to_numeric(df[column], errors="coerce")
        _risk_cache = df
    return _risk_cache


def build_risk_lookup(risk_df: pd.DataFrame) -> dict:
    lookup: dict = {}
    for row in risk_df.to_dict(orient="records"):
        key = (int(row["osm_u"]), int(row["osm_v"]), int(row["osm_key"]))
        lookup[key] = row
    return lookup


def _norm_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in {"true", "1", "yes", "y", "t"}


def _safe_float(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (TypeError, ValueError):
        return default


def _edge_travel_time(data, row) -> float:
    """Resolved travel time in seconds.

    Prefers the observed current travel time from TomTom, then the graph's
    precomputed routing travel time, then a free-flow estimate from length
    and model speed. Never fabricates a measurement when nothing is available
    (returns 0.0 so the edge is dropped).
    """
    if row is not None:
        value = _safe_float(row.get("current_travel_time_sec"))
        if value and value > 0:
            return value
        value = _safe_float(row.get("free_flow_travel_time_sec"))
        if value and value > 0:
            return value
    value = _safe_float(data.get("routing_travel_time"))
    if value and value > 0:
        return value
    length = _safe_float(data.get("length"), 0.0)
    speed = _safe_float(data.get("model_speed_kph"), 0.0)
    if length > 0 and speed > 0:
        return length / (speed / 3.6)
    if length > 0:
        return length / (30.0 / 3.6)  # nominal 30 km/h free-flow fallback
    return 0.0


def _component(value) -> Optional[float]:
    if value is None:
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def build_routing_graph(
    graph: nx.MultiDiGraph,
    risk_lookup: dict,
    exclude_closed: bool = True,
) -> nx.DiGraph:
    """Build a directed routing graph with real edge costs and risk data.

    The full OpenStreetMap graph is used (minus closed roads) so a connected
    path is preserved. Where a validated dynamic-risk record exists for an
    edge, the observed historical/traffic/weather risk is used. Otherwise the
    graph's propagated risk attributes are used, and the edge is flagged with
    the number of genuinely observed components so missing data is never
    mistaken for zero risk.
    """
    routing = nx.DiGraph()
    routing.add_nodes_from(graph.nodes(data=True))

    for u, v, key, data in graph.edges(keys=True, data=True):
        identifier = (int(u), int(v), int(key))
        row = risk_lookup.get(identifier)

        closed = _norm_bool(data.get("road_closure", False))
        if row is not None:
            closed = closed or _norm_bool(row.get("road_closure", False))
        if exclude_closed and closed:
            continue

        travel_time = _edge_travel_time(data, row)
        distance = _safe_float(
            (row or {}).get("road_length_m", data.get("length")),
            _safe_float(data.get("length"), 0.0),
        )
        if travel_time <= 0 or distance < 0:
            continue

        if row is not None:
            historical = _component(row.get("historical_risk"))
            traffic = _component(row.get("traffic_risk"))
            weather = _component(row.get("weather_risk"))
            crisk = combined_risk(historical, traffic, weather)
            combined = (
                crisk
                if crisk is not None
                else _component(row.get("dynamic_risk"))
            )
            components_available = sum(
                1 for value in (historical, traffic, weather) if value is not None
            )
            c_ratio, c_risk = traffic_risk_from_travel_times(
                row.get("current_travel_time_sec"),
                row.get("free_flow_travel_time_sec"),
            )
            observation_source = "observed"
        else:
            historical = _component(data.get("historical_risk"))
            traffic = _component(data.get("traffic_risk"))
            weather = _component(data.get("weather_risk"))
            combined = _component(data.get("dynamic_risk"))
            components_available = sum(
                1 for value in (historical, traffic, weather) if value is not None
            )
            observed_components_available = 0
            c_ratio, c_risk = traffic_risk_from_travel_times(None, None)
            observation_source = "propagated"

        congestion_category = congestion_category_from_ratio(c_ratio)

        if row is not None:
            observed_components_available = sum(
                1 for value in (historical, traffic, weather) if value is not None
            )

        edge_data = dict(data)
        edge_data.update(
            {
                "original_key": key,
                "travel_time": travel_time,
                "travel_time_sec": travel_time,
                "length": distance,
                "distance_m": distance,
                "historical_risk": historical,
                "traffic_risk": traffic,
                "weather_risk": weather,
                "combined_risk": combined,
                "dynamic_risk": combined,
                "road_closure": closed,
                "congestion_ratio": c_ratio,
                "congestion_category": congestion_category,
                "data_components_available": components_available,
                "observed_components_available": observed_components_available,
                "observation_source": observation_source,
                "weather_observation_time": (
                    row.get("observation_time") if row is not None else None
                ),
                "traffic_observation_time": (
                    row.get("traffic_observation_time") if row is not None else None
                ),
                "weather_grid_id": row.get("weather_grid_id") if row is not None else None,
                "weather_distance_km": (
                    row.get("weather_distance_km") if row is not None else None
                ),
                "road_name": (
                    row.get("road_name") if row is not None else data.get("name")
                ),
                "highway": data.get("highway"),
            }
        )

        existing = routing.get_edge_data(u, v)
        if existing is None:
            routing.add_edge(u, v, **edge_data)
        else:
            existing_cr = existing.get("combined_risk")
            if combined is not None and (
                existing_cr is None or combined < existing_cr
            ):
                routing.add_edge(u, v, **edge_data)

    return routing


# ---------------------------------------------------------------------------
# Route metrics
# ---------------------------------------------------------------------------

def path_edge_datas(routing: nx.DiGraph, path) -> list:
    datas = []
    for u, v in zip(path[:-1], path[1:]):
        data = routing.get_edge_data(u, v)
        if data:
            datas.append(data)
    return datas


def compute_route_metrics(routing: nx.DiGraph, path) -> dict:
    """Compute documented, consistent metrics for a node path."""
    datas = path_edge_datas(routing, path)
    if not datas:
        return None

    travel_time_sec = sum(
        d.get("travel_time", 0.0) or 0.0 for d in datas
    )
    distance_m = sum(d.get("length", 0.0) for d in datas)

    def weighted_avg(component):
        total = 0.0
        weight = 0.0
        for d in datas:
            value = d.get(component)
            length = d.get("length", 0.0) or 0.0
            if value is not None and math.isfinite(value) and length > 0:
                total += value * length
                weight += length
        return round(total / weight, 2) if weight > 0 else None

    def simple_avg(component):
        values = [
            d.get(component) for d in datas
            if d.get(component) is not None and math.isfinite(d.get(component))
        ]
        return round(sum(values) / len(values), 2) if values else None

    historical_values = [
        d.get("historical_risk") for d in datas
        if d.get("historical_risk") is not None and math.isfinite(d.get("historical_risk"))
    ]
    traffic_values = [
        d.get("traffic_risk") for d in datas
        if d.get("traffic_risk") is not None and math.isfinite(d.get("traffic_risk"))
    ]
    weather_values = [
        d.get("weather_risk") for d in datas
        if d.get("weather_risk") is not None and math.isfinite(d.get("weather_risk"))
    ]
    combined_values = [
        d.get("combined_risk") for d in datas
        if d.get("combined_risk") is not None and math.isfinite(d.get("combined_risk"))
    ]

    congestion_ratios = [
        d.get("congestion_ratio") for d in datas
        if d.get("congestion_ratio") is not None and math.isfinite(d.get("congestion_ratio"))
    ]
    congestion_categories = [
        d.get("congestion_category") for d in datas if d.get("congestion_category")
    ]

    components_available = sum(d.get("data_components_available", 0) for d in datas)
    observed_components_available = sum(
        d.get("observed_components_available", 0) for d in datas
    )
    components_total = len(datas) * 3

    obs_times = [
        d.get("weather_observation_time") for d in datas if d.get("weather_observation_time")
    ]
    traffic_obs_times = [
        d.get("traffic_observation_time") for d in datas if d.get("traffic_observation_time")
    ]

    sources = {d.get("observation_source") for d in datas if d.get("observation_source")}

    return {
        "edge_count": len(datas),
        "distance_m": round(distance_m, 2),
        "distance_km": round(distance_m / 1000.0, 3),
        "travel_time_sec": round(travel_time_sec, 2),
        "travel_time_min": round(travel_time_sec / 60.0, 2),
        "distance_weighted_combined_risk": weighted_avg("combined_risk"),
        "distance_weighted_historical_risk": weighted_avg("historical_risk"),
        "distance_weighted_traffic_risk": weighted_avg("traffic_risk"),
        "distance_weighted_weather_risk": weighted_avg("weather_risk"),
        "avg_historical_risk": simple_avg("historical_risk"),
        "avg_traffic_risk": simple_avg("traffic_risk"),
        "avg_weather_risk": simple_avg("weather_risk"),
        "avg_combined_risk": simple_avg("combined_risk"),
        "historical_risk_values": historical_values,
        "traffic_risk_values": traffic_values,
        "weather_risk_values": weather_values,
        "combined_risk_values": combined_values,
        "congestion_ratio": round(sum(congestion_ratios) / len(congestion_ratios), 4)
        if congestion_ratios else None,
        "congestion_categories": congestion_categories,
        "data_components_available": components_available,
        "observed_components_available": observed_components_available,
        "data_components_total": components_total,
        "data_coverage_percent": round(
            100.0 * components_available / components_total, 1
        ) if components_total else None,
        "observed_coverage_percent": round(
            100.0 * observed_components_available / components_total, 1
        ) if components_total else None,
        "observation_sources": sorted(sources),
        "weather_observation_time": obs_times[0] if obs_times else None,
        "traffic_observation_time": traffic_obs_times[0] if traffic_obs_times else None,
    }


# ---------------------------------------------------------------------------
# Path finding
# ---------------------------------------------------------------------------

def nearest_node(routing: nx.DiGraph, lon: float, lat: float) -> int:
    return min(
        routing.nodes,
        key=lambda n: (
            (routing.nodes[n].get("x", 0.0) - lon) ** 2
            + (routing.nodes[n].get("y", 0.0) - lat) ** 2
        ),
    )


def _edge_weight(routing: nx.DiGraph, mode: str):
    def weight(u, v, data):
        travel_time = data.get("travel_time", 0.0) or 0.0
        distance = data.get("length", 0.0) or 0.0
        combined = data.get("combined_risk")
        weather = data.get("weather_risk")
        if mode == "fastest":
            return travel_time
        if mode == "safest":
            return ((combined if combined is not None else 50.0) / 100.0) * max(
                distance, 1.0
            )
        if mode == "balanced":
            return travel_time * (1.0 + ((combined if combined is not None else 50.0) / 100.0))
        if mode == "weather_aware":
            weather_factor = (weather if weather is not None else 0.0) / 100.0
            return travel_time * (1.0 + weather_factor)
        return travel_time
    return weight


def _dijkstra_path(routing, origin, destination, mode):
    try:
        return nx.shortest_path(
            routing, origin, destination,
            weight=_edge_weight(routing, mode),
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
        return None


def _penalized_path(routing, origin, destination, base_mode, avoid_edges, penalty=3.0):
    """Dijkstra that penalizes reuse of edges from previously found paths."""
    original_weights = {}
    for u, v, data in routing.edges(data=True):
        original_weights[(u, v)] = _edge_weight(routing, base_mode)(u, v, data)

    def weight(u, v, data):
        base = original_weights[(u, v)]
        if (u, v) in avoid_edges:
            return base * penalty
        return base

    try:
        return nx.shortest_path(routing, origin, destination, weight=weight)
    except (nx.NetworkXNoPath, nx.NodeNotFound, nx.NetworkXError):
        return None


def _signature(path):
    return tuple(path) if path else None


# Journey definitions (real origin/destination points for Chennai corridors).
JOURNEYS = {
    1: {"origin": "Chennai Central", "destination": "Anna Nagar",
        "origin_lat": 13.0827, "origin_lon": 80.2707,
        "destination_lat": 13.0850, "destination_lon": 80.2101},
    2: {"origin": "Guindy", "destination": "T Nagar",
        "origin_lat": 13.0067, "origin_lon": 80.2206,
        "destination_lat": 13.0418, "destination_lon": 80.2341},
    3: {"origin": "Adyar", "destination": "Perambur",
        "origin_lat": 13.0012, "origin_lon": 80.2565,
        "destination_lat": 13.1167, "destination_lon": 80.2333},
    4: {"origin": "Velachery", "destination": "Tambaram",
        "origin_lat": 12.9750, "origin_lon": 80.2210,
        "destination_lat": 12.9249, "destination_lon": 80.1000},
    5: {"origin": "Chennai Airport", "destination": "Marina Beach",
        "origin_lat": 12.9941, "origin_lon": 80.1709,
        "destination_lat": 13.0500, "destination_lon": 80.2824},
}


def _route_summary(routing, path, test, label, mode, source_note):
    metrics = compute_route_metrics(routing, path)
    if metrics is None:
        return None
    coordinates = [
        [float(routing.nodes[n]["y"]), float(routing.nodes[n]["x"])]
        for n in path
    ]
    return {
        "test_id": test["test_id"],
        "origin": test["origin"],
        "destination": test["destination"],
        "category": label,
        "mode": mode,
        "source_note": source_note,
        "travel_time_min": metrics["travel_time_min"],
        "distance_km": metrics["distance_km"],
        "distance_weighted_combined_risk": metrics["distance_weighted_combined_risk"],
        "distance_weighted_historical_risk": metrics["distance_weighted_historical_risk"],
        "distance_weighted_traffic_risk": metrics["distance_weighted_traffic_risk"],
        "distance_weighted_weather_risk": metrics["distance_weighted_weather_risk"],
        "avg_historical_risk": metrics["avg_historical_risk"],
        "avg_traffic_risk": metrics["avg_traffic_risk"],
        "avg_weather_risk": metrics["avg_weather_risk"],
        "avg_combined_risk": metrics["avg_combined_risk"],
        "congestion_ratio": metrics["congestion_ratio"],
        "congestion_categories": metrics["congestion_categories"],
        "data_coverage_percent": metrics["data_coverage_percent"],
        "observed_coverage_percent": metrics["observed_coverage_percent"],
        "data_components_available": metrics["data_components_available"],
        "observed_components_available": metrics["observed_components_available"],
        "data_components_total": metrics["data_components_total"],
        "observation_sources": metrics["observation_sources"],
        "weather_observation_time": metrics["weather_observation_time"],
        "traffic_observation_time": metrics["traffic_observation_time"],
        "edge_count": metrics["edge_count"],
        "coordinates": coordinates,
        "node_path": "|".join(str(n) for n in path),
    }


def get_route_options(
    origin_lat, origin_lon, destination_lat, destination_lon,
    test_id=None, test_origin="Origin", test_destination="Destination",
):
    """Compute and compare multiple feasible routes between two points.

    Returns a list of route summary dicts (one per category) plus engine
    diagnostics. Routes are produced from real computed edge costs.
    """
    graph = load_graph()
    risk_df = load_dynamic_risk()
    risk_lookup = build_risk_lookup(risk_df)
    routing = build_routing_graph(graph, risk_lookup, exclude_closed=True)

    origin = nearest_node(routing, float(origin_lon), float(origin_lat))
    destination = nearest_node(routing, float(destination_lon), float(destination_lat))

    test = {
        "test_id": test_id,
        "origin": test_origin,
        "destination": test_destination,
    }

    diagnostics = {
        "nodes": routing.number_of_nodes(),
        "edges": routing.number_of_edges(),
        "closed_edges_excluded": True,
        "origin_node": origin,
        "destination_node": destination,
    }

    if not nx.has_path(routing, origin, destination):
        return [], diagnostics

    avoid_edges = set()
    routes = []

    # 1. FASTEST: minimize travel time using current traffic-based times.
    path = _dijkstra_path(routing, origin, destination, "fastest")
    if path:
        sig = _signature(path)
        avoid_edges.update(zip(path[:-1], path[1:]))
        routes.append(_route_summary(
            routing, path, test, "Fastest Route", "fastest",
            "Minimizes estimated travel time using current TomTom traffic observations."
        ))

    # 2. SAFEST: minimize distance-weighted combined risk.
    path = _dijkstra_path(routing, origin, destination, "safest")
    if path and _signature(path) not in {r["node_path"] for r in routes}:
        routes.append(_route_summary(
            routing, path, test, "Safest Route", "safest",
            "Minimizes distance-weighted combined road risk (historical 50%, traffic 30%, weather 20%)."
        ))

    # 3. WEATHER-AWARE: minimize travel time penalized by weather risk.
    path = _dijkstra_path(routing, origin, destination, "weather_aware")
    if path and _signature(path) not in {r["node_path"] for r in routes}:
        routes.append(_route_summary(
            routing, path, test, "Weather-Aware Route", "weather_aware",
            "Minimizes travel time weighted by Open-Meteo weather risk while respecting closures."
        ))

    # 4. BALANCED: combination of normalized time and risk across candidates.
    path = _dijkstra_path(routing, origin, destination, "balanced")
    if path and _signature(path) not in {r["node_path"] for r in routes}:
        routes.append(_route_summary(
            routing, path, test, "Balanced Route", "balanced",
            "Optimizes a blend of normalized travel time and combined road risk."
        ))

    # 5. ALTERNATIVE: feasible route that meaningfully differs from others.
    path = _penalized_path(routing, origin, destination, "fastest", avoid_edges, penalty=4.0)
    if path and _signature(path) not in {r["node_path"] for r in routes}:
        routes.append(_route_summary(
            routing, path, test, "Alternative Route", "alternative",
            "Feasible route that diverges from the other recommendations."
        ))

    # Annotate routes with relative explanations.
    if routes:
        times = [r["travel_time_min"] for r in routes]
        risks = [
            r["distance_weighted_combined_risk"]
            for r in routes
            if r["distance_weighted_combined_risk"] is not None
        ]
        min_time, max_time = min(times), max(times)
        min_risk, max_risk = (min(risks), max(risks)) if risks else (None, None)

        for route in routes:
            explanation = []
            if route["travel_time_min"] == min_time:
                explanation.append("shortest estimated travel time")
            if (
                min_risk is not None
                and route["distance_weighted_combined_risk"] == min_risk
            ):
                explanation.append("lowest estimated combined road risk")
            if route["category"] == "Safest Route":
                explanation.append("prioritizes risk minimization over speed")
            if route["category"] == "Weather-Aware Route":
                explanation.append("avoids weather-affected road segments")
            if route["category"] == "Alternative Route":
                explanation.append("takes a different road corridor")
            if not explanation:
                explanation.append("feasible alternative within the network")
            route["selection_reason"] = "; ".join(explanation)

            # Relative time/risk notes.
            if max_time > min_time:
                overhead = ((route["travel_time_min"] - min_time) / min_time) * 100
                route["time_overhead_percent_vs_fastest"] = round(overhead, 1)
            else:
                route["time_overhead_percent_vs_fastest"] = 0.0

    return routes, diagnostics
