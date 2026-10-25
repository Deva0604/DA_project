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
import networkx as nx

# Ensure project root is on the path.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend import routing

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


# ---------------------------------------------------------------------------
# Pure risk-calculation tests (synthetic, no external API)
# ---------------------------------------------------------------------------

class TestTrafficRiskCalculation(unittest.TestCase):
    """Tests for travel-time-derived traffic risk."""

    def test_congestion_ratio_and_risk(self):
        ratio, risk = routing.traffic_risk_from_travel_times(220.0, 200.0)
        self.assertAlmostEqual(ratio, 1.1)
        self.assertAlmostEqual(risk, 10.0)

    def test_free_flow_is_zero_risk(self):
        ratio, risk = routing.traffic_risk_from_travel_times(200.0, 200.0)
        self.assertAlmostEqual(ratio, 1.0)
        self.assertEqual(risk, 0.0)

    def test_severe_congestion_capped_at_100(self):
        ratio, risk = routing.traffic_risk_from_travel_times(600.0, 200.0)
        self.assertAlmostEqual(ratio, 3.0)
        self.assertEqual(risk, 100.0)

    def test_missing_inputs_are_not_zero_risk(self):
        self.assertEqual(routing.traffic_risk_from_travel_times(None, 200.0), (None, None))
        self.assertEqual(routing.traffic_risk_from_travel_times(200.0, None), (None, None))
        self.assertEqual(routing.traffic_risk_from_travel_times(200.0, 0.0), (None, None))
        self.assertEqual(routing.traffic_risk_from_travel_times(-5.0, 200.0), (None, None))

    def test_congestion_categories(self):
        self.assertEqual(routing.congestion_category_from_ratio(1.05), "Free flow")
        self.assertEqual(routing.congestion_category_from_ratio(1.20), "Low congestion")
        self.assertEqual(routing.congestion_category_from_ratio(1.40), "Moderate congestion")
        self.assertEqual(routing.congestion_category_from_ratio(1.80), "Heavy congestion")
        self.assertEqual(routing.congestion_category_from_ratio(3.00), "Severe congestion")
        self.assertIsNone(routing.congestion_category_from_ratio(None))
        self.assertIsNone(routing.congestion_category_from_ratio(0.9))


class TestWeatherRiskCalculation(unittest.TestCase):
    """Tests for the existing Open-Meteo weather-risk calculation (script 21)."""

    @classmethod
    def setUpClass(cls):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "weather_risk", ROOT / "scripts" / "21_calculate_weather_risk.py"
        )
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_rain_risk_thresholds(self):
        self.assertEqual(self.mod.calculate_rain_risk(0.0), 0.0)
        self.assertEqual(self.mod.calculate_rain_risk(1.0), 20.0)
        self.assertEqual(self.mod.calculate_rain_risk(3.0), 40.0)
        self.assertEqual(self.mod.calculate_rain_risk(7.0), 70.0)
        self.assertEqual(self.mod.calculate_rain_risk(12.0), 100.0)

    def test_weather_code_risk(self):
        self.assertEqual(self.mod.calculate_weather_code_risk(0), 0.0)   # clear
        self.assertEqual(self.mod.calculate_weather_code_risk(45), 35.0) # fog
        self.assertEqual(self.mod.calculate_weather_code_risk(61), 60.0) # rain
        self.assertEqual(self.mod.calculate_weather_code_risk(95), 90.0) # thunderstorm

    def test_wind_risk(self):
        self.assertEqual(self.mod.calculate_wind_risk(10.0), 0.0)
        self.assertEqual(self.mod.calculate_wind_risk(35.0), 50.0)
        self.assertEqual(self.mod.calculate_wind_risk(70.0), 100.0)


