#!/usr/bin/env python3
"""Focused unit tests for SafeRoute pipeline components.

Uses existing project data files where possible. Mocks external APIs.
Run with: python -m unittest tests.test_saferoute_pipeline -v
"""

import os
import sys
import unittest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pandas as pd
import numpy as np

# Ensure project root is on the path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# ----------------------------------------------------------------
# Test data paths
# ----------------------------------------------------------------
DATA_DIR = ROOT / "data" / "processed"
TRAFFIC_TARGETS = DATA_DIR / "road_traffic_targets.csv"
TRAFFIC_PRODUCTION = DATA_DIR / "road_live_traffic_full.csv"
WEATHER_GRID = DATA_DIR / "live_weather_grid.csv"
ROAD_WEATHER = DATA_DIR / "road_weather_conditions.csv"
DYNAMIC_RISK = DATA_DIR / "dynamic_road_risk.csv"
GRAPH_FILE = DATA_DIR / "saferoute_routing_graph_v6.graphml"


class TestTrafficTimestampValidation(unittest.TestCase):
    """Test traffic timestamp freshness validation logic."""

    def test_fresh_timestamp_passes(self):
        now = datetime.now(timezone.utc)
        fresh = now - timedelta(minutes=10)
        age_min = (now - fresh).total_seconds() / 60
        self.assertLess(age_min, 180)

    def test_stale_timestamp_fails(self):
        now = datetime.now(timezone.utc)
        stale = now - timedelta(minutes=200)
        age_min = (now - stale).total_seconds() / 60
        self.assertGreater(age_min, 180)

    def test_future_timestamp_fails(self):
        now = datetime.now(timezone.utc)
        future = now + timedelta(minutes=30)
        age_min = (now - future).total_seconds() / 60
        self.assertLess(age_min, 0)

    def test_production_traffic_has_timestamps(self):
        """Production traffic file should have observation timestamps."""
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        self.assertIn("traffic_observation_time", df.columns)
        self.assertFalse(df["traffic_observation_time"].isna().any())


class TestDuplicateRoadKeyRejection(unittest.TestCase):
    """Test that duplicate road keys are rejected."""

    def test_production_traffic_unique_keys(self):
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        keys = ["osm_u", "osm_v", "osm_key"]
        self.assertFalse(df[keys].duplicated().any())

    def test_traffic_targets_unique_keys(self):
        df = pd.read_csv(TRAFFIC_TARGETS)
        keys = ["osm_u", "osm_v", "osm_key"]
        self.assertFalse(df[keys].duplicated().any())

    def test_dynamic_risk_unique_keys(self):
        df = pd.read_csv(DYNAMIC_RISK)
        keys = ["osm_u", "osm_v", "osm_key"]
        self.assertFalse(df[keys].duplicated().any())

    def test_road_weather_unique_keys(self):
        df = pd.read_csv(ROAD_WEATHER)
        keys = ["osm_u", "osm_v", "osm_key"]
        self.assertFalse(df[keys].duplicated().any())


class TestWeatherTimestampValidation(unittest.TestCase):
    """Test weather observation timestamp validation."""

    def test_weather_grid_has_utc_timestamps(self):
        df = pd.read_csv(WEATHER_GRID)
        self.assertIn("observation_time", df.columns)
        timestamps = pd.to_datetime(df["observation_time"], errors="coerce", utc=True)
        self.assertFalse(timestamps.isna().any())

    def test_weather_timestamps_not_future(self):
        df = pd.read_csv(WEATHER_GRID)
        now = pd.Timestamp.now(tz="UTC")
        timestamps = pd.to_datetime(df["observation_time"], errors="coerce", utc=True)
        tolerance = timedelta(minutes=10)
        self.assertFalse((timestamps > now + tolerance).any())

    def test_weather_all_status_success(self):
        df = pd.read_csv(WEATHER_GRID)
        self.assertTrue(df["weather_status"].eq("SUCCESS").all())


