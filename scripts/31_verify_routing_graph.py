import os
import math
import csv
from collections import Counter

import networkx as nx
import osmnx as ox


# ============================================================
# SAFEROUTE - ROUTING GRAPH VERIFICATION
# STEP 31
# ============================================================

GRAPH_FILE = (
    "data/processed/"
    "saferoute_routing_graph_v3.graphml"
)

OUTPUT_FILE = (
    "data/processed/"
    "routing_graph_verification.csv"
)


print("=" * 75)
print("SAFEROUTE - ROUTING GRAPH VERIFICATION")
print("=" * 75)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

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


def safe_float(value, default=0.0):

    try:

        result = float(value)

        if not math.isfinite(result):
            return default

        return result

    except (TypeError, ValueError):

        return default


def normalize_source(value):

    source = str(
        value
    ).strip().lower()

    if source in [
        "observed",
        "actual",
        "direct",
    ]:
        return "observed"

    if source in [
        "spatial_propagated",
        "propagated",
        "spatial-propagated",
    ]:
        return "spatial_propagated"

    if source in [
        "baseline",
        "baseline_no_observation",
        "unknown",
        "none",
        "",
    ]:
        return "baseline"

    if source == "closed":
        return "closed"

    return source


# ============================================================
# 1. CHECK GRAPH FILE
# ============================================================

print("\n[1/7] Checking graph file...")


if not os.path.exists(GRAPH_FILE):

    print(
        f"ERROR: Graph file not found:"
    )

    print(
        GRAPH_FILE
    )

    raise FileNotFoundError(
        GRAPH_FILE
    )


file_size_mb = (
    os.path.getsize(GRAPH_FILE)
    / (1024 * 1024)
)


print(
    f"Graph file : {GRAPH_FILE}"
)

print(
    f"File size  : {file_size_mb:.2f} MB"
)


# ============================================================
# 2. LOAD GRAPH
# ============================================================

print(
    "\n[2/7] Loading graph..."
)


try:

    G = ox.load_graphml(
        GRAPH_FILE
    )

except Exception:

    print(
        "ox.load_graphml failed."
    )

    print(
        "Using nx.read_graphml..."
    )

    G = nx.read_graphml(
        GRAPH_FILE
    )


print(
    f"Nodes : {len(G.nodes):,}"
)

print(
    f"Edges : {len(G.edges):,}"
)


# ============================================================
# 3. CHECK GRAPH STRUCTURE
# ============================================================

print(
    "\n[3/7] Checking graph structure..."
)


node_count = len(G.nodes)

edge_count = len(G.edges)


print(
    f"Node count : {node_count:,}"
)

print(
    f"Edge count : {edge_count:,}"
)


if node_count == 0:

    print(
        "ERROR: Graph contains no nodes."
    )

    raise RuntimeError(
        "Empty graph."
    )


if edge_count == 0:

    print(
        "ERROR: Graph contains no edges."
    )

    raise RuntimeError(
        "Graph has no edges."
    )


# ============================================================
# 4. INSPECT RISK ATTRIBUTES
# ============================================================

print(
    "\n[4/7] Inspecting risk attributes..."
)


source_counter = Counter()

category_counter = Counter()

confidence_counter = Counter()


closed_edges = 0

observed_edges = 0

propagated_edges = 0

baseline_edges = 0

unknown_source_edges = 0


missing_dynamic_risk = 0

missing_historical_risk = 0

missing_traffic_risk = 0

missing_weather_risk = 0

missing_travel_time = 0

invalid_dynamic_risk = 0


dynamic_risk_values = []

historical_risk_values = []

traffic_risk_values = []

weather_risk_values = []