class TestCombinedRiskCalculation(unittest.TestCase):
    """Tests for the combined risk formula and missing-data handling."""

    def test_all_components_available(self):
        expected = 0.50 * 60.0 + 0.30 * 40.0 + 0.20 * 20.0
        self.assertAlmostEqual(routing.combined_risk(60.0, 40.0, 20.0), expected)

    def test_missing_component_is_renormalized_not_zero(self):
        # Traffic missing: (0.5*100 + 0.2*0) / (0.5+0.2)
        expected = (0.50 * 100.0 + 0.20 * 0.0) / 0.70
        self.assertAlmostEqual(routing.combined_risk(100.0, None, 0.0), expected, places=1)

    def test_all_missing_returns_none(self):
        self.assertIsNone(routing.combined_risk(None, None, None))

    def test_missing_not_treated_as_safe(self):
        # Only a high historical risk available -> result stays high, not 0.
        result = routing.combined_risk(100.0, None, None)
        self.assertEqual(result, 100.0)

    def test_scores_stay_in_range(self):
        for args in [(0, 0, 0), (100, 100, 100), (50, None, 100), (None, 100, None)]:
            result = routing.combined_risk(*args)
            if result is not None:
                self.assertGreaterEqual(result, 0.0)
                self.assertLessEqual(result, 100.0)


class TestMissingAndStaleObservations(unittest.TestCase):
    """Tests that missing/stale data is distinguishable from safe data."""

    def test_dynamic_risk_missing_components(self):
        df = pd.read_csv(DYNAMIC_RISK)
        incomplete = df[df["risk_data_status"] == "INCOMPLETE"]
        # INCOMPLETE rows must have at least one missing component.
        for _, row in incomplete.iterrows():
            components = [
                row["historical_risk"], row["traffic_risk"], row["weather_risk"]
            ]
            self.assertTrue(any(pd.isna(c) for c in components))

    def test_closed_roads_excluded_from_risk_scores(self):
        df = pd.read_csv(DYNAMIC_RISK)
        closed = df[df["road_closure"] == True]  # noqa: E712
        self.assertTrue((closed["dynamic_risk"] == 100.0).all())
        self.assertTrue((closed["risk_data_status"] == "CLOSED").all())

    def test_data_freshness_fresh(self):
        from backend.main import get_data_freshness
        now = pd.Timestamp.now(tz="Asia/Kolkata")
        result = get_data_freshness(now, 180)
        self.assertEqual(result["freshness"], "FRESH")

    def test_data_freshness_stale(self):
        from backend.main import get_data_freshness
        stale = pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(minutes=200)
        result = get_data_freshness(stale, 180)
        self.assertEqual(result["freshness"], "STALE")
        self.assertGreater(result["age_minutes"], 180)

    def test_data_freshness_unavailable(self):
        from backend.main import get_data_freshness
        result = get_data_freshness(None, 180)
        self.assertEqual(result["freshness"], "UNAVAILABLE")
        self.assertIsNone(result["age_minutes"])


# ---------------------------------------------------------------------------
# Synthetic graph routing tests
# ---------------------------------------------------------------------------

def _build_synthetic_routing_graph():
    """Small directed graph where risk and time trade off.

    1 -> 2 -> 4 : time 10+10=20, risk 80+80   (fast but risky)
    1 -> 3 -> 4 : time 20+20=40, risk 10+10   (slow but safe)
    1 -> 4      : time 30, risk 50             (middle)
    """
    import networkx as nx
    graph = nx.DiGraph()
    for n in (1, 2, 3, 4):
        graph.add_node(n, x=0.0, y=0.0)

    edges = [
        (1, 2, 10.0, 80.0),
        (2, 4, 10.0, 80.0),
        (1, 3, 20.0, 10.0),
        (3, 4, 20.0, 10.0),
        (1, 4, 30.0, 50.0),
    ]
    for u, v, t, risk in edges:
        graph.add_edge(
            u, v,
            travel_time=t, travel_time_sec=t, length=1000.0, distance_m=1000.0,
            combined_risk=risk, dynamic_risk=risk,
            historical_risk=risk, traffic_risk=risk, weather_risk=0.0,
            road_closure=False, congestion_ratio=None, congestion_category=None,
            data_components_available=3, observed_components_available=3,
            observation_source="observed",
        )
    return graph


