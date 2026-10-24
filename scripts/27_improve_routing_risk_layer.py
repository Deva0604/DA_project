import os
import pandas as pd
import networkx as nx
import osmnx as ox


GRAPH_FILE = (
    "data/raw/osm/"
    "saferoute_study_area.graphml"
)

RISK_FILE = (
    "data/processed/"
    "dynamic_road_risk.csv"
)

OUTPUT_FILE = (
    "data/processed/"
    "saferoute_routing_graph_v2.graphml"
)


print("=" * 70)
print("SAFEROUTE - IMPROVE ROUTING RISK LAYER")
print("=" * 70)


# ============================================================
# CONFIGURATION
# ============================================================

# Important:
#
# A road with no accident observation is NOT considered
# perfectly safe.
#
# We give unobserved roads a conservative baseline risk.
#
# This is an engineering/prototype assumption and should
# later be replaced by an ML/calibrated model.

BASELINE_HISTORICAL_RISK = 10.0
BASELINE_TRAFFIC_RISK = 0.0
BASELINE_WEATHER_RISK = 0.0


# ============================================================
# 1. LOAD GRAPH
# ============================================================

print("\n[1/8] Loading OSM graph...")

if not os.path.exists(GRAPH_FILE):
    raise FileNotFoundError(GRAPH_FILE)

G = ox.load_graphml(GRAPH_FILE)

print(f"Nodes : {len(G.nodes):,}")
print(f"Edges : {len(G.edges):,}")


# ============================================================
# 2. LOAD RISK DATA
# ============================================================

print("\n[2/8] Loading dynamic risk data...")

if not os.path.exists(RISK_FILE):
    raise FileNotFoundError(RISK_FILE)

risk_df = pd.read_csv(RISK_FILE)

print(f"Risk records: {len(risk_df):,}")


# ============================================================
# 3. BUILD EXACT EDGE LOOKUP
# ============================================================

print("\n[3/8] Building risk lookup...")

risk_lookup = {}

for _, row in risk_df.iterrows():

    key = (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"])
    )

    risk_lookup[key] = row


print(
    f"Risk lookup entries: "
    f"{len(risk_lookup):,}"
)


# ============================================================
# 4. ATTACH OBSERVED RISK
# ============================================================

print("\n[4/8] Attaching observed risk...")


observed_edges = 0
unobserved_edges = 0
closed_edges = 0


for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    lookup_key = (
        str(u),
        str(v),
        str(k)
    )

    row = risk_lookup.get(
        lookup_key
    )


    if row is not None:

        # ----------------------------------------------------
        # OBSERVED EDGE
        # ----------------------------------------------------

        data["historical_risk"] = float(
            row["historical_risk"]
        )

        data["traffic_risk"] = float(
            row["traffic_risk"]
        )

        data["weather_risk"] = float(
            row["weather_risk"]
        )

        data["dynamic_risk"] = float(
            row["dynamic_risk"]
        )

        data["road_closure"] = (
            str(row["road_closure"]).lower()
            in ["true", "1", "yes"]
        )

        data["accident_count"] = int(
            row["accident_count"]
        )

        data["risk_source"] = "observed"

        data["risk_confidence"] = "HIGH"

        observed_edges += 1

        if data["road_closure"]:
            closed_edges += 1


    else:

        # ----------------------------------------------------
        # UNOBSERVED EDGE
        # ----------------------------------------------------
        #
        # IMPORTANT:
        #
        # No observation does NOT mean zero risk.
        #
        # We use a small baseline historical risk.
        # Live traffic/weather remain unknown.
        # ----------------------------------------------------

        data["historical_risk"] = (
            BASELINE_HISTORICAL_RISK
        )

        data["traffic_risk"] = (
            BASELINE_TRAFFIC_RISK
        )

        data["weather_risk"] = (
            BASELINE_WEATHER_RISK
        )

        data["dynamic_risk"] = (
            BASELINE_HISTORICAL_RISK
            * 0.50
            + BASELINE_TRAFFIC_RISK
            * 0.30
            + BASELINE_WEATHER_RISK
            * 0.20
        )

        data["road_closure"] = False

        data["accident_count"] = 0

        data["risk_source"] = (
            "baseline_no_observation"
        )

        data["risk_confidence"] = "LOW"

        unobserved_edges += 1