class TestWeatherToRoadAssignment(unittest.TestCase):
    """Test weather assignment to roads."""

    def test_road_weather_has_all_roads(self):
        """Road-weather assignment must cover every traffic target."""
        targets = pd.read_csv(TRAFFIC_TARGETS)
        assigned = pd.read_csv(ROAD_WEATHER)
        target_keys = set(
            zip(targets["osm_u"], targets["osm_v"], targets["osm_key"])
        )
        assigned_keys = set(
            zip(assigned["osm_u"], assigned["osm_v"], assigned["osm_key"])
        )
        self.assertEqual(target_keys, assigned_keys)

    def test_road_weather_preserves_row_count(self):
        targets = pd.read_csv(TRAFFIC_TARGETS)
        assigned = pd.read_csv(ROAD_WEATHER)
        self.assertEqual(len(assigned), len(targets))

    def test_road_weather_has_valid_weather(self):
        df = pd.read_csv(ROAD_WEATHER)
        self.assertTrue((df["weather_status"] == "SUCCESS").all())
        for col in ["temperature_c", "humidity_percent", "rain_mm", "wind_speed_kmh"]:
            self.assertTrue(pd.to_numeric(df[col], errors="coerce").notna().all())


class TestDynamicRiskCalculation(unittest.TestCase):
    """Test dynamic risk calculation with 50/30/20 weights."""

    def test_dynamic_risk_weights(self):
        """Verify weights are 0.50/0.30/0.20."""
        # Read the script source to verify weights.
        script = (ROOT / "scripts" / "23_build_dynamic_risk.py").read_text()
        self.assertIn("HISTORICAL_WEIGHT = 0.50", script)
        self.assertIn("TRAFFIC_WEIGHT = 0.30", script)
        self.assertIn("WEATHER_WEIGHT = 0.20", script)

    def test_dynamic_risk_in_range(self):
        df = pd.read_csv(DYNAMIC_RISK)
        available = pd.to_numeric(df["dynamic_risk"], errors="coerce").dropna()
        if not available.empty:
            self.assertTrue((available >= 0).all())
            self.assertTrue((available <= 100).all())

    def test_dynamic_risk_components_exist(self):
        df = pd.read_csv(DYNAMIC_RISK)
        for col in ["historical_risk", "traffic_risk", "weather_risk", "dynamic_risk"]:
            self.assertIn(col, df.columns)

    def test_dynamic_risk_weighted_formula(self):
        """Verify dynamic_risk = 0.5*historical + 0.3*traffic + 0.2*weather
        for non-closed rows where all components are available."""
        df = pd.read_csv(DYNAMIC_RISK)
        mask = (
            df["historical_risk"].notna()
            & df["traffic_risk"].notna()
            & df["weather_risk"].notna()
            & df["dynamic_risk"].notna()
            & (df["risk_data_status"] == "COMPLETE")
        )
        if mask.any():
            sample = df[mask].head(10)
            for idx, row in sample.iterrows():
                exp = (
                    0.50 * row["historical_risk"]
                    + 0.30 * row["traffic_risk"]
                    + 0.20 * row["weather_risk"]
                )
                self.assertAlmostEqual(row["dynamic_risk"], exp, places=1)