for u, v, key, data in G.edges(
    keys=True,
    data=True
):

    # --------------------------------------------------------
    # Risk source
    # --------------------------------------------------------

    source = normalize_source(
        data.get(
            "risk_source",
            "baseline"
        )
    )

    source_counter[source] += 1


    if source == "observed":

        observed_edges += 1

    elif source == "spatial_propagated":

        propagated_edges += 1

    elif source == "baseline":

        baseline_edges += 1

    elif source == "closed":

        closed_edges += 1

    else:

        unknown_source_edges += 1


    # --------------------------------------------------------
    # Risk category
    # --------------------------------------------------------

    category = str(
        data.get(
            "risk_category",
            "UNKNOWN"
        )
    ).strip().upper()


    category_counter[
        category
    ] += 1


    # --------------------------------------------------------
    # Confidence
    # --------------------------------------------------------

    confidence = str(
        data.get(
            "risk_confidence",
            "UNKNOWN"
        )
    ).strip().upper()


    confidence_counter[
        confidence
    ] += 1


    # --------------------------------------------------------
    # Dynamic risk
    # --------------------------------------------------------

    if "dynamic_risk" not in data:

        missing_dynamic_risk += 1

    else:

        value = safe_float(
            data.get(
                "dynamic_risk"
            ),
            float("nan")
        )


        if not math.isfinite(value):

            invalid_dynamic_risk += 1

        else:

            dynamic_risk_values.append(
                value
            )


    # --------------------------------------------------------
    # Historical risk
    # --------------------------------------------------------

    if "historical_risk" not in data:

        missing_historical_risk += 1

    else:

        value = safe_float(
            data.get(
                "historical_risk"
            ),
            float("nan")
        )


        if math.isfinite(value):

            historical_risk_values.append(
                value
            )


    # --------------------------------------------------------
    # Traffic risk
    # --------------------------------------------------------

    if "traffic_risk" not in data:

        missing_traffic_risk += 1

    else:

        value = safe_float(
            data.get(
                "traffic_risk"
            ),
            float("nan")
        )


        if math.isfinite(value):

            traffic_risk_values.append(
                value
            )


    # --------------------------------------------------------
    # Weather risk
    # --------------------------------------------------------

    if "weather_risk" not in data:

        missing_weather_risk += 1

    else:

        value = safe_float(
            data.get(
                "weather_risk"
            ),
            float("nan")
        )


        if math.isfinite(value):

            weather_risk_values.append(
                value
            )


    # --------------------------------------------------------
    # Travel time
    # --------------------------------------------------------

    if (
        "routing_travel_time"
        not in data
    ):

        missing_travel_time += 1


# ============================================================
# 5. PRINT RISK SUMMARY
# ============================================================

print(
    "\n[5/7] Risk layer summary..."
)


print(
    "\nRISK SOURCES"
)

print(
    "-" * 50
)


for source, count in sorted(
    source_counter.items()
):

    percentage = (
        count
        / edge_count
        * 100
    )

    print(
        f"{source:22s} : "
        f"{count:8,} "
        f"({percentage:6.2f}%)"
    )


print(
    "\nRISK CATEGORIES"
)

print(
    "-" * 50
)


for category, count in sorted(
    category_counter.items()
):

    percentage = (
        count
        / edge_count
        * 100
    )

    print(
        f"{category:22s} : "
        f"{count:8,} "
        f"({percentage:6.2f}%)"
    )


print(
    "\nRISK CONFIDENCE"
)

print(
    "-" * 50
)


for confidence, count in sorted(
    confidence_counter.items()
):

    percentage = (
        count
        / edge_count
        * 100
    )

    print(
        f"{confidence:22s} : "
        f"{count:8,} "
        f"({percentage:6.2f}%)"
    )


# ============================================================
# RISK STATISTICS
# ============================================================

print(
    "\nRISK STATISTICS"
)

print(
    "-" * 50
)


if dynamic_risk_values:

    print(
        f"Dynamic risk min    : "
        f"{min(dynamic_risk_values):.2f}"
    )

    print(
        f"Dynamic risk max    : "
        f"{max(dynamic_risk_values):.2f}"
    )

    print(
        f"Dynamic risk mean   : "
        f"{sum(dynamic_risk_values) / len(dynamic_risk_values):.2f}"
    )

    sorted_risk = sorted(
        dynamic_risk_values
    )

    middle = len(sorted_risk) // 2

    if len(sorted_risk) % 2:

        median_risk = sorted_risk[
            middle
        ]

    else:

        median_risk = (
            sorted_risk[middle - 1]
            + sorted_risk[middle]
        ) / 2

    print(
        f"Dynamic risk median : "
        f"{median_risk:.2f}"
    )


# ============================================================
# 6. ROUTING SAFETY CHECKS
# ============================================================

print(
    "\n[6/7] Running routing safety checks..."
)


checks = []


# ------------------------------------------------------------
# Check 1 - graph exists
# ------------------------------------------------------------

checks.append({

    "check":
        "Graph exists",

    "status":
        "PASS",

    "value":
        GRAPH_FILE,

})


# ------------------------------------------------------------
# Check 2 - nodes
# ------------------------------------------------------------

checks.append({

    "check":
        "Nodes available",

    "status":
        "PASS"
        if node_count > 0
        else "FAIL",

    "value":
        node_count,

})


# ------------------------------------------------------------
# Check 3 - edges
# ------------------------------------------------------------

checks.append({

    "check":
        "Edges available",

    "status":
        "PASS"
        if edge_count > 0
        else "FAIL",

    "value":
        edge_count,

})


# ------------------------------------------------------------
# Check 4 - dynamic risk
# ------------------------------------------------------------

checks.append({

    "check":
        "Dynamic risk present",

    "status":
        "PASS"
        if missing_dynamic_risk == 0
        else "FAIL",

    "value":
        f"missing={missing_dynamic_risk}",

})