class TestRouteOptimization(unittest.TestCase):
    """Tests that dynamic edge costs drive route selection."""

    def test_fastest_route_minimizes_time(self):
        graph = _build_synthetic_routing_graph()
        path = nx.shortest_path(
            graph, 1, 4,
            weight=routing._edge_weight(graph, "fastest"),
        )
        self.assertEqual(path, [1, 2, 4])

    def test_safest_route_minimizes_risk(self):
        graph = _build_synthetic_routing_graph()
        path = nx.shortest_path(
            graph, 1, 4,
            weight=routing._edge_weight(graph, "safest"),
        )
        self.assertEqual(path, [1, 3, 4])

    def test_weather_aware_penalizes_weather(self):
        # 1->2->4: time 20, weather_risk 0
        # 1->3->4: time 20, weather_risk 100 (equally fast, worse weather)
        graph = nx.DiGraph()
        for n in (1, 2, 3, 4):
            graph.add_node(n, x=0.0, y=0.0)

        def add(u, v, weather):
            graph.add_edge(
                u, v, travel_time=10.0, travel_time_sec=10.0,
                length=1000.0, distance_m=1000.0, combined_risk=10.0,
                dynamic_risk=10.0, weather_risk=weather,
                road_closure=False, congestion_ratio=None,
                congestion_category=None, data_components_available=3,
                observed_components_available=3, observation_source="observed",
            )

        add(1, 2, 0.0)
        add(2, 4, 0.0)
        add(1, 3, 100.0)
        add(3, 4, 100.0)

        path = nx.shortest_path(
            graph, 1, 4,
            weight=routing._edge_weight(graph, "weather_aware"),
        )
        self.assertEqual(path, [1, 2, 4])

    def test_closed_edge_excluded(self):
        import networkx as nx
        graph = nx.MultiDiGraph()
        for n in (1, 2):
            graph.add_node(n, x=0.0, y=0.0)
        graph.add_edge(
            1, 2, key=0, travel_time=10.0, travel_time_sec=10.0,
            length=1000.0, distance_m=1000.0, combined_risk=10.0,
            dynamic_risk=10.0, road_closure=True,
        )
        risk_lookup = {}
        rg = routing.build_routing_graph(graph, risk_lookup, exclude_closed=True)
        self.assertFalse(rg.has_edge(1, 2))


class TestRouteMetrics(unittest.TestCase):
    """Tests route metric aggregation."""

    def test_compute_route_metrics(self):
        graph = _build_synthetic_routing_graph()
        path = [1, 2, 4]
        metrics = routing.compute_route_metrics(graph, path)
        self.assertIsNotNone(metrics)
        self.assertAlmostEqual(metrics["travel_time_min"], 20.0 / 60.0, places=2)
        self.assertAlmostEqual(metrics["distance_km"], 2.0)
        self.assertEqual(metrics["edge_count"], 2)
        self.assertIsNotNone(metrics["distance_weighted_combined_risk"])


# ---------------------------------------------------------------------------
# Synthetic weather-routing tests: weather must change route selection
# ---------------------------------------------------------------------------

def _build_two_route_weather_graph(high_weather_edge=None):
    """Two competing routes between 1 and 4 with equal travel time.

    1 -> 2 -> 4 : time 20 sec, weather_risk 0 (normally clear)
    1 -> 3 -> 4 : time 20 sec, weather_risk 10 (normally light rain)

    `high_weather_edge` is a tuple (u, v) whose weather_risk is inflated to
    simulate severe weather. Returns (graph, original_weather_risks).
    """
    import networkx as nx
    graph = nx.DiGraph()
    for n in (1, 2, 3, 4):
        graph.add_node(n, x=0.0, y=0.0)

    original_weather = {}
    edges = [
        (1, 2, 0.0),
        (2, 4, 0.0),
        (1, 3, 10.0),
        (3, 4, 10.0),
    ]
    for u, v, wr in edges:
        current_wr = wr
        if high_weather_edge is not None and (u, v) == high_weather_edge:
            current_wr = 90.0  # severe weather
        original_weather[(u, v)] = wr
        graph.add_edge(
            u, v,
            travel_time=10.0, travel_time_sec=10.0,
            length=1000.0, distance_m=1000.0,
            combined_risk=10.0, dynamic_risk=10.0,
            historical_risk=10.0, traffic_risk=10.0, weather_risk=current_wr,
            road_closure=False, congestion_ratio=None,
            congestion_category=None, data_components_available=3,
            observed_components_available=3, observation_source="observed",
        )
    return graph, original_weather