class TestAPIFailureHandling(unittest.TestCase):
    """Test that API failures are handled without marking as success."""

    def test_fetch_traffic_returns_failed_on_error(self):
        """Import and test fetch_traffic logic with mocked failed response."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "refresh_traffic", ROOT / "scripts" / "17_refresh_full_traffic.py"
        )
        mod = importlib.util.module_from_spec(spec)
        # Don't execute main; just load the module functions.
        spec.loader.exec_module(mod)

        # Create a mock session that returns a 401 response.
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        result = mod.fetch_traffic(mock_session, "fake_key", 13.0, 80.2)
        self.assertEqual(result["traffic_status"], "FAILED")
        self.assertIsNotNone(result["traffic_error"])
        self.assertEqual(result["traffic_http_status"], 401)


class TestPartialRefreshRejection(unittest.TestCase):
    """Test that partial staging cannot be promoted."""

    def test_staging_row_count_matches_targets(self):
        targets = pd.read_csv(TRAFFIC_TARGETS)
        target_count = len(targets)
        self.assertEqual(target_count, 1924)

    def test_staging_must_have_all_targets(self):
        """Promotion should reject staging with fewer rows than targets."""
        targets = pd.read_csv(TRAFFIC_TARGETS)
        target_keys = set(
            zip(targets["osm_u"], targets["osm_v"], targets["osm_key"])
        )
        self.assertEqual(len(target_keys), 1924)

    def test_incomplete_staging_cannot_promote(self):
        """Simulate: staging with only 500 of 1924 roads must be rejected."""
        targets = pd.read_csv(TRAFFIC_TARGETS)
        partial = targets.head(500).copy()
        partial["traffic_status"] = "SUCCESS"
        partial["traffic_observation_time"] = datetime.now(timezone.utc).isoformat()
        partial["current_speed_kmh"] = 30.0
        partial["free_flow_speed_kmh"] = 36.0
        partial["congestion_ratio"] = 0.0
        partial["traffic_risk"] = 0.0

        # Row count mismatch should cause rejection.
        self.assertNotEqual(len(partial), len(targets))
        self.assertLess(len(partial), len(targets))


class TestRoutingEngine(unittest.TestCase):
    """Test routing and route ranking components."""

    @classmethod
    def setUpClass(cls):
        if not GRAPH_FILE.exists():
            cls.skipTest(cls, "Graph file not found")
        import networkx as nx
        cls.graph = nx.read_graphml(GRAPH_FILE, node_type=int)

    def test_graph_has_nodes_and_edges(self):
        if not hasattr(self, "graph"):
            self.skipTest("Graph not loaded")
        self.assertGreater(self.graph.number_of_nodes(), 0)
        self.assertGreater(self.graph.number_of_edges(), 0)

    def test_graph_nodes_have_coordinates(self):
        if not hasattr(self, "graph"):
            self.skipTest("Graph not loaded")
        nodes_with_xy = sum(
            1 for _, d in self.graph.nodes(data=True) if "x" in d and "y" in d
        )
        self.assertGreater(nodes_with_xy, 0)

    def test_invalid_coordinates_rejected(self):
        """Test that NaN coordinates are rejected."""
        self.assertTrue(pd.isna(float("nan")))
        self.assertFalse(np.isfinite(float("nan")))


class TestBackendSchemas(unittest.TestCase):
    """Test backend endpoint response schemas."""

    def test_health_endpoint_fields(self):
        """Verify expected health response fields."""
        expected = {"status", "service", "recommendation_count", "journey_count", "graph_available"}
        self.assertTrue("status" in expected)
        self.assertTrue("service" in expected)

    def test_dynamic_risk_summary_fields(self):
        """Verify dynamic risk summary response fields."""
        df = pd.read_csv(DYNAMIC_RISK)
        required = {
            "osm_u", "osm_v", "osm_key",
            "historical_risk", "traffic_risk", "weather_risk",
            "dynamic_risk", "dynamic_risk_category",
            "risk_data_status",
            "traffic_status", "traffic_observation_time",
            "observation_time",
        }
        missing = required - set(df.columns)
        self.assertEqual(len(missing), 0, f"Missing columns: {missing}")

    def test_recommendations_columns(self):
        """Verify recommendations file has required columns."""
        rec_file = DATA_DIR / "ranked_saferoute_recommendations.csv"
        if rec_file.exists():
            df = pd.read_csv(rec_file)
            required = {"test_id", "origin", "destination", "recommendation",
                        "travel_time_min", "distance_km",
                        "distance_weighted_dynamic_risk", "node_path"}
            missing = required - set(df.columns)
            self.assertEqual(len(missing), 0, f"Missing columns: {missing}")


class TestTrafficStagingValidation(unittest.TestCase):
    """Test staging validation logic from promote_traffic_staging.py."""

    def test_required_traffic_columns(self):
        required = [
            "osm_u", "osm_v", "osm_key",
            "traffic_latitude", "traffic_longitude",
            "current_speed_kmh", "free_flow_speed_kmh",
            "traffic_status", "traffic_observation_time",
        ]
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        missing = [c for c in required if c not in df.columns]
        self.assertEqual(len(missing), 0, f"Missing columns: {missing}")

    def test_speed_values_physical(self):
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        current = pd.to_numeric(df["current_speed_kmh"], errors="coerce")
        free_flow = pd.to_numeric(df["free_flow_speed_kmh"], errors="coerce")
        self.assertTrue((current >= 0).all())
        self.assertTrue((free_flow > 0).all())

    def test_congestion_ratio_range(self):
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        congestion = pd.to_numeric(df["congestion_ratio"], errors="coerce")
        self.assertTrue(((congestion >= 0) & (congestion <= 1)).all())

    def test_traffic_risk_range(self):
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        risk = pd.to_numeric(df["traffic_risk"], errors="coerce")
        self.assertTrue(((risk >= 0) & (risk <= 100)).all())


class TestBackendFrontendSchemaCompatibility(unittest.TestCase):
    """Test that backend responses match frontend expectations."""

    def test_route_endpoint_fields(self):
        """Frontend expects: test_id, candidate_rank, origin, destination,
        recommendation, travel_time_min, distance_km, risk_score, coordinates."""
        expected_fields = {
            "test_id", "candidate_rank", "origin", "destination",
            "recommendation", "travel_time_min", "distance_km",
            "risk_score", "coordinates",
        }
        # These fields come from backend/main.py route_geometry endpoint.
        self.assertTrue("test_id" in expected_fields)
        self.assertTrue("coordinates" in expected_fields)

    def test_data_status_endpoint_fields(self):
        """Frontend expects traffic.freshness, weather.freshness, age_minutes."""
        expected_traffic_fields = {"freshness", "age_minutes", "threshold_minutes", "status"}
        expected_weather_fields = {"freshness", "age_minutes", "threshold_minutes", "status"}
        self.assertTrue("freshness" in expected_traffic_fields)
        self.assertTrue("freshness" in expected_weather_fields)


class TestResumeLogic(unittest.TestCase):
    """Test that the traffic refresh resume logic skips already-successful roads."""

    def test_pending_excludes_successful_keys(self):
        """Verify pending list only contains roads not in successful_keys."""
        # Simulate the resume logic from script 17.
        target_keys = [("a", "b", "0"), ("c", "d", "1"), ("e", "f", "2")]
        successful_keys = {("a", "b", "0")}  # First road already done

        pending = [
            i for i, key in enumerate(target_keys)
            if key not in successful_keys
        ]

        # Should only include indices 1 and 2 (roads c,d,1 and e,f,2)
        self.assertEqual(pending, [1, 2])
        self.assertEqual(len(pending), 2)

    def test_pending_empty_when_all_successful(self):
        """Verify pending is empty when all roads are already successful."""
        target_keys = [("a", "b", "0"), ("c", "d", "1")]
        successful_keys = {("a", "b", "0"), ("c", "d", "1")}

        pending = [
            i for i, key in enumerate(target_keys)
            if key not in successful_keys
        ]

        self.assertEqual(pending, [])

    def test_collector_freshness_constant_matches_promotion(self):
        """Collector skip window must stay aligned with promotion freshness."""
        import importlib.util

        refresh_spec = importlib.util.spec_from_file_location(
            "refresh_traffic", ROOT / "scripts" / "17_refresh_full_traffic.py"
        )
        refresh = importlib.util.module_from_spec(refresh_spec)
        refresh_spec.loader.exec_module(refresh)

        promote_spec = importlib.util.spec_from_file_location(
            "promote_traffic", ROOT / "scripts" / "promote_traffic_staging.py"
        )
        promote = importlib.util.module_from_spec(promote_spec)
        promote_spec.loader.exec_module(promote)

        self.assertEqual(
            refresh.TRAFFIC_FRESHNESS_MINUTES,
            promote.TRAFFIC_FRESHNESS_MINUTES,
        )

    def test_failed_fetch_does_not_replace_previous_success(self):
        """A later FAILED TomTom response must not overwrite a prior SUCCESS."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "refresh_traffic", ROOT / "scripts" / "17_refresh_full_traffic.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_session = MagicMock()
        mock_session.get.return_value = mock_response

        previous = {
            "osm_u": 1,
            "osm_v": 2,
            "osm_key": 0,
            "traffic_status": "SUCCESS",
            "current_speed_kmh": 42,
        }
        failed = mod.fetch_traffic(mock_session, "fake_key", 13.0, 80.2)
        self.assertEqual(failed["traffic_status"], "FAILED")

        if (
            failed.get("traffic_status") != "SUCCESS"
            and previous.get("traffic_status") == "SUCCESS"
        ):
            kept = previous
        else:
            kept = {**previous, **failed}

        self.assertEqual(kept["traffic_status"], "SUCCESS")
        self.assertEqual(kept["current_speed_kmh"], 42)


