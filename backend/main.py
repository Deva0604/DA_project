from pathlib import Path
from functools import lru_cache

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
    return {
        "recommendations_file_exists": DATA_FILE.exists(),
        "road_graph_exists": GRAPH_FILE.exists(),
        "weather": "Not yet verified as live",
        "traffic": "Not yet verified as live",
    }
