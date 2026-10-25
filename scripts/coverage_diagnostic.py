"""Route-edge coverage diagnostic for SafeRoute.

Reports, for each test journey and route category:
- Total route edges
- Edges with directly matched traffic observations
- Edges with fresh traffic observations
- Edges with directly matched weather observations
- Edges with fresh weather observations
- Edges using propagated baseline estimates
- Edges with missing data
- Traffic and weather coverage percentages separately

Uses actual graph edges and validated datasets. Does not fabricate
observations or count propagated estimates as live observations.
"""

from __future__ import annotations

import datetime as _dt
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import routing  # noqa: E402


TRAFFIC_FRESHNESS_MINUTES = 180
WEATHER_FRESHNESS_MINUTES = 60


def _is_fresh(ts, threshold_minutes):
    if ts is None:
        return False, None
    try:
        observed_at = _dt.datetime.fromisoformat(str(ts))
        if observed_at.tzinfo is None:
            import zoneinfo

            observed_at = observed_at.replace(tzinfo=zoneinfo.ZoneInfo("Asia/Kolkata"))
        now = _dt.datetime.now(tz=observed_at.tzinfo)
        age = (now - observed_at).total_seconds() / 60.0
        return age <= threshold_minutes, round(age, 1)
    except Exception:
        return False, None


def analyze_coverage():
    graph = routing.load_graph()
    risk_df = routing.load_dynamic_risk()
    lookup = routing.build_risk_lookup(risk_df)
    routing_graph = routing.build_routing_graph(graph, lookup, exclude_closed=True)

    # Load timestamps for freshness checks
    dr = risk_df.copy()
    dr["traffic_fresh"] = dr["traffic_observation_time"].apply(
        lambda t: _is_fresh(t, TRAFFIC_FRESHNESS_MINUTES)[0]
    )
    dr["weather_fresh"] = dr["observation_time"].apply(
        lambda t: _is_fresh(t, WEATHER_FRESHNESS_MINUTES)[0]
    )
    dr["traffic_age"] = dr["traffic_observation_time"].apply(
        lambda t: _is_fresh(t, TRAFFIC_FRESHNESS_MINUTES)[1]
    )
    dr["weather_age"] = dr["observation_time"].apply(
        lambda t: _is_fresh(t, WEATHER_FRESHNESS_MINUTES)[1]
    )

    obs_keys = set(
        (int(r["osm_u"]), int(r["osm_v"]), int(r["osm_key"])) for _, r in dr.iterrows()
    )
    traffic_obs_keys = {
        (int(r["osm_u"]), int(r["osm_v"]), int(r["osm_key"]))
        for _, r in dr[dr["traffic_status"] == "SUCCESS"].iterrows()
    }
    weather_obs_keys = {
        (int(r["osm_u"]), int(r["osm_v"]), int(r["osm_key"]))
        for _, r in dr[dr["weather_status"] == "SUCCESS"].iterrows()
    }
    traffic_fresh_keys = {
        (int(r["osm_u"]), int(r["osm_v"]), int(r["osm_key"]))
        for _, r in dr[dr["traffic_fresh"]].iterrows()
    }
    weather_fresh_keys = {
        (int(r["osm_u"]), int(r["osm_v"]), int(r["osm_key"]))
        for _, r in dr[dr["weather_fresh"]].iterrows()
    }

    results = []

    for test_id, journey in routing.JOURNEYS.items():
        routes, diagnostics = routing.get_route_options(
            origin_lat=journey["origin_lat"],
            origin_lon=journey["origin_lon"],
            destination_lat=journey["destination_lat"],
            destination_lon=journey["destination_lon"],
            test_id=test_id,
            test_origin=journey["origin"],
            test_destination=journey["destination"],
        )

        for route in routes:
            path = [int(n) for n in route["node_path"].split("|")]
            total_edges = len(path) - 1

            traffic_obs_count = 0
            traffic_fresh_count = 0
            weather_obs_count = 0
            weather_fresh_count = 0
            propagated_count = 0
            missing_count = 0

            for u, v in zip(path[:-1], path[1:]):
                edge_data = routing_graph.get_edge_data(u, v)
                if edge_data is None:
                    missing_count += 1
                    continue
                source = edge_data.get("observation_source", "propagated")
                identifier = (int(u), int(v), int(edge_data.get("original_key", -1)))
                if source == "observed":
                    traffic_obs_count += 1
                    weather_obs_count += 1
                    if identifier in traffic_fresh_keys:
                        traffic_fresh_count += 1
                    if identifier in weather_fresh_keys:
                        weather_fresh_count += 1
                else:
                    propagated_count += 1

            results.append(
                {
                    "test_id": test_id,
                    "origin": journey["origin"],
                    "destination": journey["destination"],
                    "category": route["category"],
                    "total_edges": total_edges,
                    "traffic_obs_edges": traffic_obs_count,
                    "traffic_fresh_edges": traffic_fresh_count,
                    "weather_obs_edges": weather_obs_count,
                    "weather_fresh_edges": weather_fresh_count,
                    "propagated_edges": propagated_count,
                    "missing_edges": missing_count,
                    "traffic_coverage_pct": round(
                        100.0 * traffic_obs_count / total_edges, 1
                    )
                    if total_edges
                    else 0.0,
                    "weather_coverage_pct": round(
                        100.0 * weather_obs_count / total_edges, 1
                    )
                    if total_edges
                    else 0.0,
                    "traffic_fresh_pct": round(
                        100.0 * traffic_fresh_count / total_edges, 1
                    )
                    if total_edges
                    else 0.0,
                    "weather_fresh_pct": round(
                        100.0 * weather_fresh_count / total_edges, 1
                    )
                    if total_edges
                    else 0.0,
                    "observed_coverage_percent": route.get("observed_coverage_percent"),
                    "data_coverage_percent": route.get("data_coverage_percent"),
                }
            )

    return results, dr


