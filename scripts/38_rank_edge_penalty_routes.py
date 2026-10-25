from pathlib import Path
from itertools import combinations

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"

INPUT_FILE = DATA_DIR / "edge_penalty_candidates.csv"
OUTPUT_FILE = DATA_DIR / "ranked_saferoute_recommendations.csv"
SUMMARY_FILE = DATA_DIR / "ranked_saferoute_summary.csv"

MAX_TIME_OVERHEAD = 0.20
FALLBACK_TIME_OVERHEAD = 0.40
# Safety-oriented fallback for substantially lower-risk routes.
SAFER_TIME_OVERHEAD = 0.70
MIN_RISK_REDUCTION = 0.25
MAX_OVERLAP = 0.70
MAX_RECOMMENDATIONS = 3


def parse_path(value):
    """Parse a pipe-separated sequence of road-network node IDs."""
    if pd.isna(value):
        return []
    return [node for node in str(value).split("|") if node]


def path_edges(path):
    """Represent a route as directed node-to-node edges."""
    return set(zip(path[:-1], path[1:]))


def jaccard_similarity(edges_a, edges_b):
    """Calculate directed-edge Jaccard similarity."""
    union = edges_a | edges_b
    if not union:
        return 1.0
    return len(edges_a & edges_b) / len(union)


def normalize(series):
    """Normalize a numeric series to [0, 1]."""
    minimum = series.min()
    maximum = series.max()

    if maximum == minimum:
        return pd.Series(0.0, index=series.index)

    return (series - minimum) / (maximum - minimum)