# ------------------------------------------------------------
# Check 5 - historical risk
# ------------------------------------------------------------

checks.append({

    "check":
        "Historical risk present",

    "status":
        "PASS"
        if missing_historical_risk == 0
        else "FAIL",

    "value":
        f"missing={missing_historical_risk}",

})


# ------------------------------------------------------------
# Check 6 - traffic risk
# ------------------------------------------------------------

checks.append({

    "check":
        "Traffic risk present",

    "status":
        "PASS"
        if missing_traffic_risk == 0
        else "FAIL",

    "value":
        f"missing={missing_traffic_risk}",

})


# ------------------------------------------------------------
# Check 7 - weather risk
# ------------------------------------------------------------

checks.append({

    "check":
        "Weather risk present",

    "status":
        "PASS"
        if missing_weather_risk == 0
        else "FAIL",

    "value":
        f"missing={missing_weather_risk}",

})


# ------------------------------------------------------------
# Check 8 - travel time
# ------------------------------------------------------------

checks.append({

    "check":
        "Routing travel time present",

    "status":
        "PASS"
        if missing_travel_time == 0
        else "WARNING",

    "value":
        f"missing={missing_travel_time}",

})


# ------------------------------------------------------------
# Check 9 - closed roads
# ------------------------------------------------------------

checks.append({

    "check":
        "Closed roads identified",

    "status":
        "PASS"
        if closed_edges > 0
        else "INFO",

    "value":
        closed_edges,

})


# ------------------------------------------------------------
# Check 10 - unknown sources
# ------------------------------------------------------------

checks.append({

    "check":
        "Risk source classification",

    "status":
        "PASS"
        if unknown_source_edges == 0
        else "WARNING",

    "value":
        f"unknown={unknown_source_edges}",

})


# ------------------------------------------------------------
# Print checks
# ------------------------------------------------------------

print(
    "\nVALIDATION CHECKS"
)

print(
    "-" * 75
)


for check in checks:

    print(
        f"{check['status']:8s} | "
        f"{check['check']:35s} | "
        f"{check['value']}"
    )


# ============================================================
# 7. SAVE VERIFICATION REPORT
# ============================================================

print(
    "\n[7/7] Saving verification report..."
)


os.makedirs(
    os.path.dirname(
        OUTPUT_FILE
    ),
    exist_ok=True
)


report_rows = [

    {
        "metric":
            "graph_file",

        "value":
            GRAPH_FILE,
    },

    {
        "metric":
            "file_size_mb",

        "value":
            round(
                file_size_mb,
                2
            ),
    },

    {
        "metric":
            "node_count",

        "value":
            node_count,
    },

    {
        "metric":
            "edge_count",

        "value":
            edge_count,
    },

    {
        "metric":
            "observed_edges",

        "value":
            observed_edges,
    },

    {
        "metric":
            "propagated_edges",

        "value":
            propagated_edges,
    },

    {
        "metric":
            "baseline_edges",

        "value":
            baseline_edges,
    },

    {
        "metric":
            "closed_edges",

        "value":
            closed_edges,
    },

    {
        "metric":
            "unknown_source_edges",

        "value":
            unknown_source_edges,
    },

    {
        "metric":
            "missing_dynamic_risk",

        "value":
            missing_dynamic_risk,
    },

    {
        "metric":
            "missing_historical_risk",

        "value":
            missing_historical_risk,
    },

    {
        "metric":
            "missing_traffic_risk",

        "value":
            missing_traffic_risk,
    },

    {
        "metric":
            "missing_weather_risk",

        "value":
            missing_weather_risk,
    },

    {
        "metric":
            "missing_routing_travel_time",

        "value":
            missing_travel_time,
    },

    {
        "metric":
            "invalid_dynamic_risk",

        "value":
            invalid_dynamic_risk,
    },

]


with open(
    OUTPUT_FILE,
    "w",
    newline=""
) as file:

    writer = csv.DictWriter(
        file,
        fieldnames=[
            "metric",
            "value"
        ]
    )

    writer.writeheader()

    writer.writerows(
        report_rows
    )


# ============================================================
# FINAL RESULT
# ============================================================

failed_checks = [

    check

    for check in checks

    if check["status"] == "FAIL"

]


print(
    f"\nSaved: {OUTPUT_FILE}"
)


print(
    "\n"
    + "=" * 75
)


if failed_checks:

    print(
        "ROUTING GRAPH STATUS: NOT READY"
    )

    print(
        f"Failed checks: "
        f"{len(failed_checks)}"
    )

else:

    print(
        "ROUTING GRAPH STATUS: READY"
    )

    print(
        "All critical checks passed."
    )


print(
    "=" * 75
)

print(
    "\nSTEP 31 COMPLETE"
)

print(
    "=" * 75
)
