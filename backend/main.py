from pathlib import Path
from functools import lru_cache
from datetime import datetime, timezone
import os

import pandas as pd
import osmnx as ox
import osmnx.io as oxio
import ast
import contextlib
from shapely import wkt

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_FILE = BASE_DIR / "data/processed/ranked_saferoute_recommendations.csv"
GRAPH_FILE = BASE_DIR / "data/processed/saferoute_routing_graph_v6.graphml"
FRONTEND_DIR = BASE_DIR / "frontend"
DYNAMIC_RISK_FILE = BASE_DIR / "data/processed/dynamic_road_risk.csv"

TRAFFIC_FRESHNESS_MINUTES = int(
    os.getenv("SAFEROUTE_TRAFFIC_FRESHNESS_MINUTES", "180")
)
WEATHER_FRESHNESS_MINUTES = int(
    os.getenv("SAFEROUTE_WEATHER_FRESHNESS_MINUTES", "60")
)


def get_data_freshness(observation_end, threshold_minutes):
    """Classify data freshness using its latest observation timestamp."""
    if observation_end is None or pd.isna(observation_end):
        return {
            "freshness": "UNAVAILABLE",
            "age_minutes": None,
            "threshold_minutes": threshold_minutes,
        }

    try:
        observed_at = pd.Timestamp(observation_end)
        if observed_at.tzinfo is None:
            observed_at = observed_at.tz_localize("Asia/Kolkata")

        now = pd.Timestamp.now(tz="Asia/Kolkata")
        age_minutes = (now - observed_at).total_seconds() / 60.0
        if age_minutes < 0:
            age_minutes = 0.0

        freshness = "FRESH" if age_minutes <= threshold_minutes else "STALE"
        return {
            "freshness": freshness,
            "age_minutes": round(age_minutes, 1),
            "threshold_minutes": threshold_minutes,
        }
    except (TypeError, ValueError, OverflowError):
        return {
            "freshness": "UNAVAILABLE",
            "age_minutes": None,
            "threshold_minutes": threshold_minutes,
        }


