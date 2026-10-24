from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString


# ============================================================
# SAFEROUTE - SPATIAL RISK PROPAGATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parents[1]

GRAPH_PATH = (
    BASE_DIR
    / "data/processed/saferoute_routing_graph_v2.graphml"
)

RISK_PATH = (
    BASE_DIR
    / "data/processed/dynamic_road_risk.csv"
)

OUTPUT_GRAPH_PATH = (
    BASE_DIR
    / "data/processed/saferoute_routing_graph_v3.graphml"
)

OUTPUT_CSV_PATH = (
    BASE_DIR
    / "data/processed/spatially_propagated_risk.csv"
)


# ============================================================
# CONFIGURATION
# ============================================================

MAX_PROPAGATION_DISTANCE_M = 500.0

# Baseline risk for roads with no nearby observed risk.
BASELINE_HISTORICAL_RISK = 10.0
BASELINE_TRAFFIC_RISK = 0.0
BASELINE_WEATHER_RISK = 0.0

# Weight used when combining nearby observed roads.
# Closer roads receive stronger influence.
DISTANCE_POWER = 2.0


print("=" * 70)
print("SAFEROUTE - SPATIAL RISK PROPAGATION")
print("=" * 70)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def safe_float(value, default=0.0):
    try:
        value = float(value)

        if np.isnan(value):
            return default

        return value

    except (TypeError, ValueError):
        return default


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


def build_geometry(G, u, v, data):
    """
    Return a LineString for an OSM graph edge.

    GraphML geometry can sometimes be unavailable or stored
    as a string, so we safely fall back to node coordinates.
    """

    geometry = data.get("geometry")

    if geometry is not None and hasattr(
        geometry,
        "geom_type"
    ):
        return geometry

    try:

        x1 = float(G.nodes[u]["x"])
        y1 = float(G.nodes[u]["y"])

        x2 = float(G.nodes[v]["x"])
        y2 = float(G.nodes[v]["y"])

        return LineString([
            (x1, y1),
            (x2, y2),
        ])

    except Exception:

        return None


# ============================================================
# 1. LOAD GRAPH
# ============================================================

print("\n[1/9] Loading routing graph...")

G = nx.read_graphml(GRAPH_PATH)

print(f"Nodes : {len(G.nodes):,}")
print(f"Edges : {len(G.edges):,}")


# ============================================================
# 2. LOAD RISK DATA
# ============================================================

print("\n[2/9] Loading dynamic risk data...")

risk_df = pd.read_csv(RISK_PATH)

print(f"Risk rows : {len(risk_df):,}")

required = [
    "osm_u",
    "osm_v",
    "osm_key",
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "dynamic_risk",
]

missing = [
    column
    for column in required
    if column not in risk_df.columns
]

if missing:

    raise ValueError(
        f"Missing required columns: {missing}"
    )


# ============================================================
# 3. NORMALIZE OSM IDENTIFIERS
# ============================================================

print("\n[3/9] Normalizing OSM identifiers...")

for column in [
    "osm_u",
    "osm_v",
    "osm_key",
]:

    risk_df[column] = (
        risk_df[column]
        .astype(str)
        .str.strip()
    )


# ============================================================
# 4. BUILD GRAPH EDGE GEOMETRIES
# ============================================================

print("\n[4/9] Building graph edge geometries...")

graph_records = []

for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    geometry = build_geometry(
        G,
        u,
        v,
        data
    )

    if geometry is None:
        continue

    graph_records.append({
        "osm_u": str(u),
        "osm_v": str(v),
        "osm_key": str(key),
        "geometry": geometry,
        "road_closure": parse_bool(
            data.get("road_closure")
        ),
    })


graph_gdf = gpd.GeoDataFrame(
    graph_records,
    geometry="geometry",
    crs="EPSG:4326",
)

print(
    f"Graph edge geometries : "
    f"{len(graph_gdf):,}"
)


# ============================================================
# 5. MATCH OBSERVED RISK ROADS
# ============================================================

print("\n[5/9] Matching observed risk roads...")