def rank_journey(group):
    group = group.copy()

    numeric_columns = [
        "candidate_rank",
        "travel_time_min",
        "distance_km",
        "avg_dynamic_risk",
        "distance_weighted_dynamic_risk",
    ]

    for column in numeric_columns:
        group[column] = pd.to_numeric(group[column], errors="coerce")

    group = group.dropna(subset=numeric_columns)
    group = group[
        (group["travel_time_min"] > 0)
        & (group["distance_km"] > 0)
    ].copy()

    if group.empty:
        return pd.DataFrame(), {
            "candidate_count": 0,
            "eligible_count": 0,
            "recommended_count": 0,
            "fastest_time_min": None,
            "time_limit_min": None,
            "mean_pairwise_overlap_percent": None,
            "status": "NO_VALID_CANDIDATES",
        }

    if "node_path" not in group.columns:
        raise ValueError(
            "Input CSV has no 'node_path' column. "
            "Rerun scripts/37_test_edge_penalty_routing.py first."
        )

    group = group.reset_index(drop=True)
    group["_path"] = group["node_path"].apply(parse_path)
    group["_edges"] = group["_path"].apply(path_edges)

    group = group[
        group["_path"].apply(lambda path: len(path) >= 2)
    ].copy().reset_index(drop=True)

    if group.empty:
        return pd.DataFrame(), {
            "candidate_count": 0,
            "eligible_count": 0,
            "recommended_count": 0,
            "fastest_time_min": None,
            "time_limit_min": None,
            "mean_pairwise_overlap_percent": None,
            "status": "NO_VALID_PATHS",
        }

    # Remove duplicate candidate ranks, keeping the first valid row.
    group = group.drop_duplicates(
        subset=["candidate_rank"], keep="first"
    ).reset_index(drop=True)

    fastest_time = group["travel_time_min"].min()
    normal_limit = fastest_time * (1 + MAX_TIME_OVERHEAD)

    group["time_overhead_percent"] = (
        group["travel_time_min"] / fastest_time - 1
    ) * 100

    # Calculate normalized scores for ALL valid candidates, including
    # safety-fallback routes that may sit outside the time-eligible set.
    # Balanced score: 60% normalized time, 40% normalized risk.
    group["normalized_time"] = normalize(group["travel_time_min"])
    group["normalized_risk"] = normalize(
        group["distance_weighted_dynamic_risk"]
    )
    group["balanced_score"] = (
        0.60 * group["normalized_time"]
        + 0.40 * group["normalized_risk"]
    )

    # Keep the existing route eligibility and selection rules unchanged.
    eligible = group[
        group["travel_time_min"] <= normal_limit
    ].copy().reset_index(drop=True)

    if eligible.empty:
        return pd.DataFrame(), {
            "candidate_count": len(group),
            "eligible_count": 0,
            "recommended_count": 0,
            "fastest_time_min": fastest_time,
            "time_limit_min": normal_limit,
            "mean_pairwise_overlap_percent": None,
            "status": "NO_TIME_ELIGIBLE_CANDIDATES",
        }

    preferred_eligible_count = len(eligible)
    fallback_used = False

    # Relax to 40% only when there are fewer than three candidates.
    if len(eligible) < MAX_RECOMMENDATIONS:
        fallback_limit = fastest_time * (1 + FALLBACK_TIME_OVERHEAD)
        fallback = group[
            group["travel_time_min"] <= fallback_limit
        ].copy().reset_index(drop=True)

        if len(fallback) > len(eligible):
            eligible = fallback
            fallback_used = True

    # Build a preferred ordering. The route selected for each category
    # must be distinct and pass the route-overlap filter.
    category_candidates = [
        (
            "Fastest",
            eligible.sort_values(
                ["travel_time_min", "candidate_rank"]
            ),
        ),
        (
            "Safest",
            eligible.sort_values(
                [
                    "distance_weighted_dynamic_risk",
                    "travel_time_min",
                    "candidate_rank",
                ]
            ),
        ),
        (
            "Balanced",
            eligible.sort_values(
                ["balanced_score", "candidate_rank"]
            ),
        ),
    ]

    selected = []
    selected_ranks = set()
    selected_labels = set()

    def try_select(label, candidates):
        for _, candidate in candidates.iterrows():
            rank = int(candidate["candidate_rank"])

            if rank in selected_ranks:
                continue

            edges = candidate["_edges"]
            overlaps = [
                jaccard_similarity(edges, item["_edges"])
                for item in selected
            ]
            max_overlap = max(overlaps, default=0.0)

            if max_overlap > MAX_OVERLAP:
                continue

            row = candidate.to_dict()
            row["recommendation"] = label
            row["max_overlap_with_selected_percent"] = max_overlap * 100

            selected.append(row)
            selected_ranks.add(rank)
            selected_labels.add(label)
            return True

        return False

    # Select the fastest route first.
    try_select("Fastest", category_candidates[0][1])
    # Select the lowest-risk distinct route.
    # If the fastest route is also the lowest-risk route, do not
    # falsely label a higher-risk route as "Safest".
    safest_candidates = category_candidates[1][1]
    if not selected or (
        not safest_candidates.empty
        and float(
            safest_candidates.iloc[0]["distance_weighted_dynamic_risk"]
        )
        < float(selected[0]["distance_weighted_dynamic_risk"])
    ):
        try_select("Safest", safest_candidates)
    else:
        # Do not claim a route is lower-risk unless its risk score
        # is actually lower than the selected fastest route.
        try_select("Alternative", safest_candidates)
    # Select the best balanced distinct route.
    try_select("Balanced", category_candidates[2][1])

    # Add a safety-oriented fallback when a substantially lower-risk
    # route is available outside the normal time limits.
    safer_time_limit = fastest_time * (1 + SAFER_TIME_OVERHEAD)
    safer_candidates = group[
        (group["travel_time_min"] > fastest_time * (1 + FALLBACK_TIME_OVERHEAD))
        & (group["travel_time_min"] <= safer_time_limit)
    ].copy()
    safer_candidates = safer_candidates.sort_values(
        ["distance_weighted_dynamic_risk", "travel_time_min", "candidate_rank"]
    )
    fastest_risk = float(
        eligible.sort_values("travel_time_min").iloc[0][
            "distance_weighted_dynamic_risk"
        ]
    )
    for _, candidate in safer_candidates.iterrows():
        if len(selected) >= MAX_RECOMMENDATIONS:
            break
        candidate_risk = float(candidate["distance_weighted_dynamic_risk"])
        if candidate_risk > fastest_risk * (1 - MIN_RISK_REDUCTION):
            continue
        rank = int(candidate["candidate_rank"])
        if rank in selected_ranks:
            continue
        edges = candidate["_edges"]
        overlaps = [
            jaccard_similarity(edges, item["_edges"])
            for item in selected
        ]
        max_overlap = max(overlaps, default=0.0)
        if max_overlap > MAX_OVERLAP:
            continue
        row = candidate.to_dict()
        row["recommendation"] = "Safer"
        row["max_overlap_with_selected_percent"] = max_overlap * 100

        selected.append(row)
        selected_ranks.add(rank)

    # If category winners overlap too much, fill remaining slots with
    # distinct low-score alternatives that satisfy the same time limit.
    remaining = eligible[
        ~eligible["candidate_rank"].astype(int).isin(selected_ranks)
    ].sort_values(["balanced_score", "candidate_rank"])

    for _, candidate in remaining.iterrows():
        if len(selected) >= MAX_RECOMMENDATIONS:
            break

        rank = int(candidate["candidate_rank"])
        edges = candidate["_edges"]

        overlaps = [
            jaccard_similarity(edges, item["_edges"])
            for item in selected
        ]
        max_overlap = max(overlaps, default=0.0)

        if max_overlap > MAX_OVERLAP:
            continue

        row = candidate.to_dict()
        row["recommendation"] = "Alternative"
        row["max_overlap_with_selected_percent"] = max_overlap * 100

        selected.append(row)
        selected_ranks.add(rank)

    # Calculate mean pairwise overlap.
    pairwise_overlaps = [
        jaccard_similarity(first["_edges"], second["_edges"]) * 100
        for first, second in combinations(selected, 2)
    ]

    has_safer_fallback = any(
        item["recommendation"] == "Safer"
        for item in selected
    )
    if has_safer_fallback and fallback_used:
        status = "PASS_WITH_TIME_AND_SAFETY_FALLBACK"
    elif has_safer_fallback:
        status = "PASS_WITH_SAFETY_FALLBACK"
    elif len(selected) >= MAX_RECOMMENDATIONS and fallback_used:
        status = "PASS_WITH_TIME_FALLBACK"
    elif len(selected) >= MAX_RECOMMENDATIONS:
        status = "PASS"
    elif len(selected) >= 2:
        status = "LIMITED_ALTERNATIVES"
    else:
        status = "INSUFFICIENT_DISTINCT_ROUTES"

    # Remove internal routing objects before writing the CSV.
    clean_rows = []
    for row in selected:
        row.pop("_path", None)
        row.pop("_edges", None)
        clean_rows.append(row)

    result = pd.DataFrame(clean_rows)

    summary = {
        "candidate_count": len(group),
        "eligible_count": len(eligible),
        "recommended_count": len(result),
        "fastest_time_min": fastest_time,
        "time_limit_min": normal_limit,
        "fallback_used": fallback_used,
        "safer_fallback_used": has_safer_fallback,
        "mean_pairwise_overlap_percent": (
            sum(pairwise_overlaps) / len(pairwise_overlaps)
            if pairwise_overlaps else 0.0
        ),
        "status": status,
    }

    return result, summary


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Candidate file not found: {INPUT_FILE}\n"
            "Run scripts/37_test_edge_penalty_routing.py first."
        )

    df = pd.read_csv(INPUT_FILE)

    if df.empty:
        raise ValueError("The candidate file contains no routes.")

    required_columns = {
        "test_id",
        "origin",
        "destination",
        "candidate_rank",
        "travel_time_min",
        "distance_km",
        "avg_dynamic_risk",
        "distance_weighted_dynamic_risk",
        "node_path",
    }

    missing = required_columns - set(df.columns)
    if missing:
        raise ValueError(
            f"Input file is missing required columns: {sorted(missing)}"
        )

    recommendation_frames = []
    summary_rows = []

    for test_id, journey in df.groupby("test_id", sort=True):
        ranked, stats = rank_journey(journey)

        if not ranked.empty:
            recommendation_frames.append(ranked)

        summary_rows.append({
            "test_id": test_id,
            "origin": journey["origin"].iloc[0],
            "destination": journey["destination"].iloc[0],
            **stats,
        })

    if recommendation_frames:
        recommendations = pd.concat(
            recommendation_frames, ignore_index=True
        )
    else:
        recommendations = pd.DataFrame()

    recommendations.to_csv(OUTPUT_FILE, index=False)
    summary = pd.DataFrame(summary_rows)
    summary.to_csv(SUMMARY_FILE, index=False)

    print("\n========== SAFEROUTE RANKING COMPLETE ==========")
    print(f"Recommendations: {OUTPUT_FILE}")
    print(f"Journey summary:  {SUMMARY_FILE}")

    if not recommendations.empty:
        display_columns = [
            "test_id",
            "origin",
            "destination",
            "candidate_rank",
            "recommendation",
            "travel_time_min",
            "distance_km",
            "distance_weighted_dynamic_risk",
            "time_overhead_percent",
            "max_overlap_with_selected_percent",
        ]
        print("\nRECOMMENDATIONS\n")
        print(recommendations[display_columns].to_string(index=False))

    print("\nJOURNEY SUMMARY\n")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