app = FastAPI(
    title="SafeRoute API",
    description="Historical road-risk-aware route recommendations for Chennai",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


def patch_osmnx_edge_conversion():
    """Handle GraphML edge attributes that are already non-string values."""
    original = oxio._convert_edge_attr_types
    if getattr(original, "_saferoute_patched", False):
        return

    def safe_convert(G, dtypes):
        for _, _, data in G.edges(data=True):
            data.pop("id", None)
            for attr, value in list(data.items()):
                if isinstance(value, str):
                    if (
                        (value.startswith("[") and value.endswith("]"))
                        or (value.startswith("{") and value.endswith("}"))
                    ):
                        with contextlib.suppress(SyntaxError, ValueError):
                            data[attr] = ast.literal_eval(value)
            for attr in data.keys() & dtypes.keys():
                if isinstance(data[attr], list):
                    data[attr] = [dtypes[attr](item) for item in data[attr]]
                else:
                    data[attr] = dtypes[attr](data[attr])
            if "geometry" in data and isinstance(data["geometry"], str):
                data["geometry"] = wkt.loads(data["geometry"])
        return G

    safe_convert._saferoute_patched = True
    oxio._convert_edge_attr_types = safe_convert


patch_osmnx_edge_conversion()


def load_recommendations():
    if not DATA_FILE.exists():
        raise FileNotFoundError(f"Recommendation file not found: {DATA_FILE}")

    df = pd.read_csv(DATA_FILE)

    required = {
        "test_id", "origin", "destination", "recommendation",
        "travel_time_min", "distance_km",
        "distance_weighted_dynamic_risk", "node_path",
    }

    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing CSV columns: {sorted(missing)}")

    return df


def load_dynamic_risk():
    if not DYNAMIC_RISK_FILE.exists():
        raise FileNotFoundError(
            f"Dynamic risk file not found: {DYNAMIC_RISK_FILE}"
        )
    df = pd.read_csv(DYNAMIC_RISK_FILE)
    required = {
        "osm_u",
        "osm_v",
        "osm_key",
        "historical_risk",
        "traffic_risk",
        "weather_risk",
        "dynamic_risk",
        "dynamic_risk_category",
        "risk_data_status",
        "traffic_status",
        "traffic_observation_time",
        "observation_time",
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f"Missing dynamic-risk columns: {sorted(missing)}"
        )
    return df


@lru_cache(maxsize=1)
def load_graph():
    if not GRAPH_FILE.exists():
        raise FileNotFoundError(f"Road graph not found: {GRAPH_FILE}")

    print("Loading Chennai road network. First route-map request may take a little time...")
    graph = ox.load_graphml(GRAPH_FILE)
    print(f"Road network loaded: {len(graph.nodes):,} nodes")
    return graph


@app.get("/", include_in_schema=False)
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    try:
        df = load_recommendations()
        return {
            "status": "ok",
            "service": "SafeRoute",
            "recommendation_count": len(df),
            "journey_count": int(df["test_id"].nunique()),
            "graph_available": GRAPH_FILE.exists(),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/journeys")
def journeys():
    try:
        df = load_recommendations()
        grouped = df.groupby("test_id", sort=True).first().reset_index()

        return [
            {
                "test_id": int(row["test_id"]),
                "origin": str(row["origin"]),
                "destination": str(row["destination"]),
                "recommendation_count": int(
                    (df["test_id"] == row["test_id"]).sum()
                ),
            }
            for _, row in grouped.iterrows()
        ]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/recommendations/{test_id}")
def recommendations(test_id: int):
    try:
        df = load_recommendations()
        selected = df[df["test_id"] == test_id].copy()

        if selected.empty:
            raise HTTPException(status_code=404, detail="Journey not found")

        # node_path is used by the separate route-geometry endpoint.
        selected = selected.drop(columns=["node_path"])
        # Convert NaN values to None so FastAPI can serialize them as JSON null.
        selected = selected.astype(object)
        selected = selected.where(pd.notna(selected), None)

        return selected.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


def find_node(graph, value):
    if value in graph:
        return value

    text_value = str(value)

    if text_value in graph:
        return text_value

    try:
        numeric_value = int(text_value)
        if numeric_value in graph:
            return numeric_value
    except (TypeError, ValueError):
        pass

    raise KeyError(f"Road-network node not found: {value}")


@app.get("/api/route/{test_id}/{candidate_rank}")
def route_geometry(test_id: int, candidate_rank: int):
    try:
        df = load_recommendations()
        selected = df[
            (df["test_id"] == test_id)
            & (df["candidate_rank"] == candidate_rank)
        ]

        if selected.empty:
            raise HTTPException(status_code=404, detail="Route not found")

        row = selected.iloc[0]
        raw_path = str(row["node_path"]).split("|")

        graph = load_graph()
        coordinates = []

        for raw_node in raw_path:
            node = find_node(graph, raw_node)
            data = graph.nodes[node]
            coordinates.append([float(data["y"]), float(data["x"])])

        return {
            "test_id": test_id,
            "candidate_rank": candidate_rank,
            "origin": str(row["origin"]),
            "destination": str(row["destination"]),
            "recommendation": str(row["recommendation"]),
            "travel_time_min": float(row["travel_time_min"]),
            "distance_km": float(row["distance_km"]),
            "risk_score": float(row["distance_weighted_dynamic_risk"]),
            "coordinates": coordinates,
        }

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/data-status")
def data_status():
    result = {
        "recommendations_file_exists": DATA_FILE.exists(),
        "road_graph_exists": GRAPH_FILE.exists(),
        "dynamic_risk_file_exists": DYNAMIC_RISK_FILE.exists(),
        "weather": "Not yet verified as live",
        "traffic": "Not yet verified as live",
    }
    if DYNAMIC_RISK_FILE.exists():
        try:
            df = load_dynamic_risk()
            result.update({
                "dynamic_risk_road_count": len(df),
                "traffic": {
                    "status": (
                        "SUCCESS"
                        if df["traffic_status"].eq("SUCCESS").all()
                        else "PARTIAL"
                    ),
                    "observation_start": (
                        None
                        if df["traffic_observation_time"].isna().all()
                        else str(df["traffic_observation_time"].min())
                    ),
                    "observation_end": (
                        None
                        if df["traffic_observation_time"].isna().all()
                        else str(df["traffic_observation_time"].max())
                    ),
                    **get_data_freshness(
                        df["traffic_observation_time"].max(),
                        TRAFFIC_FRESHNESS_MINUTES,
                    ),
                },
                "weather": {
                    "status": (
                        "SUCCESS"
                        if df["weather_status"].eq("SUCCESS").all()
                        else "PARTIAL"
                    ),
                    "observation_start": (
                        None
                        if df["observation_time"].isna().all()
                        else str(df["observation_time"].min())
                    ),
                    "observation_end": (
                        None
                        if df["observation_time"].isna().all()
                        else str(df["observation_time"].max())
                    ),
                    **get_data_freshness(
                        df["observation_time"].max(),
                        WEATHER_FRESHNESS_MINUTES,
                    ),
                },
            })
        except Exception as exc:
            result["dynamic_risk_error"] = str(exc)
    return result


@app.get("/api/dynamic-risk/summary")
def dynamic_risk_summary():
    try:
        df = load_dynamic_risk()
        risk_counts = (
            df["dynamic_risk_category"]
            .value_counts(dropna=False)
            .to_dict()
        )
        complete_count = int(
            df["risk_data_status"].eq("COMPLETE").sum()
        )
        closed_count = int(
            df["risk_data_status"].eq("CLOSED").sum()
        )
        available_risk = pd.to_numeric(
            df["dynamic_risk"],
            errors="coerce",
        ).dropna()
        return {
            "road_segment_count": len(df),
            "complete_risk_count": complete_count,
            "closed_classification_count": closed_count,
            "risk_category_counts": {
                str(k): int(v) for k, v in risk_counts.items()
            },
            "mean_dynamic_risk": (
                round(float(available_risk.mean()), 2)
                if not available_risk.empty else None
            ),
            "traffic_observation_start": (
                None
                if df["traffic_observation_time"].isna().all()
                else str(df["traffic_observation_time"].min())
            ),
            "traffic_observation_end": (
                None
                if df["traffic_observation_time"].isna().all()
                else str(df["traffic_observation_time"].max())
            ),
            "weather_observation_start": (
                None
                if df["observation_time"].isna().all()
                else str(df["observation_time"].min())
            ),
            "weather_observation_end": (
                None
                if df["observation_time"].isna().all()
                else str(df["observation_time"].max())
            ),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/api/dynamic-risk/roads")
def dynamic_risk_roads(
    category: str | None = None,
    limit: int = 100,
):
    try:
        if limit < 1 or limit > 500:
            raise HTTPException(
                status_code=400,
                detail="limit must be between 1 and 500",
            )
        df = load_dynamic_risk()
        if category:
            allowed = {
                "LOW", "MEDIUM", "HIGH", "SEVERE",
                "CLOSED", "UNAVAILABLE",
            }
            category = category.upper()
            if category not in allowed:
                raise HTTPException(
                    status_code=400,
                    detail=f"category must be one of {sorted(allowed)}",
                )
            df = df[
                df["dynamic_risk_category"].astype(str).str.upper()
                == category
            ]
        df = df.sort_values(
            "dynamic_risk",
            ascending=False,
            na_position="last",
        ).head(limit)

        columns = [
            "osm_u",
            "osm_v",
            "osm_key",
            "road_name",
            "highway",
            "historical_risk",
            "traffic_risk",
            "weather_risk",
            "dynamic_risk",
            "dynamic_risk_category",
            "risk_data_status",
            "traffic_status",
            "traffic_observation_time",
            "observation_time",
        ]
        available = [c for c in columns if c in df.columns]
        selected = df[available].copy()

        # Clean OSM metadata that may be stored as Python-list strings.
        def clean_metadata(value):
            if value is None or pd.isna(value):
                return None

            if isinstance(value, (list, tuple)):
                values = [str(item).strip() for item in value if str(item).strip()]
                return ", ".join(values) if values else None

            value = str(value).strip()

            if not value or value.lower() in {"nan", "none", "null"}:
                return None

            if value.startswith("[") and value.endswith("]"):
                import ast

                try:
                    parsed = ast.literal_eval(value)
                    if isinstance(parsed, (list, tuple)):
                        values = [
                            str(item).strip()
                            for item in parsed
                            if str(item).strip()
                        ]
                        return ", ".join(values) if values else None
                except (ValueError, SyntaxError):
                    pass

            return value

        for column in ("road_name", "highway"):
            if column in selected.columns:
                selected[column] = selected[column].map(clean_metadata)

        selected = selected.astype(object)
        selected = selected.where(pd.notna(selected), None)

        return selected.to_dict(orient="records")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
