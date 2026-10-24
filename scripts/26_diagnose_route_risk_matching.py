import pandas as pd
import osmnx as ox


GRAPH_FILE = "data/raw/osm/saferoute_study_area.graphml"
RISK_FILE = "data/processed/dynamic_road_risk.csv"


print("=" * 70)
print("SAFEROUTE - DIAGNOSE ROUTE RISK MATCHING")
print("=" * 70)


# ============================================================
# 1. LOAD
# ============================================================

print("\n[1/5] Loading graph and risk data...")

G = ox.load_graphml(GRAPH_FILE)

risk_df = pd.read_csv(RISK_FILE)

print(f"Graph nodes : {len(G.nodes):,}")
print(f"Graph edges : {len(G.edges):,}")
print(f"Risk rows   : {len(risk_df):,}")


# ============================================================
# 2. BUILD GRAPH EDGE SETS
# ============================================================

print("\n[2/5] Building graph edge indexes...")

exact_edges = set()

directed_pairs = set()
undirected_pairs = set()


for u, v, k in G.edges(
    keys=True
):

    u = str(u)
    v = str(v)
    k = str(k)

    exact_edges.add(
        (u, v, k)
    )

    directed_pairs.add(
        (u, v)
    )

    undirected_pairs.add(
        tuple(
            sorted(
                [u, v]
            )
        )
    )


print(
    f"Exact graph edges     : "
    f"{len(exact_edges):,}"
)

print(
    f"Directed node pairs   : "
    f"{len(directed_pairs):,}"
)

print(
    f"Undirected node pairs : "
    f"{len(undirected_pairs):,}"
)


# ============================================================
# 3. TEST RISK MATCHES
# ============================================================

print("\n[3/5] Testing risk records...")


exact_matches = 0
reverse_matches = 0
pair_matches = 0
no_matches = 0


for _, row in risk_df.iterrows():

    u = str(row["osm_u"])
    v = str(row["osm_v"])
    k = str(row["osm_key"])


    # Exact direction + key
    if (u, v, k) in exact_edges:

        exact_matches += 1
        continue


    # Reverse direction
    if (v, u, k) in exact_edges:

        reverse_matches += 1
        continue


    # Same directed/undirected physical pair
    if (u, v) in directed_pairs:

        pair_matches += 1
        continue


    if tuple(sorted([u, v])) in undirected_pairs:

        pair_matches += 1
        continue


    no_matches += 1


print("\nRisk matching results:")

print(
    f"Exact matches     : {exact_matches:,}"
)

print(
    f"Reverse matches   : {reverse_matches:,}"
)

print(
    f"Pair matches      : {pair_matches:,}"
)

print(
    f"No matches        : {no_matches:,}"
)


# ============================================================
# 4. PERCENTAGES
# ============================================================

total = len(risk_df)


print("\nMatch percentages:")

if total > 0:

    print(
        f"Exact   : "
        f"{exact_matches / total * 100:.2f}%"
    )

    print(
        f"Reverse : "
        f"{reverse_matches / total * 100:.2f}%"
    )

    print(
        f"Pair    : "
        f"{pair_matches / total * 100:.2f}%"
    )

    print(
        f"None    : "
        f"{no_matches / total * 100:.2f}%"
    )


# ============================================================
# 5. SAMPLE RISK RECORDS
# ============================================================

print("\n[4/5] Sample risk records...")

print(
    risk_df[
        [
            "osm_u",
            "osm_v",
            "osm_key",
            "road_name",
            "historical_risk",
            "traffic_risk",
            "dynamic_risk",
            "road_closure",
        ]
    ]
    .head(20)
    .to_string(index=False)
)


print("\n[5/5] Diagnosis complete.")

print("\n" + "=" * 70)
print("ROUTE RISK MATCHING DIAGNOSIS COMPLETE")
print("=" * 70)
