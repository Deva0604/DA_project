import pandas as pd


# =========================================================
# SAFEROUTE
# Build Road-Level Historical Accident Risk
# =========================================================

INPUT_FILE = (
    "data/processed/"
    "accident_road_matches.csv"
)

OUTPUT_MATCHED = (
    "data/processed/"
    "accepted_accident_road_matches_v2.csv"
)

OUTPUT_RISK = (
    "data/processed/"
    "road_accident_risk.csv"
)


print("=" * 70)
print("SAFEROUTE - ROAD ACCIDENT RISK ENGINE")
print("=" * 70)


# =========================================================
# 1. LOAD DATA
# =========================================================

print("\n[1/7] Loading accident-road matches...")

df = pd.read_csv(INPUT_FILE)

print(f"Total records: {len(df)}")


# =========================================================
# 2. CREATE SPATIAL CONFIDENCE
# =========================================================

print("\n[2/7] Calculating spatial confidence...")


def calculate_confidence(distance):

    if pd.isna(distance):
        return 0.0

    if distance <= 50:
        return 1.00

    elif distance <= 100:
        return 0.75

    elif distance <= 250:
        return 0.40

    else:
        return 0.00


df["match_confidence"] = (
    df["distance_to_road_m"]
    .apply(calculate_confidence)
)


# =========================================================
# 3. MATCH STATUS
# =========================================================

df["match_accepted"] = (
    df["match_confidence"] > 0
)


accepted = df[
    df["match_accepted"]
].copy()


print("\nMatch counts:")

print(
    df["match_accepted"]
    .value_counts()
)


# =========================================================
# 4. MATCH QUALITY
# =========================================================

def calculate_quality(distance):

    if pd.isna(distance):
        return "REJECTED"

    if distance <= 50:
        return "HIGH"

    elif distance <= 100:
        return "MEDIUM"

    elif distance <= 250:
        return "LOW"

    return "REJECTED"


accepted["match_quality"] = (
    accepted["distance_to_road_m"]
    .apply(calculate_quality)
)


# =========================================================
# 5. EXPLICITLY RENAME OSM ATTRIBUTES
# =========================================================

print("\n[3/7] Preparing OSM road attributes...")


# Accident dataset's lanes_left is NOT used
# OSM's lanes_right is the road-network value.

accepted = accepted.rename(
    columns={
        "u": "osm_u",
        "v": "osm_v",
        "key": "osm_key",
        "osmid": "osm_id",
        "highway": "osm_highway",
        "name": "osm_name",
        "oneway": "osm_oneway",
        "length": "osm_length_m",
        "lanes_right": "osm_lanes",
        "maxspeed": "osm_maxspeed",
        "junction": "osm_junction",
        "service": "osm_service"
    }
)


# =========================================================
# 6. SAVE ACCEPTED ACCIDENT-ROAD DATA
# =========================================================

print("\n[4/7] Saving accepted accident-road data...")


accepted.to_csv(
    OUTPUT_MATCHED,
    index=False
)


print(
    f"Accepted records: {len(accepted)}"
)

print(
    f"Saved: {OUTPUT_MATCHED}"
)


# =========================================================
# 7. CREATE SEVERITY FEATURES
# =========================================================

print("\n[5/7] Creating severity features...")


accepted["is_fatal"] = (
    accepted["accident_severity"]
    .astype(str)
    .str.lower()
    .eq("fatal")
    .astype(int)
)


accepted["is_major"] = (
    accepted["accident_severity"]
    .astype(str)
    .str.lower()
    .eq("major")
    .astype(int)
)


accepted["is_minor"] = (
    accepted["accident_severity"]
    .astype(str)
    .str.lower()
    .eq("minor")
    .astype(int)
)


# =========================================================
# SEVERITY WEIGHTS
# =========================================================

severity_weight = {
    "minor": 1.0,
    "major": 2.0,
    "fatal": 4.0
}


accepted["severity_weight"] = (
    accepted["accident_severity"]
    .astype(str)
    .str.lower()
    .map(severity_weight)
    .fillna(0)
)


# =========================================================
# SPATIAL + SEVERITY CONTRIBUTION
# =========================================================

accepted["weighted_risk_contribution"] = (
    accepted["match_confidence"]
    * accepted["severity_weight"]
)