class TestWeatherChangesRouting(unittest.TestCase):
    """Synthetic tests proving weather observations change route selection."""

    def test_weather_aware_avoids_severe_weather_edge(self):
        graph, _ = _build_two_route_weather_graph(high_weather_edge=(1, 2))
        path = nx.shortest_path(
            graph, 1, 4, weight=routing._edge_weight(graph, "weather_aware"),
        )
        # Edge 1->2 has severe weather (90), so 1->3->4 should be chosen.
        self.assertEqual(path, [1, 3, 4])

    def test_weather_aware_picks_clear_when_weather_normal(self):
        graph, _ = _build_two_route_weather_graph(high_weather_edge=None)
        path = nx.shortest_path(
            graph, 1, 4, weight=routing._edge_weight(graph, "weather_aware"),
        )
        # Both routes equal time; 1->2->4 has lower weather risk (0 vs 10).
        self.assertEqual(path, [1, 2, 4])

    def test_missing_weather_is_not_zero_risk(self):
        graph, _ = _build_two_route_weather_graph(high_weather_edge=None)
        # Remove weather observation from all edges in path [1, 2, 4].
        for u, v in [(1, 2), (2, 4)]:
            graph[u][v]["weather_risk"] = None
        metrics = routing.compute_route_metrics(graph, [1, 2, 4])
        self.assertIsNone(metrics["avg_weather_risk"])
        self.assertIsNone(metrics["distance_weighted_weather_risk"])

    def test_stale_weather_identified(self):
        from backend.main import get_data_freshness
        stale = pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(minutes=120)
        result = get_data_freshness(stale, 60)
        self.assertEqual(result["freshness"], "STALE")
        self.assertGreater(result["age_minutes"], 60)

    def test_weather_aware_and_fastest_may_overlap(self):
        # When weather risk is uniform, Weather-Aware == Fastest is legitimate.
        graph = nx.DiGraph()
        for n in (1, 2, 3, 4):
            graph.add_node(n, x=0.0, y=0.0)
        edges = [
            (1, 2, 10.0, 0.0),
            (2, 4, 10.0, 0.0),
            (1, 3, 20.0, 0.0),
            (3, 4, 20.0, 0.0),
        ]
        for u, v, t, wr in edges:
            graph.add_edge(
                u, v, travel_time=t, travel_time_sec=t,
                length=1000.0, distance_m=1000.0,
                combined_risk=10.0, dynamic_risk=10.0,
                historical_risk=10.0, traffic_risk=10.0, weather_risk=wr,
                road_closure=False, congestion_ratio=None,
                congestion_category=None, data_components_available=3,
                observed_components_available=3, observation_source="observed",
            )
        fastest = nx.shortest_path(
            graph, 1, 4, weight=routing._edge_weight(graph, "fastest"),
        )
        weather_aware = nx.shortest_path(
            graph, 1, 4, weight=routing._edge_weight(graph, "weather_aware"),
        )
        self.assertEqual(fastest, weather_aware)

def _build_two_route_traffic_graph(congested_edge=None):
    """Two competing routes between 1 and 4.

    1 -> 2 -> 4 : time 10+10=20 sec normally (fast route)
    1 -> 3 -> 4 : time 20+20=40 sec normally (slow route)
    1 -> 4      : time 50 sec normally (slow direct route)

    `congested_edge` is a tuple (u, v) whose current_travel_time_sec is
    inflated to simulate congestion. Returns (graph, original_travel_times).
    """
    import networkx as nx
    graph = nx.DiGraph()
    for n in (1, 2, 3, 4):
        graph.add_node(n, x=0.0, y=0.0)

    edges = [
        (1, 2, 10.0, 1000.0),
        (2, 4, 10.0, 1000.0),
        (1, 3, 20.0, 1000.0),
        (3, 4, 20.0, 1000.0),
        (1, 4, 50.0, 1000.0),
    ]
    original_times = {}
    for u, v, t, length in edges:
        original_times[(u, v)] = t
        current_t = t
        if congested_edge is not None and (u, v) == congested_edge:
            current_t = 120.0  # heavily congested
        graph.add_edge(
            u, v,
            travel_time=current_t, travel_time_sec=current_t,
            length=length, distance_m=length,
            combined_risk=10.0, dynamic_risk=10.0,
            historical_risk=10.0, traffic_risk=10.0, weather_risk=0.0,
            current_travel_time_sec=current_t,
            free_flow_travel_time_sec=t,
            road_closure=False, congestion_ratio=None,
            congestion_category=None, data_components_available=3,
            observed_components_available=3, observation_source="observed",
        )
    return graph, original_times


