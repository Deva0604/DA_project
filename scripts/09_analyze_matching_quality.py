import pandas as pd

FILE = "data/processed/test_accident_road_matching_v2.csv"

df = pd.read_csv(FILE)

print("=" * 70)
print("SAFEROUTE - MATCHING QUALITY ANALYSIS")
print("=" * 70)

# ---------------------------------------------------------
# Distance groups
# ---------------------------------------------------------

bins = [-1, 10, 25, 50, 100, 250, 500, 1000, 2000, float("inf")]

labels = [
    "0-10m",
    "10-25m",
    "25-50m",
    "50-100m",
    "100-250m",
    "250-500m",
    "500m-1km",
    "1-2km",
    ">2km"
]

df["distance_group"] = pd.cut(
    df["distance_to_road_m"],
    bins=bins,
    labels=labels
)

print("\nDistance distribution:")
print(
    df["distance_group"]
    .value_counts()
    .reindex(labels)
    .fillna(0)
)

# ---------------------------------------------------------
# Percentage
# ---------------------------------------------------------

print("\nPercentage:")
print(
    (
        df["distance_group"]
        .value_counts(normalize=True)
        .reindex(labels)
        .fillna(0)
        * 100
    ).round(2)
)

# ---------------------------------------------------------
# Worst matches
# ---------------------------------------------------------

print("\nWorst 20 matches:")

columns = [
    "accident_id",
    "latitude",
    "longitude",
    "accident_severity",
    "road_type",
    "highway",
    "name",
    "distance_to_road_m"
]

print(
    df.sort_values(
        "distance_to_road_m",
        ascending=False
    )[columns]
    .head(20)
    .to_string(index=False)
)

# ---------------------------------------------------------
# Severity vs distance
# ---------------------------------------------------------

print("\nDistance by accident severity:")

print(
    df.groupby("accident_severity", observed=True)[
        "distance_to_road_m"
    ].agg(
        ["count", "mean", "median", "min", "max"]
    )
)

# ---------------------------------------------------------
# Save sorted diagnostic file
# ---------------------------------------------------------

output = "data/processed/matching_quality_report.csv"

df.sort_values(
    "distance_to_road_m",
    ascending=False
).to_csv(
    output,
    index=False
)

print("\nSaved:")
print(output)