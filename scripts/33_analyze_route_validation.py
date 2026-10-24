import os
import pandas as pd
import numpy as np


# ============================================================
# SAFEROUTE - ROUTE VALIDATION ANALYSIS
# STEP 33
# ============================================================

INPUT_FILE = (
    "data/processed/"
    "route_validation_results.csv"
)

SUMMARY_FILE = (
    "data/processed/"
    "route_validation_summary.csv"
)

TEST_SUMMARY_FILE = (
    "data/processed/"
    "route_validation_test_summary.csv"
)


print("=" * 75)
print("SAFEROUTE - ROUTE VALIDATION ANALYSIS")
print("=" * 75)


# ============================================================
# 1. CHECK INPUT
# ============================================================

print("\n[1/7] Checking validation dataset...")


if not os.path.exists(INPUT_FILE):

    raise FileNotFoundError(
        f"Validation file not found: {INPUT_FILE}"
    )


df = pd.read_csv(
    INPUT_FILE
)


print(
    f"Rows    : {len(df):,}"
)

print(
    f"Columns : {len(df.columns):,}"
)


if df.empty:

    raise ValueError(
        "Validation dataset is empty."
    )


# ============================================================
# 2. BASIC DATA QUALITY
# ============================================================

print(
    "\n[2/7] Checking data quality..."
)


print(
    f"Missing values: "
    f"{df.isna().sum().sum():,}"
)


print(
    f"Unique tests : "
    f"{df['test_id'].nunique()}"
)


print(
    f"Unique routes: "
    f"{df['route_id'].nunique()}"
)


expected_tests = 5

expected_routes_per_test = 10

expected_total_routes = (
    expected_tests
    * expected_routes_per_test
)


if len(df) == expected_total_routes:

    print(
        "PASS: Expected 50 validation routes found."
    )

else:

    print(
        "WARNING: Expected 50 routes, "
        f"found {len(df)}."
    )


# ============================================================
# 3. OVERALL ROUTE STATISTICS
# ============================================================

print(
    "\n[3/7] Calculating overall route statistics..."
)


numeric_columns = [

    "distance_km",

    "travel_time_min",

    "avg_historical_risk",

    "avg_traffic_risk",

    "avg_weather_risk",

    "avg_dynamic_risk",

    "total_dynamic_risk",

    "risk_coverage_percent",

    "balanced_score",

]


overall_summary = []


for column in numeric_columns:

    if column not in df.columns:

        continue


    series = pd.to_numeric(
        df[column],
        errors="coerce"
    ).dropna()


    if len(series) == 0:

        continue


    overall_summary.append({

        "metric": column,

        "count": len(series),

        "mean": series.mean(),

        "median": series.median(),

        "minimum": series.min(),

        "maximum": series.max(),

        "std": series.std(),

    })


overall_summary_df = pd.DataFrame(
    overall_summary
)


# ============================================================
# PRINT OVERALL SUMMARY
# ============================================================

print(
    "\nOVERALL ROUTE STATISTICS"
)

print(
    "-" * 75
)


for _, row in overall_summary_df.iterrows():

    print(
        f"{row['metric']:28s} | "
        f"Mean: {row['mean']:8.2f} | "
        f"Median: {row['median']:8.2f} | "
        f"Min: {row['minimum']:8.2f} | "
        f"Max: {row['maximum']:8.2f}"
    )


# ============================================================
# 4. TEST-BY-TEST ANALYSIS
# ============================================================

print(
    "\n[4/7] Analyzing each origin-destination pair..."
)


test_summaries = []