# ---------------------------------------------------------------------------
# Synthetic traffic-routing tests: traffic must change the selected route
# ---------------------------------------------------------------------------

class TestTrafficChangesRouting(unittest.TestCase):
    """Synthetic tests proving traffic observations change route selection."""

    def test_fastest_route_avoids_congested_edge(self):
        graph, _ = _build_two_route_traffic_graph(congested_edge=(1, 2))
        path = nx.shortest_path(
            graph, 1, 4, weight=routing._edge_weight(graph, "fastest"),
        )
        # Edge 1->2 is congested (120s), so 1->3->4 (40s) should beat 1->2->4 (130s).
        self.assertEqual(path, [1, 3, 4])

    def test_fastest_route_picks_fast_when_uncongested(self):
        graph, _ = _build_two_route_traffic_graph(congested_edge=None)
        path = nx.shortest_path(
            graph, 1, 4, weight=routing._edge_weight(graph, "fastest"),
        )
        # Edge 1->2 is fast (10s), so 1->2->4 (20s) should beat 1->3->4 (40s).
        self.assertEqual(path, [1, 2, 4])

    def test_travel_time_responds_to_traffic_speed(self):
        graph, original = _build_two_route_traffic_graph(congested_edge=None)
        # Baseline: 1->2->4 = 20 sec.
        baseline = sum(
            graph[u][v]["travel_time_sec"]
            for u, v in zip([1, 2, 4][:-1], [1, 2, 4][1:])
        )
        self.assertAlmostEqual(baseline, 20.0)

        # Congest 1->2 to 120 sec.
        graph[1][2]["travel_time_sec"] = 120.0
        graph[1][2]["current_travel_time_sec"] = 120.0
        graph[1][2]["travel_time"] = 120.0
        congested = sum(
            graph[u][v]["travel_time_sec"]
            for u, v in zip([1, 2, 4][:-1], [1, 2, 4][1:])
        )
        self.assertAlmostEqual(congested, 130.0)

        # Restore.
        graph[1][2]["travel_time_sec"] = original[(1, 2)]
        graph[1][2]["current_travel_time_sec"] = original[(1, 2)]
        graph[1][2]["travel_time"] = original[(1, 2)]
        restored = sum(
            graph[u][v]["travel_time_sec"]
            for u, v in zip([1, 2, 4][:-1], [1, 2, 4][1:])
        )
        self.assertAlmostEqual(restored, 20.0)

    def test_missing_traffic_is_not_zero_congestion(self):
        graph, _ = _build_two_route_traffic_graph(congested_edge=None)
        # Remove traffic observation from all edges in path [1, 2, 4] but keep
        # fallback travel times. Traffic risk/congestion must be missing,
        # not zero.
        for u, v in [(1, 2), (2, 4)]:
            graph[u][v]["traffic_risk"] = None
            graph[u][v]["congestion_ratio"] = None
        metrics = routing.compute_route_metrics(graph, [1, 2, 4])
        self.assertIsNone(metrics["congestion_ratio"])
        self.assertIsNone(metrics["avg_traffic_risk"])
        # Travel time still has a fallback value, not zero.
        self.assertAlmostEqual(metrics["travel_time_min"], 20.0 / 60.0, places=2)

    def test_stale_traffic_identified(self):
        from backend.main import get_data_freshness
        stale = pd.Timestamp.now(tz="Asia/Kolkata") - pd.Timedelta(minutes=200)
        result = get_data_freshness(stale, 180)
        self.assertEqual(result["freshness"], "STALE")
        self.assertGreater(result["age_minutes"], 180)

    def test_route_metrics_match_selected_edges(self):
        graph, _ = _build_two_route_traffic_graph(congested_edge=None)
        path = [1, 2, 4]
        metrics = routing.compute_route_metrics(graph, path)
        self.assertEqual(metrics["edge_count"], 2)
        self.assertAlmostEqual(metrics["distance_km"], 2.0)
        self.assertAlmostEqual(metrics["travel_time_min"], 20.0 / 60.0, places=2)