if __name__ == "__main__":
    results, dr = analyze_coverage()
    print("=" * 100)
    print("ROUTE-EDGE COVERAGE DIAGNOSTIC")
    print("=" * 100)
    print(f"\nDynamic-risk dataset: {len(dr)} road segments")
    print(f"Closed roads: {int(dr['road_closure'].sum())}")
    print(f"Traffic obs (max): {dr['traffic_observation_time'].max()}")
    print(f"Weather obs (max): {dr['observation_time'].max()}")
    print(f"Traffic SUCCESS: {(dr['traffic_status']=='SUCCESS').sum()}")
    print(f"Weather SUCCESS: {(dr['weather_status']=='SUCCESS').sum()}")
    print(f"Traffic fresh (<=180min): {dr['traffic_fresh'].sum()}")
    print(f"Weather fresh (<=60min): {dr['weather_fresh'].sum()}")
    print()

    header = (
        f"{'Journey':<8} {'Category':<18} {'Edges':<6} "
        f"{'TrafObs':<8} {'TrafFresh':<9} {'WeaObs':<8} {'WeaFresh':<9} "
        f"{'Prop':<6} {'Miss':<6} {'TrafCov%':<9} {'WeaCov%':<8}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['test_id']:<8} {r['category']:<18} {r['total_edges']:<6} "
            f"{r['traffic_obs_edges']:<8} {r['traffic_fresh_edges']:<9} "
            f"{r['weather_obs_edges']:<8} {r['weather_fresh_edges']:<9} "
            f"{r['propagated_edges']:<6} {r['missing_edges']:<6} "
            f"{r['traffic_coverage_pct']:<9} {r['weather_coverage_pct']:<8}"
        )

    print("\n" + "=" * 100)
    print("SUMMARY")
    print("=" * 100)
    tot_edges = sum(r["total_edges"] for r in results)
    tot_tobs = sum(r["traffic_obs_edges"] for r in results)
    tot_tfresh = sum(r["traffic_fresh_edges"] for r in results)
    tot_wobs = sum(r["weather_obs_edges"] for r in results)
    tot_wfresh = sum(r["weather_fresh_edges"] for r in results)
    tot_prop = sum(r["propagated_edges"] for r in results)
    print(f"Total route edges across all journeys/categories: {tot_edges}")
    print(f"Edges with directly matched traffic observations: {tot_tobs} ({100*tot_tobs/tot_edges:.1f}%)")
    print(f"Edges with fresh traffic observations: {tot_tfresh} ({100*tot_tfresh/tot_edges:.1f}%)")
    print(f"Edges with directly matched weather observations: {tot_wobs} ({100*tot_wobs/tot_edges:.1f}%)")
    print(f"Edges with fresh weather observations: {tot_wfresh} ({100*tot_wfresh/tot_edges:.1f}%)")
    print(f"Edges using propagated baseline: {tot_prop} ({100*tot_prop/tot_edges:.1f}%)")
    print(f"Edges with missing data: {sum(r['missing_edges'] for r in results)}")