for test_id, group in df.groupby(
    "test_id"
):

    group = group.copy()


    # --------------------------------------------------------
    # Basic values
    # --------------------------------------------------------

    origin = group[
        "origin"
    ].iloc[0]


    destination = group[
        "destination"
    ].iloc[0]


    # --------------------------------------------------------
    # Fastest route
    # --------------------------------------------------------

    fastest_route = group.loc[
        group[
            "travel_time_min"
        ].idxmin()
    ]


    # --------------------------------------------------------
    # Safest route
    # --------------------------------------------------------

    safest_route = group.loc[
        group[
            "avg_dynamic_risk"
        ].idxmin()
    ]


    # --------------------------------------------------------
    # Balanced route
    # --------------------------------------------------------

    balanced_route = group.loc[
        group[
            "balanced_score"
        ].idxmin()
    ]


    # --------------------------------------------------------
    # Best / worst risk
    # --------------------------------------------------------

    minimum_risk = group[
        "avg_dynamic_risk"
    ].min()


    maximum_risk = group[
        "avg_dynamic_risk"
    ].max()


    risk_range = (
        maximum_risk
        - minimum_risk
    )


    # --------------------------------------------------------
    # Best / worst travel time
    # --------------------------------------------------------

    minimum_time = group[
        "travel_time_min"
    ].min()


    maximum_time = group[
        "travel_time_min"
    ].max()


    time_range = (
        maximum_time
        - minimum_time
    )


    # --------------------------------------------------------
    # Safer route time penalty
    # --------------------------------------------------------

    safest_time_penalty_percent = (

        (
            safest_route[
                "travel_time_min"
            ]
            - fastest_route[
                "travel_time_min"
            ]
        )

        / fastest_route[
            "travel_time_min"
        ]

        * 100

    )


    # --------------------------------------------------------
    # Risk improvement
    # --------------------------------------------------------

    risk_improvement_percent = (

        (
            fastest_route[
                "avg_dynamic_risk"
            ]
            - safest_route[
                "avg_dynamic_risk"
            ]
        )

        / max(
            fastest_route[
                "avg_dynamic_risk"
            ],
            0.0001
        )

        * 100

    )


    # --------------------------------------------------------
    # Recommendation differences
    # --------------------------------------------------------

    fastest_id = int(
        fastest_route[
            "route_id"
        ]
    )


    safest_id = int(
        safest_route[
            "route_id"
        ]
    )


    balanced_id = int(
        balanced_route[
            "route_id"
        ]
    )


    test_summaries.append({

        "test_id":
            test_id,

        "origin":
            origin,

        "destination":
            destination,

        "candidate_routes":
            len(group),

        "fastest_route":
            fastest_id,

        "safest_route":
            safest_id,

        "balanced_route":
            balanced_id,

        "fastest_time_min":
            fastest_route[
                "travel_time_min"
            ],

        "safest_time_min":
            safest_route[
                "travel_time_min"
            ],

        "balanced_time_min":
            balanced_route[
                "travel_time_min"
            ],

        "fastest_risk":
            fastest_route[
                "avg_dynamic_risk"
            ],

        "safest_risk":
            safest_route[
                "avg_dynamic_risk"
            ],

        "balanced_risk":
            balanced_route[
                "avg_dynamic_risk"
            ],

        "minimum_risk":
            minimum_risk,

        "maximum_risk":
            maximum_risk,

        "risk_range":
            risk_range,

        "minimum_time_min":
            minimum_time,

        "maximum_time_min":
            maximum_time,

        "time_range_min":
            time_range,

        "safest_time_penalty_percent":
            safest_time_penalty_percent,

        "risk_improvement_percent":
            risk_improvement_percent,

        "average_coverage_percent":
            group[
                "risk_coverage_percent"
            ].mean(),

        "minimum_coverage_percent":
            group[
                "risk_coverage_percent"
            ].min(),

        "maximum_coverage_percent":
            group[
                "risk_coverage_percent"
            ].max(),

        "closed_edges_total":
            group[
                "closed_edges"
            ].sum(),

    })


test_summary_df = pd.DataFrame(
    test_summaries
)


# ============================================================
# PRINT TEST RESULTS
# ============================================================

print(
    "\nTEST-BY-TEST RESULTS"
)

print(
    "-" * 75
)


for _, row in test_summary_df.iterrows():

    print(
        f"\nTest {int(row['test_id'])}: "
        f"{row['origin']} → "
        f"{row['destination']}"
    )


    print(
        f"  Fastest : Route "
        f"{int(row['fastest_route'])} | "
        f"{row['fastest_time_min']:.2f} min | "
        f"Risk {row['fastest_risk']:.2f}"
    )


    print(
        f"  Safest  : Route "
        f"{int(row['safest_route'])} | "
        f"{row['safest_time_min']:.2f} min | "
        f"Risk {row['safest_risk']:.2f}"
    )


    print(
        f"  Balanced: Route "
        f"{int(row['balanced_route'])} | "
        f"{row['balanced_time_min']:.2f} min | "
        f"Risk {row['balanced_risk']:.2f}"
    )


    print(
        f"  Risk range       : "
        f"{row['risk_range']:.2f}"
    )


    print(
        f"  Safer route time "
        f"penalty          : "
        f"{row['safest_time_penalty_percent']:.2f}%"
    )


    print(
        f"  Risk improvement : "
        f"{row['risk_improvement_percent']:.2f}%"
    )


    print(
        f"  Average coverage : "
        f"{row['average_coverage_percent']:.2f}%"
    )


# ============================================================
# 5. RECOMMENDATION ANALYSIS
# ============================================================

print(
    "\n[5/7] Analyzing recommendation behavior..."
)


fastest_routes = (
    test_summary_df[
        "fastest_route"
    ]
)


safest_routes = (
    test_summary_df[
        "safest_route"
    ]
)


balanced_routes = (
    test_summary_df[
        "balanced_route"
    ]
)


fastest_safest_same = (

    test_summary_df[
        "fastest_route"
    ]

    ==

    test_summary_df[
        "safest_route"
    ]

).sum()


