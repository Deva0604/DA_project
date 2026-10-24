from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point


# ============================================================
# SAFEROUTE - RISK COVERAGE DIAGNOSIS
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

GRAPH_PATH = BASE_DIR / "data/processed/saferoute_routing_graph_v2.graphml"
RISK_PATH = BASE_DIR / "data/processed/dynamic_road_risk.csv"

OUTPUT_DIR = BASE_DIR / "data/processed"
REPORT_PATH = OUTPUT_DIR / "risk_coverage_diagnosis.csv"


print("=" * 70)
print("SAFEROUTE - RISK COVERAGE DIAGNOSIS")
print("=" * 70)


# ============================================================
# 1. LOAD GRAPH
# ============================================================

print("\n[1/7] Loading routing graph...")

G = nx.read_graphml(GRAPH_PATH)

print(f"Nodes : {len(G.nodes):,}")
print(f"Edges : {len(G.edges):,}")


# ============================================================
# 2. LOAD DYNAMIC RISK DATA
# ============================================================

print("\n[2/7] Loading dynamic road-risk data...")

risk_df = pd.read_csv(RISK_PATH)

print(f"Risk rows : {len(risk_df):,}")

required_columns = [
    "osm_u",
    "osm_v",
    "osm_key",
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "dynamic_risk",
]

missing = [
    col for col in required_columns
    if col not in risk_df.columns
]

if missing:
    raise ValueError(
        f"Missing required columns in risk file: {missing}"
    )


# ============================================================
# 3. IDENTIFY OBSERVED VS BASELINE ROADS
# ============================================================

print("\n[3/7] Separating observed and baseline roads...")

if "risk_source" in risk_df.columns:
    risk_df["risk_source"] = (
        risk_df["risk_source"]
        .astype(str)
        .str.strip()
        .str.lower()
    )

    observed_df = risk_df[
        risk_df["risk_source"] != "baseline_no_observation"
    ].copy()

    baseline_df = risk_df[
        risk_df["risk_source"] == "baseline_no_observation"
    ].copy()
else:
    # dynamic_road_risk.csv (built by 23_build_dynamic_risk.py)
    # contains only observed roads and has no risk_source column.
    # risk_source only exists on the routing graph edges
    # (added by 27_improve_routing_risk_layer.py).
    print(
        "NOTE: 'risk_source' not in risk CSV — "
        "treating all risk rows as observed."
    )
    observed_df = risk_df.copy()
    baseline_df = risk_df.iloc[0:0].copy()

print(f"Total risk rows      : {len(risk_df):,}")
print(f"Observed-risk roads   : {len(observed_df):,}")
print(f"Baseline-risk roads   : {len(baseline_df):,}")


# ============================================================
# 4. BUILD GEOMETRY FROM GRAPH
# ============================================================

print("\n[4/7] Building road geometries from OSM graph...")