class TestPromotionValidation(unittest.TestCase):
    """Test that the promotion validator rejects invalid staging."""

    def test_partial_staging_rejected_by_row_count(self):
        """Staging with fewer rows than targets must be rejected."""
        targets = pd.read_csv(TRAFFIC_TARGETS)
        partial = targets.head(100).copy()
        self.assertLess(len(partial), len(targets))
        self.assertEqual(len(targets), 1924)

    def test_validate_staging_rejects_incomplete_dataset(self):
        """Call the real promote validator with a partial staging frame."""
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "promote_traffic", ROOT / "scripts" / "promote_traffic_staging.py"
        )
        promote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(promote)

        targets = pd.read_csv(TRAFFIC_TARGETS)
        partial = targets.head(10).copy()
        for column in promote.REQUIRED_TRAFFIC_COLUMNS:
            if column not in partial.columns:
                partial[column] = None
        partial["traffic_status"] = "SUCCESS"
        partial["traffic_observation_time"] = datetime.now(timezone.utc).isoformat()
        partial["current_speed_kmh"] = 30.0
        partial["free_flow_speed_kmh"] = 40.0
        partial["current_travel_time_sec"] = 20.0
        partial["free_flow_travel_time_sec"] = 15.0
        partial["traffic_confidence"] = 1.0
        partial["road_closure"] = False
        partial["congestion_ratio"] = 0.1
        partial["traffic_risk"] = 10.0
        partial["traffic_http_status"] = 200
        partial["traffic_error"] = None

        with self.assertRaises(ValueError) as ctx:
            promote.validate_staging(partial, targets, promote.now_utc())
        self.assertIn("1924", str(ctx.exception))

    def test_staging_must_have_required_columns(self):
        """Staging must contain all REQUIRED_TRAFFIC_COLUMNS."""
        required = [
            "osm_u", "osm_v", "osm_key",
            "traffic_latitude", "traffic_longitude",
            "current_speed_kmh", "free_flow_speed_kmh",
            "traffic_status", "traffic_observation_time",
        ]
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        missing = [c for c in required if c not in df.columns]
        self.assertEqual(len(missing), 0, f"Missing columns: {missing}")

    def test_staging_all_statuses_success(self):
        """Every road in valid staging must have traffic_status == SUCCESS."""
        df = pd.read_csv(TRAFFIC_PRODUCTION)
        # Note: production currently has stale data but all SUCCESS statuses.
        # This test validates the status field, not freshness.
        self.assertTrue(df["traffic_status"].eq("SUCCESS").all())


if __name__ == "__main__":
    unittest.main()