risk_gdf = graph_gdf.merge(
    risk_df[
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
    on=[
        "osm_u",
        "osm_v",
        "osm_key",
    ],
    how="left",
)

risk_gdf["observed"] = (
    risk_gdf["dynamic_risk"]
    .notna()
)

print(
    f"Observed edges : "
    f"{risk_gdf['observed'].sum():,}"
)

print(
    f"Unobserved edges : "
    f"{(~risk_gdf['observed']).sum():,}"
)


# ============================================================
# 6. PROJECT TO METRIC CRS
# ============================================================

print("\n[6/9] Projecting roads to metric coordinates...")

METRIC_CRS = "EPSG:32644"

risk_metric = risk_gdf.to_crs(
    METRIC_CRS
)

# Representative points provide a stable location for
# nearest-neighbour risk propagation.

risk_metric["representative_point"] = (
    risk_metric.geometry.representative_point()
)


observed_metric = risk_metric[
    risk_metric["observed"]
].copy()

unobserved_metric = risk_metric[
    ~risk_metric["observed"]
].copy()


print(
    f"Observed source roads : "
    f"{len(observed_metric):,}"
)

print(
    f"Target roads           : "
    f"{len(unobserved_metric):,}"
)


# ============================================================
# 7. FIND NEARBY OBSERVED ROADS
# ============================================================

print(
    "\n[7/9] Propagating risk within "
    f"{MAX_PROPAGATION_DISTANCE_M:.0f} m..."
)

if len(observed_metric) == 0:

    raise ValueError(
        "No observed-risk roads were found."
    )


# ------------------------------------------------------------
# Create source GeoDataFrame
# ------------------------------------------------------------

source_points = gpd.GeoDataFrame(
    observed_metric[
        [
            "osm_u",
            "osm_v",
            "osm_key",
            "representative_point",
            "historical_risk",
            "traffic_risk",
            "weather_risk",
            "dynamic_risk",
        ]
    ].copy(),
    geometry="representative_point",
    crs=METRIC_CRS,
)


# ------------------------------------------------------------
# Create target GeoDataFrame
# ------------------------------------------------------------

target_points = gpd.GeoDataFrame(
    unobserved_metric[
        [
            "osm_u",
            "osm_v",
            "osm_key",
            "representative_point",
        ]
    ].copy(),
    geometry="representative_point",
    crs=METRIC_CRS,
)


# ------------------------------------------------------------
# Find all observed roads within 500 m.
# ------------------------------------------------------------

nearby = gpd.sjoin(
    target_points,
    source_points,
    how="left",
    predicate="dwithin",
    distance=MAX_PROPAGATION_DISTANCE_M,
)


# ============================================================
# CALCULATE DISTANCE
# ============================================================

print(
    f"Candidate spatial relationships : "
    f"{len(nearby):,}"
)


# Spatial join does not directly provide the exact distance,
# so calculate it for each matched pair.
#
# NOTE: sjoin keeps only the LEFT (target) geometry and drops
# the RIGHT (source) geometry, and iterrows() yields plain
# Series (no .geometry). So look up both geometries via maps
# built from the original GeoDataFrames.

target_geometry_map = {
    (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"]),
    ): row["representative_point"]
    for _, row in target_points.iterrows()
}


source_geometry_map = {
    (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"]),
    ): row["representative_point"]
    for _, row in source_points.iterrows()
}


distances = []

for _, row in nearby.iterrows():

    source_u = row.get("osm_u_right")
    source_v = row.get("osm_v_right")
    source_key = row.get("osm_key_right")

    if pd.isna(source_u):
        distances.append(np.nan)
        continue

    source_geom = source_geometry_map.get(
        (
            str(source_u),
            str(source_v),
            str(source_key),
        )
    )

    target_geom = target_geometry_map.get(
        (
            str(row.get("osm_u_left")),
            str(row.get("osm_v_left")),
            str(row.get("osm_key_left")),
        )
    )

    if target_geom is None:
        # Fallback to the joined left geometry.
        target_geom = row.get("representative_point")

    if source_geom is None or target_geom is None:
        distances.append(np.nan)
        continue

    distances.append(
        target_geom.distance(
            source_geom
        )
    )


nearby["distance_m"] = distances

nearby = nearby[
    nearby["distance_m"].notna()
].copy()

nearby = nearby[
    nearby["distance_m"]
    <= MAX_PROPAGATION_DISTANCE_M
].copy()


print(
    f"Valid nearby relationships : "
    f"{len(nearby):,}"
)


# ============================================================
# DISTANCE-WEIGHTED RISK
# ============================================================

print("\nCalculating distance-weighted risk...")


def calculate_weight(distance):
    """
    Inverse-distance weighting.

    A tiny minimum distance prevents division by zero.
    """

    distance = max(
        float(distance),
        1.0
    )

    return 1.0 / (
        distance ** DISTANCE_POWER
    )


nearby["weight"] = (
    nearby["distance_m"]
    .apply(calculate_weight)
)


# ============================================================
# AGGREGATE RISK FOR EACH TARGET ROAD
# ============================================================

group_columns = [
    "osm_u_left",
    "osm_v_left",
    "osm_key_left",
]


aggregated_rows = []

for target_id, group in nearby.groupby(
    group_columns,
    dropna=False
):

    weights = group["weight"].to_numpy()

    weight_sum = weights.sum()

    if weight_sum <= 0:
        continue

    historical = np.average(
        group["historical_risk"].astype(float),
        weights=weights,
    )

    traffic = np.average(
        group["traffic_risk"].astype(float),
        weights=weights,
    )

    weather = np.average(
        group["weather_risk"].astype(float),
        weights=weights,
    )

    dynamic = np.average(
        group["dynamic_risk"].astype(float),
        weights=weights,
    )

    nearest_distance = (
        group["distance_m"].min()
    )

    source_count = len(group)

    aggregated_rows.append({
        "osm_u": str(target_id[0]),
        "osm_v": str(target_id[1]),
        "osm_key": str(target_id[2]),

        "propagated_historical_risk":
            historical,

        "propagated_traffic_risk":
            traffic,

        "propagated_weather_risk":
            weather,

        "propagated_dynamic_risk":
            dynamic,

        "nearest_observed_distance_m":
            nearest_distance,

        "nearby_observed_road_count":
            source_count,
    })


propagated_df = pd.DataFrame(
    aggregated_rows
)


print(
    f"Roads receiving propagated risk : "
    f"{len(propagated_df):,}"
)


# ============================================================
# 8. BUILD FINAL RISK LAYER
# ============================================================

print("\n[8/9] Building final risk layer...")


final_records = []


# ------------------------------------------------------------
# OBSERVED ROADS
# ------------------------------------------------------------

for _, row in risk_gdf[
    risk_gdf["observed"]
].iterrows():

    final_records.append({

        "osm_u": row["osm_u"],
        "osm_v": row["osm_v"],
        "osm_key": row["osm_key"],

        "historical_risk":
            safe_float(
                row["historical_risk"]
            ),

        "traffic_risk":
            safe_float(
                row["traffic_risk"]
            ),

        "weather_risk":
            safe_float(
                row["weather_risk"]
            ),

        "dynamic_risk":
            safe_float(
                row["dynamic_risk"]
            ),

        "risk_source":
            "observed",

        "risk_confidence":
            "HIGH",

        "nearest_observed_distance_m":
            0.0,

        "nearby_observed_road_count":
            1,

        "road_closure":
            row["road_closure"],
    })


# ------------------------------------------------------------
# PROPAGATED ROADS
# ------------------------------------------------------------

propagated_lookup = {
    (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"]),
    ): row
    for _, row in propagated_df.iterrows()
}


for _, row in risk_gdf[
    ~risk_gdf["observed"]
].iterrows():

    road_id = (
        row["osm_u"],
        row["osm_v"],
        row["osm_key"],
    )

    propagated = propagated_lookup.get(
        road_id
    )

    if propagated is None:

        # No observed road within 500 m.
        final_records.append({

            "osm_u": row["osm_u"],
            "osm_v": row["osm_v"],
            "osm_key": row["osm_key"],

            "historical_risk":
                BASELINE_HISTORICAL_RISK,

            "traffic_risk":
                BASELINE_TRAFFIC_RISK,

            "weather_risk":
                BASELINE_WEATHER_RISK,

            "dynamic_risk":
                0.50
                * BASELINE_HISTORICAL_RISK
                + 0.30
                * BASELINE_TRAFFIC_RISK
                + 0.20
                * BASELINE_WEATHER_RISK,

            "risk_source":
                "baseline_no_observation",

            "risk_confidence":
                "LOW",

            "nearest_observed_distance_m":
                np.nan,

            "nearby_observed_road_count":
                0,

            "road_closure":
                row["road_closure"],
        })

    else:

        final_records.append({

            "osm_u": row["osm_u"],
            "osm_v": row["osm_v"],
            "osm_key": row["osm_key"],

            "historical_risk":
                safe_float(
                    propagated[
                        "propagated_historical_risk"
                    ]
                ),

            "traffic_risk":
                safe_float(
                    propagated[
                        "propagated_traffic_risk"
                    ]
                ),

            "weather_risk":
                safe_float(
                    propagated[
                        "propagated_weather_risk"
                    ]
                ),

            "dynamic_risk":
                safe_float(
                    propagated[
                        "propagated_dynamic_risk"
                    ]
                ),

            "risk_source":
                "spatial_propagated",

            "risk_confidence":
                "MEDIUM",

            "nearest_observed_distance_m":
                safe_float(
                    propagated[
                        "nearest_observed_distance_m"
                    ]
                ),

            "nearby_observed_road_count":
                int(
                    propagated[
                        "nearby_observed_road_count"
                    ]
                ),

            "road_closure":
                row["road_closure"],
        })


final_df = pd.DataFrame(
    final_records
)


# ============================================================
# CLOSED ROADS
# ============================================================

final_df.loc[
    final_df["road_closure"],
    "dynamic_risk"
] = 100.0


final_df.loc[
    final_df["road_closure"],
    "risk_source"
] = "closed"


final_df.loc[
    final_df["road_closure"],
    "risk_confidence"
] = "HIGH"


# ============================================================
# RISK CATEGORIES
# ============================================================

def classify_risk(row):

    if row["road_closure"]:
        return "CLOSED"

    risk = float(
        row["dynamic_risk"]
    )

    if risk < 35:
        return "LOW"

    elif risk < 60:
        return "MEDIUM"

    else:
        return "HIGH"


final_df["risk_category"] = (
    final_df.apply(
        classify_risk,
        axis=1
    )
)


# ============================================================
# SAVE CSV
# ============================================================

final_df.to_csv(
    OUTPUT_CSV_PATH,
    index=False
)

print(
    f"\nSaved risk CSV:\n"
    f"{OUTPUT_CSV_PATH}"
)


# ============================================================
# UPDATE GRAPH
# ============================================================

print("\nUpdating routing graph attributes...")


risk_lookup = {
    (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"]),
    ): row
    for _, row in final_df.iterrows()
}


updated_edges = 0


for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    road_id = (
        str(u),
        str(v),
        str(key),
    )

    risk = risk_lookup.get(
        road_id
    )

    if risk is None:
        continue

    data["historical_risk"] = float(
        risk["historical_risk"]
    )

    data["traffic_risk"] = float(
        risk["traffic_risk"]
    )

    data["weather_risk"] = float(
        risk["weather_risk"]
    )

    data["dynamic_risk"] = float(
        risk["dynamic_risk"]
    )

    data["risk_source"] = str(
        risk["risk_source"]
    )

    data["risk_confidence"] = str(
        risk["risk_confidence"]
    )

    data["risk_category"] = str(
        risk["risk_category"]
    )

    data["nearest_observed_distance_m"] = (
        safe_float(
            risk[
                "nearest_observed_distance_m"
            ]
        )
    )

    data["nearby_observed_road_count"] = int(
        risk[
            "nearby_observed_road_count"
        ]
    )

    updated_edges += 1


# ============================================================
# CLOSED EDGES = INFINITE ROUTING WEIGHT
# ============================================================

for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    if parse_bool(
        data.get("road_closure")
    ):

        data["routing_weight"] = float(
            "inf"
        )

    else:

        travel_time = safe_float(
            data.get(
                "travel_time",
                0
            )
        )

        dynamic_risk = safe_float(
            data.get(
                "dynamic_risk",
                5
            )
        )

        if travel_time <= 0:

            length = safe_float(
                data.get(
                    "length",
                    0
                )
            )

            travel_time = max(
                length / 13.89,
                1.0
            )

        data["routing_weight"] = (
            travel_time
            * (
                1
                + 0.75
                * dynamic_risk
                / 100
            )
        )


G.graph[
    "risk_propagation_distance_m"
] = MAX_PROPAGATION_DISTANCE_M

G.graph[
    "risk_propagation_method"
] = "inverse_distance_weighted"

G.graph[
    "risk_distance_power"
] = DISTANCE_POWER


nx.write_graphml(
    G,
    OUTPUT_GRAPH_PATH
)


# ============================================================
# FINAL STATISTICS
# ============================================================

print("\n" + "=" * 70)
print("SPATIAL RISK PROPAGATION SUMMARY")
print("=" * 70)

print(
    f"Total graph edges        : "
    f"{len(G.edges):,}"
)

print(
    f"Updated risk edges       : "
    f"{updated_edges:,}"
)

print(
    f"Observed roads           : "
    f"{(
        final_df['risk_source'] == 'observed'
    ).sum():,}"
)

print(
    f"Propagated roads         : "
    f"{(
        final_df['risk_source']
        == 'spatial_propagated'
    ).sum():,}"
)

print(
    f"Baseline roads           : "
    f"{(
        final_df['risk_source']
        == 'baseline_no_observation'
    ).sum():,}"
)

print(
    f"Closed roads             : "
    f"{(
        final_df['risk_source']
        == 'closed'
    ).sum():,}"
)

print("\nRisk categories:")

print(
    final_df[
        "risk_category"
    ].value_counts()
    .to_string()
)

print("\nDynamic risk statistics:")

print(
    final_df[
        "dynamic_risk"
    ].describe()
    .to_string()
)

print(
    "\nSaved graph:\n"
    f"{OUTPUT_GRAPH_PATH}"
)

print("=" * 70)
print("STEP 30 COMPLETE")
print("=" * 70)