# ============================================================
# 5. CREATE ROUTING WEIGHTS
# ============================================================

print("\n[5/8] Creating routing weights...")


for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    length = float(
        data.get(
            "length",
            1.0
        )
    )


    dynamic_risk = float(
        data.get(
            "dynamic_risk",
            BASELINE_HISTORICAL_RISK
            * 0.50
        )
    )


    road_closure = bool(
        data.get(
            "road_closure",
            False
        )
    )


    # --------------------------------------------------------
    # Travel time
    # --------------------------------------------------------

    travel_time = data.get(
        "travel_time"
    )


    if travel_time is None:

        # Approximate fallback:
        #
        # 50 km/h = 13.89 m/s

        travel_time = (
            length / 13.89
        )


    travel_time = float(
        travel_time
    )


    data["routing_travel_time"] = (
        travel_time
    )


    # --------------------------------------------------------
    # Safety weight
    # --------------------------------------------------------

    data["safety_weight"] = (
        length
        * (
            1
            + dynamic_risk / 100
        )
    )


    # --------------------------------------------------------
    # Balanced weight
    # --------------------------------------------------------

    data["balanced_weight"] = (
        travel_time
        * (
            1
            + 0.40
            * dynamic_risk
            / 100
        )
    )


    # --------------------------------------------------------
    # Closed roads
    # --------------------------------------------------------

    if road_closure:

        data["routing_travel_time"] = (
            float("inf")
        )

        data["safety_weight"] = (
            float("inf")
        )

        data["balanced_weight"] = (
            float("inf")
        )


# ============================================================
# 6. CREATE RISK CATEGORIES
# ============================================================

print("\n[6/8] Creating risk categories...")


for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    if data.get(
        "road_closure",
        False
    ):

        data["dynamic_risk_category"] = (
            "CLOSED"
        )

        continue


    risk = float(
        data.get(
            "dynamic_risk",
            0
        )
    )


    if risk < 20:

        category = "LOW"

    elif risk < 40:

        category = "MEDIUM"

    elif risk < 70:

        category = "HIGH"

    else:

        category = "SEVERE"


    data["dynamic_risk_category"] = (
        category
    )


# ============================================================
# 7. VALIDATION
# ============================================================

print("\n[7/8] Validating routing graph...")


required_attributes = [
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "dynamic_risk",
    "road_closure",
    "risk_source",
    "risk_confidence",
    "routing_travel_time",
    "safety_weight",
    "balanced_weight",
    "dynamic_risk_category",
]


missing = 0


for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    for attribute in required_attributes:

        if attribute not in data:

            missing += 1


print(
    f"Missing attributes: {missing}"
)


# ============================================================
# 8. SAVE
# ============================================================

print("\n[8/8] Saving improved routing graph...")


ox.save_graphml(
    G,
    filepath=OUTPUT_FILE
)


print("\n" + "=" * 70)
print("IMPROVED ROUTING GRAPH CREATED")
print("=" * 70)

print(
    f"\nNodes              : "
    f"{len(G.nodes):,}"
)

print(
    f"Edges              : "
    f"{len(G.edges):,}"
)

print(
    f"Observed edges     : "
    f"{observed_edges:,}"
)

print(
    f"Unobserved edges   : "
    f"{unobserved_edges:,}"
)

print(
    f"Closed edges       : "
    f"{closed_edges:,}"
)

print(
    f"Missing attributes : "
    f"{missing}"
)

print(
    f"\nBaseline historical risk: "
    f"{BASELINE_HISTORICAL_RISK}"
)

print(
    f"\nSaved:"
)

print(
    OUTPUT_FILE
)

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