def get_float(value):
    """
    Safely convert a graph attribute to float.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


graph_edges = []

for u, v, key, data in G.edges(keys=True, data=True):

    geometry = data.get("geometry")

    if geometry is None:
        # Build straight line from node coordinates
        try:
            x1 = float(G.nodes[u]["x"])
            y1 = float(G.nodes[u]["y"])
            x2 = float(G.nodes[v]["x"])
            y2 = float(G.nodes[v]["y"])

            geometry = LineString([
                (x1, y1),
                (x2, y2)
            ])

        except Exception:
            continue

    else:
        # GraphML may store geometry as a string.
        # For this diagnosis, if geometry is not already
        # a shapely geometry, use node coordinates.
        if not hasattr(geometry, "geom_type"):

            try:
                x1 = float(G.nodes[u]["x"])
                y1 = float(G.nodes[u]["y"])
                x2 = float(G.nodes[v]["x"])
                y2 = float(G.nodes[v]["y"])

                geometry = LineString([
                    (x1, y1),
                    (x2, y2)
                ])

            except Exception:
                continue

    graph_edges.append({
        "osm_u": str(u),
        "osm_v": str(v),
        "osm_key": str(key),
        "geometry": geometry,
    })


graph_gdf = gpd.GeoDataFrame(
    graph_edges,
    geometry="geometry",
    crs="EPSG:4326"
)

print(f"Graph geometries : {len(graph_gdf):,}")


# ============================================================
# 5. MATCH OBSERVED RISK ROADS TO GRAPH
# ============================================================

print("\n[5/7] Matching observed-risk roads to routing graph...")

observed_df["osm_u"] = observed_df["osm_u"].astype(str)
observed_df["osm_v"] = observed_df["osm_v"].astype(str)
observed_df["osm_key"] = observed_df["osm_key"].astype(str)

graph_gdf["osm_u"] = graph_gdf["osm_u"].astype(str)
graph_gdf["osm_v"] = graph_gdf["osm_v"].astype(str)
graph_gdf["osm_key"] = graph_gdf["osm_key"].astype(str)

observed_graph = graph_gdf.merge(
    observed_df[
        [
            "osm_u",
            "osm_v",
            "osm_key",
            "historical_risk",
            "traffic_risk",
            "weather_risk",
            "dynamic_risk",
        ]
    ],
    on=["osm_u", "osm_v", "osm_key"],
    how="inner"
)

print(
    f"Observed roads matched to graph : "
    f"{len(observed_graph):,}"
)


# ============================================================
# 6. SPATIAL COVERAGE ANALYSIS
# ============================================================

print("\n[6/7] Calculating spatial coverage...")

# Project to UTM zone 44N for Chennai.
GRAPH_CRS = "EPSG:4326"
METRIC_CRS = "EPSG:32644"

graph_metric = graph_gdf.to_crs(METRIC_CRS)
observed_metric = observed_graph.to_crs(METRIC_CRS)

print("Calculating nearest observed-risk road distances...")

# Use representative points instead of full geometry
# for a much lighter spatial comparison.
graph_points = graph_metric.copy()
graph_points["geometry"] = graph_points.geometry.representative_point()

observed_points = observed_metric.copy()
observed_points["geometry"] = (
    observed_points.geometry.representative_point()
)

# Spatial nearest join.
# NOTE: sjoin_nearest returns ALL equidistant matches, so one
# graph edge can produce multiple rows. De-duplicate to keep
# the single nearest match per graph edge.
nearest = gpd.sjoin_nearest(
    graph_points[
        [
            "osm_u",
            "osm_v",
            "osm_key",
            "geometry",
        ]
    ],
    observed_points[
        [
            "osm_u",
            "osm_v",
            "osm_key",
            "geometry",
            "dynamic_risk",
        ]
    ],
    how="left",
    distance_col="distance_to_observed_m",
)

if len(nearest) != len(graph_points):
    nearest = nearest.sort_values(
        "distance_to_observed_m"
    )
    nearest = nearest[
        ~nearest.index.duplicated(keep="first")
    ]
    print(
        f"De-duplicated nearest matches : "
        f"{len(nearest):,} (one per graph edge)"
    )

# Avoid confusing duplicated OSM columns from the spatial join.
nearest = nearest.rename(
    columns={
        "dynamic_risk": "nearest_dynamic_risk"
    }
)

distance_series = nearest["distance_to_observed_m"].dropna()

print("\nNearest observed-risk distance statistics:")

if len(distance_series) > 0:

    print(
        f"Mean     : {distance_series.mean():,.1f} m"
    )

    print(
        f"Median   : {distance_series.median():,.1f} m"
    )

    print(
        f"75th %ile: "
        f"{distance_series.quantile(0.75):,.1f} m"
    )

    print(
        f"90th %ile: "
        f"{distance_series.quantile(0.90):,.1f} m"
    )

    print(
        f"95th %ile: "
        f"{distance_series.quantile(0.95):,.1f} m"
    )

    print(
        f"Maximum  : {distance_series.max():,.1f} m"
    )


# ============================================================
# COVERAGE THRESHOLDS
# ============================================================

thresholds = [
    100,
    250,
    500,
    1000,
    2000,
    3000,
]

coverage_rows = []

total_graph_edges = len(graph_gdf)

for threshold in thresholds:

    covered = (
        nearest["distance_to_observed_m"]
        <= threshold
    ).sum()

    percentage = (
        covered / total_graph_edges * 100
        if total_graph_edges > 0
        else 0
    )

    print(
        f"Within {threshold:>4} m : "
        f"{covered:>7,} edges "
        f"({percentage:6.2f}%)"
    )

    coverage_rows.append({
        "analysis": "spatial_coverage",
        "threshold_m": threshold,
        "covered_edges": int(covered),
        "total_edges": int(total_graph_edges),
        "coverage_percent": percentage,
    })


# ============================================================
# OBSERVED RISK STATISTICS
# ============================================================

print("\nObserved-risk statistics:")

if len(observed_df) > 0:

    print(
        f"Dynamic risk mean   : "
        f"{observed_df['dynamic_risk'].mean():.2f}"
    )

    print(
        f"Dynamic risk median : "
        f"{observed_df['dynamic_risk'].median():.2f}"
    )

    print(
        f"Dynamic risk max    : "
        f"{observed_df['dynamic_risk'].max():.2f}"
    )

    print(
        f"High-risk roads     : "
        f"{(observed_df['dynamic_risk'] >= 60).sum():,}"
    )

    medium_count = ((observed_df['dynamic_risk'] >= 35) & (observed_df['dynamic_risk'] < 60)).sum()

    print(
        f"Medium-risk roads   : "
        f"{medium_count:,}"
    )

    print(
        f"Low-risk roads      : "
        f"{(observed_df['dynamic_risk'] < 35).sum():,}"
    )


# ============================================================
# 7. SAVE REPORT
# ============================================================

print("\n[7/7] Saving diagnosis report...")

report_df = pd.DataFrame(coverage_rows)

REPORT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

report_df.to_csv(
    REPORT_PATH,
    index=False
)

print(f"Saved: {REPORT_PATH}")


# ============================================================
# FINAL SUMMARY
# ============================================================

print("\n" + "=" * 70)
print("RISK COVERAGE DIAGNOSIS COMPLETE")
print("=" * 70)

print(f"""
Routing graph edges       : {len(graph_gdf):,}
Observed-risk roads       : {len(observed_df):,}
Matched observed roads    : {len(observed_graph):,}

The important question is:

How much of the routing network is reasonably
close to an observed-risk road?

The distance/coverage statistics above will
determine the next risk-propagation strategy.
""")

print("=" * 70)
