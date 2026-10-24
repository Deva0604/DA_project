import os
import pandas as pd
import networkx as nx
import osmnx as ox


GRAPH_FILE = "data/raw/osm/saferoute_study_area.graphml"
RISK_FILE = "data/processed/dynamic_road_risk.csv"
OUTPUT_FILE = "data/processed/saferoute_routing_graph.graphml"


print("=" * 70)
print("SAFEROUTE - PREPARE ROUTING GRAPH")
print("=" * 70)


# ============================================================
# 1. LOAD OSM GRAPH
# ============================================================

print("\n[1/7] Loading OSM road graph...")

if not os.path.exists(GRAPH_FILE):
    raise FileNotFoundError(
        f"Graph not found: {GRAPH_FILE}"
    )

G = ox.load_graphml(GRAPH_FILE)

print(f"Nodes : {len(G.nodes):,}")
print(f"Edges : {len(G.edges):,}")


# ============================================================
# 2. LOAD DYNAMIC RISK
# ============================================================

print("\n[2/7] Loading dynamic road risk...")

risk_df = pd.read_csv(RISK_FILE)

print(f"Risk records: {len(risk_df):,}")


# ============================================================
# 3. PREPARE OSM EDGE IDENTIFIERS
# ============================================================

print("\n[3/7] Preparing edge identifiers...")

# GraphML can store node IDs as strings.
# Convert them to strings consistently.

risk_df["osm_u"] = risk_df["osm_u"].astype(str)
risk_df["osm_v"] = risk_df["osm_v"].astype(str)
risk_df["osm_key"] = risk_df["osm_key"].astype(str)


# Create lookup dictionary

risk_lookup = {}

for _, row in risk_df.iterrows():

    key = (
        str(row["osm_u"]),
        str(row["osm_v"]),
        str(row["osm_key"])
    )

    risk_lookup[key] = row


print(f"Risk lookup entries: {len(risk_lookup):,}")


# ============================================================
# 4. ATTACH RISK TO GRAPH EDGES
# ============================================================

print("\n[4/7] Attaching risk to OSM edges...")


matched_edges = 0
unmatched_edges = 0
closed_edges = 0


for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    key = (
        str(u),
        str(v),
        str(k)
    )

    risk = risk_lookup.get(key)

    if risk is not None:

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

        data["road_closure"] = bool(
            risk["road_closure"]
        )

        data["accident_count"] = int(
            risk["accident_count"]
        )

        data["traffic_status"] = str(
            risk["traffic_status_calculated"]
        )

        data["weather_status"] = str(
            risk["weather_status_calculated"]
        )

        data["dynamic_risk_category"] = str(
            risk["dynamic_risk_category"]
        )

        data["risk_source"] = "observed"

        matched_edges += 1

        if data["road_closure"]:
            closed_edges += 1

    else:

        # ----------------------------------------------------
        # Roads without historical accident observations
        # ----------------------------------------------------
        #
        # IMPORTANT:
        # Do not remove these roads.
        #
        # They remain available for routing and receive
        # a neutral baseline risk.
        # ----------------------------------------------------

        data["historical_risk"] = 0.0
        data["traffic_risk"] = 0.0
        data["weather_risk"] = 0.0
        data["dynamic_risk"] = 0.0

        data["road_closure"] = False

        data["accident_count"] = 0

        data["traffic_status"] = "UNKNOWN"
        data["weather_status"] = "UNKNOWN"
        data["dynamic_risk_category"] = "LOW"

        data["risk_source"] = "no_observation"

        unmatched_edges += 1


print("\nEdge matching:")

print(f"Matched edges   : {matched_edges:,}")
print(f"Unmatched edges : {unmatched_edges:,}")
print(f"Closed edges    : {closed_edges:,}")


# ============================================================
# 5. CREATE ROUTING WEIGHTS
# ============================================================

print("\n[5/7] Creating routing weights...")


# ------------------------------------------------------------
# Distance weight
# ------------------------------------------------------------

for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    length = float(
        data.get("length", 1.0)
    )

    dynamic_risk = float(
        data.get("dynamic_risk", 0.0)
    )

    road_closure = bool(
        data.get("road_closure", False)
    )


    # --------------------------------------------------------
    # Fastest-route weight
    # --------------------------------------------------------
    #
    # OSMnx graph normally contains travel-time when
    # speed information is available. Otherwise we use
    # distance as the fallback.
    # --------------------------------------------------------

    travel_time = data.get("travel_time")

    if travel_time is None:
        travel_time = length / 13.89
        # 13.89 m/s ≈ 50 km/h baseline


    travel_time = float(travel_time)

    data["routing_travel_time"] = travel_time


    # --------------------------------------------------------
    # Safest-route weight
    # --------------------------------------------------------
    #
    # Risk is combined with distance.
    #
    # We use:
    #
    # distance × (1 + risk/100)
    #
    # This prevents a very long route from automatically
    # becoming the safest simply because it has low risk.
    # --------------------------------------------------------

    data["safety_weight"] = (
        length
        * (1.0 + dynamic_risk / 100.0)
    )


    # --------------------------------------------------------
    # Balanced-route weight
    # --------------------------------------------------------
    #
    # 60% travel-time importance
    # 40% safety importance
    #
    # Both components are normalized later during route
    # comparison.
    # --------------------------------------------------------

    data["risk_penalty"] = (
        1.0 + dynamic_risk / 100.0
    )


    # --------------------------------------------------------
    # Closed roads
    # --------------------------------------------------------

    if road_closure:

        data["routing_travel_time"] = float("inf")
        data["safety_weight"] = float("inf")


# ============================================================
# 6. GRAPH VALIDATION
# ============================================================

print("\n[6/7] Validating routing graph...")


required_graph_attributes = [
    "routing_travel_time",
    "safety_weight",
    "dynamic_risk",
    "historical_risk",
    "traffic_risk",
    "weather_risk",
    "road_closure",
]


missing_attribute_count = 0


for u, v, k, data in G.edges(
    keys=True,
    data=True
):

    for attribute in required_graph_attributes:

        if attribute not in data:
            missing_attribute_count += 1


print(
    f"Missing edge attributes: "
    f"{missing_attribute_count}"
)


# ============================================================
# 7. SAVE GRAPH
# ============================================================

print("\n[7/7] Saving routing graph...")


ox.save_graphml(
    G,
    filepath=OUTPUT_FILE
)


print("\n" + "=" * 70)
print("ROUTING GRAPH CREATED")
print("=" * 70)

print(f"\nNodes : {len(G.nodes):,}")
print(f"Edges : {len(G.edges):,}")

print(f"\nMatched risk edges   : {matched_edges:,}")
print(f"Unmatched risk edges : {unmatched_edges:,}")
print(f"Closed edges         : {closed_edges:,}")

print(f"\nSaved:")
print(OUTPUT_FILE)

print("\n" + "=" * 70)
print("DONE")
print("=" * 70)