fastest_balanced_same = (

    test_summary_df[
        "fastest_route"
    ]

    ==

    test_summary_df[
        "balanced_route"
    ]

).sum()


safest_balanced_same = (

    test_summary_df[
        "safest_route"
    ]

    ==

    test_summary_df[
        "balanced_route"
    ]

).sum()


all_three_same = (

    (
        test_summary_df[
            "fastest_route"
        ]

        ==

        test_summary_df[
            "safest_route"
        ]
    )

    &

    (
        test_summary_df[
            "safest_route"
        ]

        ==

        test_summary_df[
            "balanced_route"
        ]
    )

).sum()


print(
    f"Fastest = Safest   : "
    f"{fastest_safest_same}/"
    f"{len(test_summary_df)}"
)


print(
    f"Fastest = Balanced : "
    f"{fastest_balanced_same}/"
    f"{len(test_summary_df)}"
)


print(
    f"Safest = Balanced  : "
    f"{safest_balanced_same}/"
    f"{len(test_summary_df)}"
)


print(
    f"All three same     : "
    f"{all_three_same}/"
    f"{len(test_summary_df)}"
)


# ============================================================
# RISK DIVERSITY
# ============================================================

average_risk_range = (
    test_summary_df[
        "risk_range"
    ].mean()
)


average_time_range = (
    test_summary_df[
        "time_range_min"
    ].mean()
)


average_coverage = (
    test_summary_df[
        "average_coverage_percent"
    ].mean()
)


average_safest_penalty = (
    test_summary_df[
        "safest_time_penalty_percent"
    ].mean()
)


average_risk_improvement = (
    test_summary_df[
        "risk_improvement_percent"
    ].mean()
)


print(
    "\nROUTE DIVERSITY"
)

print(
    "-" * 75
)


print(
    f"Average risk range : "
    f"{average_risk_range:.2f}"
)


print(
    f"Average time range : "
    f"{average_time_range:.2f} min"
)


print(
    f"Average coverage   : "
    f"{average_coverage:.2f}%"
)


print(
    f"Average safer-time "
    f"penalty           : "
    f"{average_safest_penalty:.2f}%"
)


print(
    f"Average risk "
    f"improvement       : "
    f"{average_risk_improvement:.2f}%"
)


# ============================================================
# 6. CORRELATION ANALYSIS
# ============================================================

print(
    "\n[6/7] Checking time-risk relationship..."
)


correlation = df[
    [
        "travel_time_min",
        "avg_dynamic_risk",
        "distance_km",
    ]
].corr()


print(
    "\nCORRELATION MATRIX"
)

print(
    "-" * 75
)

print(
    correlation.round(3)
)


time_risk_correlation = (
    correlation.loc[
        "travel_time_min",
        "avg_dynamic_risk"
    ]
)


print(
    f"\nTime ↔ Risk correlation: "
    f"{time_risk_correlation:.3f}"
)


# ============================================================
# SAVE SUMMARY
# ============================================================

print(
    "\n[7/7] Saving analysis results..."
)


os.makedirs(
    os.path.dirname(
        SUMMARY_FILE
    ),
    exist_ok=True
)


overall_summary_df.to_csv(
    SUMMARY_FILE,
    index=False
)


test_summary_df.to_csv(
    TEST_SUMMARY_FILE,
    index=False
)


print(
    f"Saved: {SUMMARY_FILE}"
)


print(
    f"Saved: {TEST_SUMMARY_FILE}"
)


# ============================================================
# FINAL INTERPRETATION
# ============================================================

print(
    "\n"
    + "=" * 75
)

print(
    "STEP 33 VALIDATION RESULT"
)

print(
    "=" * 75
)


if len(df) >= 50:

    print(
        "PASS: Multi-route validation dataset "
        "contains the expected number of routes."
    )


else:

    print(
        "WARNING: Validation dataset is smaller "
        "than expected."
    )


if average_coverage >= 80:

    print(
        f"PASS: Average risk coverage is "
        f"{average_coverage:.2f}%."
    )

else:

    print(
        f"WARNING: Average risk coverage is "
        f"only {average_coverage:.2f}%."
    )


if average_risk_range > 0:

    print(
        f"PASS: Candidate routes show "
        f"risk differentiation "
        f"(average range {average_risk_range:.2f})."
    )

else:

    print(
        "WARNING: Candidate routes show "
        "no meaningful risk differentiation."
    )


if all_three_same < len(
    test_summary_df
):

    print(
        "PASS: At least one test produces "
        "different route recommendations."
    )

else:

    print(
        "INFO: All tests select the same "
        "route for all recommendation types."
    )


print(
    "\n"
    "The validation analysis is complete."
)


print(
    "=" * 75
)

print(
    "STEP 33 COMPLETE"
)

print(
    "=" * 75
)