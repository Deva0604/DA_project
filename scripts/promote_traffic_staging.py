#!/usr/bin/env python3
"""Validate and atomically promote the live-traffic staging file to production.

Safety rules:
  * The production CSV is backed up before any replacement.
  * Staging is rejected unless every required check passes.
  * Promotion uses atomic file replacement (os.replace).
  * On any failure, the staging file is left untouched for inspection/resumption.
"""

import os
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

TARGETS_FILE = ROOT / "data/processed/road_traffic_targets.csv"
STAGING_FILE = ROOT / "data/processed/road_live_traffic_full_refresh_staging.csv"
PRODUCTION_FILE = ROOT / "data/processed/road_live_traffic_full.csv"
BACKUP_DIR = ROOT / "backups"

TRAFFIC_FRESHNESS_MINUTES = 180
CLOCK_SKEW_TOLERANCE_MINUTES = 10

ROAD_KEYS = ["osm_u", "osm_v", "osm_key"]

REQUIRED_TRAFFIC_COLUMNS = [
    "osm_u",
    "osm_v",
    "osm_key",
    "traffic_latitude",
    "traffic_longitude",
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "current_travel_time_sec",
    "free_flow_travel_time_sec",
    "traffic_confidence",
    "road_closure",
    "congestion_ratio",
    "traffic_risk",
    "traffic_status",
    "traffic_observation_time",
    "traffic_http_status",
    "traffic_error",
]

NUMERIC_TRAFFIC_COLUMNS = [
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "current_travel_time_sec",
    "free_flow_travel_time_sec",
    "traffic_confidence",
    "congestion_ratio",
    "traffic_risk",
]


def now_utc():
    return datetime.now(timezone.utc)


def fail(message):
    raise ValueError(message)


def load_csv(path, label):
    if not path.exists():
        fail(f"{label} file not found: {path}")
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        fail(f"Cannot read {label} file {path}: {exc}")
    return df