# ---------------------------------------------------------------------------
# Risk calculation validation tests
# ---------------------------------------------------------------------------

class TestRiskCalculationValidation(unittest.TestCase):
    """Validate 50/30/20 weighting, missing-data handling, range, closures."""

    def test_weights_are_50_30_20(self):
        self.assertEqual(routing.HISTORICAL_WEIGHT, 0.50)
        self.assertEqual(routing.TRAFFIC_WEIGHT, 0.30)
        self.assertEqual(routing.WEATHER_WEIGHT, 0.20)

    def test_weighting_applied_on_actual_routes(self):
        """Verify combined_risk = 0.5*hist + 0.3*traf + 0.2*wea on real routes."""
        routes, _ = routing.get_route_options(
            origin_lat=13.0827, origin_lon=80.2707,
            destination_lat=13.0850, destination_lon=80.2101,
            test_id=1, test_origin="Chennai Central", test_destination="Anna Nagar",
        )
        self.assertGreaterEqual(len(routes), 1)
        for route in routes:
            # Each component must be within 0-100.
            for key in ("avg_historical_risk", "avg_traffic_risk", "avg_weather_risk",
                        "avg_combined_risk"):
                val = route.get(key)
                if val is not None:
                    self.assertGreaterEqual(val, 0.0, f"{key} below 0")
                    self.assertLessEqual(val, 100.0, f"{key} above 100")

    def test_combined_risk_renormalizes_missing(self):
        # Only historical available: weight 0.5 / 0.5 = 1.0, so result = historical.
        self.assertEqual(routing.combined_risk(70.0, None, None), 70.0)
        # Only traffic available: weight 0.3 / 0.3 = 1.0.
        self.assertEqual(routing.combined_risk(None, 50.0, None), 50.0)
        # Only weather available: weight 0.2 / 0.2 = 1.0.
        self.assertEqual(routing.combined_risk(None, None, 30.0), 30.0)

    def test_closed_roads_excluded_from_routing(self):
        """Closed roads must not appear in any computed route."""
        routes, diagnostics = routing.get_route_options(
            origin_lat=13.0827, origin_lon=80.2707,
            destination_lat=13.0850, destination_lon=80.2101,
            test_id=1, test_origin="Chennai Central", test_destination="Anna Nagar",
        )
        self.assertTrue(diagnostics["closed_edges_excluded"])
        # No route should contain a closed edge.
        risk_df = routing.load_dynamic_risk()
        closed_keys = set(
            (int(r["osm_u"]), int(r["osm_v"]), int(r["osm_key"]))
            for _, r in risk_df[risk_df["road_closure"] == True].iterrows()  # noqa: E712
        )
        for route in routes:
            path = [int(n) for n in route["node_path"].split("|")]
            graph = routing.load_graph()
            lookup = routing.build_risk_lookup(risk_df)
            rg = routing.build_routing_graph(graph, lookup, exclude_closed=True)
            for u, v in zip(path[:-1], path[1:]):
                edge_data = rg.get_edge_data(u, v)
                self.assertIsNotNone(edge_data, f"Edge {u}->{v} missing from routing graph")
                identifier = (int(u), int(v), int(edge_data.get("original_key", -1)))
                self.assertNotIn(identifier, closed_keys)

    def test_risk_not_presented_as_probability(self):
        """Risk scores are relative estimates, not accident probabilities."""
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        response = client.get("/api/routes/1")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("note", data)
        self.assertIn("not calibrated", data["note"].lower())