# =========================================================
# 8. GROUP BY ACTUAL OSM ROAD SEGMENT
# =========================================================

print("\n[6/7] Aggregating accidents by OSM road...")


group_columns = [
    "osm_u",
    "osm_v",
    "osm_key"
]


road_risk = (
    accepted
    .groupby(
        group_columns,
        as_index=False
    )
    .agg(

        # -------------------------------------------------
        # Accident counts
        # -------------------------------------------------

        accident_count=(
            "accident_id",
            "count"
        ),

        weighted_accident_count=(
            "match_confidence",
            "sum"
        ),

        # -------------------------------------------------
        # Severity
        # -------------------------------------------------

        fatal_count=(
            "is_fatal",
            "sum"
        ),

        major_count=(
            "is_major",
            "sum"
        ),

        minor_count=(
            "is_minor",
            "sum"
        ),

        severity_risk=(
            "weighted_risk_contribution",
            "sum"
        ),

        # -------------------------------------------------
        # Casualties
        # -------------------------------------------------

        total_casualties=(
            "casualties",
            "sum"
        ),

        # -------------------------------------------------
        # Spatial quality
        # -------------------------------------------------

        avg_match_distance_m=(
            "distance_to_road_m",
            "mean"
        ),

        avg_match_confidence=(
            "match_confidence",
            "mean"
        ),

        # -------------------------------------------------
        # OSM road attributes
        # -------------------------------------------------

        road_name=(
            "osm_name",
            "first"
        ),

        highway=(
            "osm_highway",
            "first"
        ),

        road_length_m=(
            "osm_length_m",
            "first"
        ),

        osm_lanes=(
            "osm_lanes",
            "first"
        ),

        maxspeed=(
            "osm_maxspeed",
            "first"
        ),

        oneway=(
            "osm_oneway",
            "first"
        ),

        junction=(
            "osm_junction",
            "first"
        ),

        service=(
            "osm_service",
            "first"
        )
    )
)


# =========================================================
# 9. HISTORICAL RISK SCORE
# =========================================================

print("\nCalculating historical risk...")


max_risk = (
    road_risk["severity_risk"].max()
)


if max_risk > 0:

    road_risk["historical_risk"] = (
        road_risk["severity_risk"]
        / max_risk
        * 100
    )

else:

    road_risk["historical_risk"] = 0.0


# =========================================================
# 10. RISK CATEGORY
# =========================================================

def risk_category(score):

    if score >= 70:
        return "HIGH"

    elif score >= 40:
        return "MEDIUM"

    else:
        return "LOW"


road_risk["risk_category"] = (
    road_risk["historical_risk"]
    .apply(risk_category)
)


# =========================================================
# 11. SORT BY RISK
# =========================================================

road_risk = (
    road_risk
    .sort_values(
        "historical_risk",
        ascending=False
    )
    .reset_index(drop=True)
)


# =========================================================
# 12. SAVE FINAL ROAD DATASET
# =========================================================

print("\n[7/7] Saving road risk dataset...")


road_risk.to_csv(
    OUTPUT_RISK,
    index=False
)


# =========================================================
# FINAL REPORT
# =========================================================

print("\n" + "=" * 70)
print("ROAD RISK DATASET CREATED SUCCESSFULLY")
print("=" * 70)


print(
    f"\nAccepted accident observations : "
    f"{len(accepted)}"
)


print(
    f"Road segments with accidents   : "
    f"{len(road_risk)}"
)


print("\nRisk categories:")

print(
    road_risk[
        "risk_category"
    ].value_counts()
)


print("\nDistance statistics for accepted matches:")

print(
    accepted[
        "distance_to_road_m"
    ].describe()
)


print("\nTop 20 highest-risk road segments:")


display_columns = [
    "osm_u",
    "osm_v",
    "osm_key",
    "road_name",
    "highway",
    "accident_count",
    "fatal_count",
    "major_count",
    "minor_count",
    "total_casualties",
    "avg_match_distance_m",
    "historical_risk",
    "risk_category"
]


print(
    road_risk[
        display_columns
    ]
    .head(20)
    .to_string(index=False)
)


print("\nSaved final dataset:")

print(
    OUTPUT_RISK
)


print("\nDone.")