def validate_staging(staging, targets, now):
    """Run every required staging validation check. Raises on failure."""

    # --- Structure ---
    missing = set(REQUIRED_TRAFFIC_COLUMNS) - set(staging.columns)
    if missing:
        fail(f"Staging missing required columns: {sorted(missing)}")

    if staging.empty:
        fail("Staging dataset is empty.")

    # --- Road keys ---
    if staging[ROAD_KEYS].isna().any().any():
        fail("Staging contains missing road identifiers.")

    if staging.duplicated(ROAD_KEYS).any():
        fail("Staging contains duplicate road keys.")

    # --- Target set equality ---
    target_keys = set(
        zip(targets["osm_u"], targets["osm_v"], targets["osm_key"])
    )
    staging_keys = set(
        zip(staging["osm_u"], staging["osm_v"], staging["osm_key"])
    )

    if len(staging) != len(targets):
        fail(
            f"Staging row count {len(staging)} != target count {len(targets)}. "
            "Refresh is incomplete; refusing to promote."
        )

    if staging_keys != target_keys:
        missing_in_staging = target_keys - staging_keys
        extra_in_staging = staging_keys - target_keys
        details = []
        if missing_in_staging:
            details.append(
                f"{len(missing_in_staging)} target roads missing from staging"
            )
        if extra_in_staging:
            details.append(
                f"{len(extra_in_staging)} unexpected roads in staging"
            )
        fail("Staging road-key set does not match target set: " + "; ".join(details))

    # --- Coordinates ---
    for column in ["traffic_latitude", "traffic_longitude"]:
        staging[column] = pd.to_numeric(staging[column], errors="coerce")
        if staging[column].isna().any():
            fail(f"Staging has missing road coordinates: {column}")
        if not staging[column].between(-90, 90 if column == "traffic_latitude" else 180).all():
            fail(f"Staging has invalid road coordinates: {column}")

    # --- Status: every road must be SUCCESS ---
    if not staging["traffic_status"].eq("SUCCESS").all():
        failed_count = int((staging["traffic_status"] != "SUCCESS").sum())
        fail(f"{failed_count} roads did not return SUCCESS traffic status.")

    # --- Timestamps ---
    timestamps = pd.to_datetime(
        staging["traffic_observation_time"], errors="coerce", utc=True
    )
    if timestamps.isna().any():
        fail("Staging has missing or invalid traffic observation timestamps.")

    # No future timestamps beyond clock-skew tolerance.
    future_cutoff = now + timedelta(minutes=CLOCK_SKEW_TOLERANCE_MINUTES)
    if (timestamps > future_cutoff).any():
        fail("Staging contains future-dated traffic observations.")

    # Freshness: every observation must be within the policy window.
    age_minutes = (now - timestamps).dt.total_seconds() / 60
    if (age_minutes > TRAFFIC_FRESHNESS_MINUTES).any():
        stale_count = int((age_minutes > TRAFFIC_FRESHNESS_MINUTES).sum())
        fail(
            f"{stale_count} traffic observations are older than "
            f"{TRAFFIC_FRESHNESS_MINUTES} minutes. Refresh is stale."
        )
    if (age_minutes < -CLOCK_SKEW_TOLERANCE_MINUTES).any():
        fail("Staging contains traffic observations in the future (beyond skew tolerance).")

    # --- Numeric fields ---
    for column in NUMERIC_TRAFFIC_COLUMNS:
        if column not in staging.columns:
            continue
        values = pd.to_numeric(staging[column], errors="coerce")
        if values.isna().any():
            fail(f"Staging has missing numeric values: {column}")
        if not (values.apply(lambda x: pd.notna(x) and abs(x) != float("inf"))).all():
            fail(f"Staging has non-finite numeric values: {column}")

    # Speeds: current >= 0, free_flow > 0
    current_speed = pd.to_numeric(staging["current_speed_kmh"], errors="coerce")
    free_flow_speed = pd.to_numeric(staging["free_flow_speed_kmh"], errors="coerce")
    if (current_speed < 0).any():
        fail("Staging has negative current_speed_kmh values.")
    if (free_flow_speed <= 0).any():
        fail("Staging has non-positive free_flow_speed_kmh values.")

    # Congestion ratio in [0, 1]
    congestion = pd.to_numeric(staging["congestion_ratio"], errors="coerce")
    if ((congestion < 0) | (congestion > 1)).any():
        fail("Staging has congestion_ratio outside [0, 1].")

    # Traffic risk in [0, 100]
    traffic_risk = pd.to_numeric(staging["traffic_risk"], errors="coerce")
    if ((traffic_risk < 0) | (traffic_risk > 100)).any():
        fail("Staging has traffic_risk outside [0, 100].")

    return staging


def backup_production(production):
    """Create a timestamped backup of the production file."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = now_utc().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"road_live_traffic_full_before_promotion_{timestamp}.csv"
    shutil.copy2(production, backup_path)
    return backup_path


def atomic_replace(staging, production):
    """Atomically replace production with staging via a temp file."""
    temp_file = production.with_suffix(".csv.tmp")
    shutil.copy2(staging, temp_file)
    os.replace(temp_file, production)


def main():
    now = now_utc()

    print("=" * 70)
    print("SAFEROUTE - TRAFFIC STAGING VALIDATION & PROMOTION")
    print("=" * 70)

    targets = load_csv(TARGETS_FILE, "traffic targets")
    staging = load_csv(STAGING_FILE, "traffic staging")

    print(f"Target roads: {len(targets)}")
    print(f"Staging rows: {len(staging)}")

    staging = validate_staging(staging, targets, now)

    print("All staging validation checks passed.")

    # Backup production before promotion.
    backup_path = backup_production(PRODUCTION_FILE)
    print(f"Production backup: {backup_path}")

    # Atomic promotion.
    atomic_replace(STAGING_FILE, PRODUCTION_FILE)

    # Read back and confirm.
    check = pd.read_csv(PRODUCTION_FILE)
    if len(check) != len(staging):
        fail("Promoted production row count does not match staging.")

    if set(zip(check["osm_u"], check["osm_v"], check["osm_key"])) != set(
        zip(staging["osm_u"], staging["osm_v"], staging["osm_key"])
    ):
        fail("Promoted production road-key set does not match staging.")

    print()
    print("TRAFFIC STAGING PROMOTED TO PRODUCTION")
    print(f"Production file: {PRODUCTION_FILE}")
    print(f"Roads promoted: {len(check)}")
    print(f"Backup preserved: {backup_path}")
    print("Atomic replacement complete.")


if __name__ == "__main__":
    main()