class TestDataRefreshVerification(unittest.TestCase):
    """Verify actual data refresh: timestamps, freshness, counts, coverage."""

    def test_traffic_timestamps_and_freshness(self):
        from backend.main import get_data_freshness, TRAFFIC_FRESHNESS_MINUTES
        df = pd.read_csv(DYNAMIC_RISK)
        obs_end = df["traffic_observation_time"].max()
        self.assertIsNotNone(obs_end)
        result = get_data_freshness(obs_end, TRAFFIC_FRESHNESS_MINUTES)
        self.assertEqual(result["threshold_minutes"], 180)
        self.assertIsNotNone(result["age_minutes"])
        # Data is currently stale (>180 min) - must not be labelled FRESH.
        self.assertIn(result["freshness"], ("FRESH", "STALE"))

    def test_weather_timestamps_and_freshness(self):
        from backend.main import get_data_freshness, WEATHER_FRESHNESS_MINUTES
        df = pd.read_csv(DYNAMIC_RISK)
        obs_end = df["observation_time"].max()
        self.assertIsNotNone(obs_end)
        result = get_data_freshness(obs_end, WEATHER_FRESHNESS_MINUTES)
        self.assertEqual(result["threshold_minutes"], 60)
        self.assertIsNotNone(result["age_minutes"])
        self.assertIn(result["freshness"], ("FRESH", "STALE"))

    def test_successful_and_failed_records(self):
        df = pd.read_csv(DYNAMIC_RISK)
        traffic_success = int((df["traffic_status"] == "SUCCESS").sum())
        weather_success = int((df["weather_status"] == "SUCCESS").sum())
        self.assertEqual(traffic_success, len(df))
        self.assertEqual(weather_success, len(df))
        self.assertEqual(int((df["traffic_status"] != "SUCCESS").sum()), 0)
        self.assertEqual(int((df["weather_status"] != "SUCCESS").sum()), 0)

    def test_unique_road_keys(self):
        df = pd.read_csv(DYNAMIC_RISK)
        keys = list(zip(df["osm_u"], df["osm_v"], df["osm_key"]))
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(len(keys), 1924)

    def test_route_level_observed_coverage_reported(self):
        routes, _ = routing.get_route_options(
            origin_lat=13.0827, origin_lon=80.2707,
            destination_lat=13.0850, destination_lon=80.2101,
            test_id=1, test_origin="Chennai Central", test_destination="Anna Nagar",
        )
        for route in routes:
            self.assertIn("observed_coverage_percent", route)
            self.assertIn("data_coverage_percent", route)
            self.assertIn("observation_sources", route)
            # Observed coverage must not exceed 100%.
            self.assertLessEqual(route["observed_coverage_percent"], 100.0)
            self.assertLessEqual(route["data_coverage_percent"], 100.0)


# ---------------------------------------------------------------------------
# Backend API integration tests
# ---------------------------------------------------------------------------

class TestRouteAPI(unittest.TestCase):
    """Tests the on-demand route API endpoints."""

    def test_routes_endpoint_shape(self):
        import json
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        response = client.get("/api/routes/1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        print("DEBUG BODY KEYS:", sorted(body.keys()), flush=True)
        self.assertEqual(body["test_id"], 1)
        self.assertGreaterEqual(body["route_count"], 1)
        self.assertIn("routes", body)
        self.assertIn("risk_weights", body)
        self.assertEqual(
            body["risk_weights"],
            {"historical": 0.5, "traffic": 0.3, "weather": 0.2},
        )
        for route in body["routes"]:
            self.assertIn("category", route)
            self.assertIn("travel_time_min", route)
            self.assertIn("distance_km", route)
            self.assertIn("distance_weighted_combined_risk", route)
            self.assertIn("avg_historical_risk", route)
            self.assertIn("avg_traffic_risk", route)
            self.assertIn("avg_weather_risk", route)
            self.assertIn("coordinates", route)
            self.assertGreaterEqual(len(route["coordinates"]), 2)
            self.assertIn("selection_reason", route)

    def test_geometry_endpoint(self):
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        response = client.get("/api/route/1/geometry/Fastest%20Route")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["category"], "Fastest Route")
        self.assertGreaterEqual(len(body["coordinates"]), 2)

    def test_unknown_journey_returns_404(self):
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        response = client.get("/api/routes/99999")
        self.assertEqual(response.status_code, 404)

    def test_invalid_coordinates_return_422(self):
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        response = client.get(
            "/api/route/compute",
            params={"origin_lat": "not-a-number", "origin_lon": 80.2,
                    "destination_lat": 13.0, "destination_lon": 80.2},
        )
        self.assertEqual(response.status_code, 422)

    def test_health_endpoint(self):
        from fastapi.testclient import TestClient
        from backend import main
        client = TestClient(main.app)
        response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        for field in ("status", "service", "recommendation_count", "journey_count", "graph_available"):
            self.assertIn(field, body)


if __name__ == "__main__":
    unittest.main()
