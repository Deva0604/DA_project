import os
import time
import random
import pandas as pd
import requests

from dotenv import load_dotenv
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

INPUT_FILE = "data/processed/road_live_traffic_full.csv"
BACKUP_FILE = "backups/road_live_traffic_before_retry.csv"
OUTPUT_FILE = INPUT_FILE

ENDPOINT = (
    "https://api.tomtom.com/traffic/services/"
    "4/flowSegmentData/absolute/10/json"
)

CHECKPOINT_EVERY = 5
MAX_ATTEMPTS = 4
BASE_DELAY_SECONDS = 3
TIMEOUT_SECONDS = 25

load_dotenv(".env")
api_key = os.getenv("TOMTOM_API_KEY")

if not api_key:
    raise SystemExit("TomTom API key is not configured in .env.")

df = pd.read_csv(INPUT_FILE)

required = {
    "traffic_status",
    "traffic_latitude",
    "traffic_longitude",
    "current_speed_kmh",
    "free_flow_speed_kmh",
    "traffic_risk",
}
missing = required - set(df.columns)

if missing:
    raise SystemExit(f"Missing required columns: {sorted(missing)}")

os.makedirs("backups", exist_ok=True)

if not os.path.exists(BACKUP_FILE):
    df.to_csv(BACKUP_FILE, index=False)
    print("Created pre-retry backup:", BACKUP_FILE)
else:
    print("Existing pre-retry backup preserved:", BACKUP_FILE)

failed_indices = df.index[
    df["traffic_status"].ne("SUCCESS")
].tolist()

print("Total roads:", len(df))
print("Successful roads before retry:", df["traffic_status"].eq("SUCCESS").sum())
print("Roads to retry:", len(failed_indices))

if not failed_indices:
    print("No failed roads to retry.")
    raise SystemExit(0)

session = requests.Session()
session.headers.update({"User-Agent": "SafeRoute/1.0"})

success_count = 0
failure_count = 0

def valid_number(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
    )

try:
    for position, idx in enumerate(failed_indices, start=1):
        row = df.loc[idx]

        lat = row["traffic_latitude"]
        lon = row["traffic_longitude"]

        if pd.isna(lat) or pd.isna(lon):
            df.at[idx, "traffic_error"] = "MISSING_COORDINATES"
            failure_count += 1
            continue

        last_error = None
        updated = False

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = session.get(
                    ENDPOINT,
                    params={
                        "key": api_key,
                        "point": f"{float(lat)},{float(lon)}",
                        "unit": "KMPH",
                    },
                    timeout=TIMEOUT_SECONDS,
                    # Keep normal TLS certificate verification enabled.
                )

                df.at[idx, "traffic_http_status"] = response.status_code

                if response.status_code in (401, 403, 429):
                    last_error = f"HTTP_{response.status_code}"
                    print(
                        f"\nStopping: TomTom returned HTTP "
                        f"{response.status_code}. Check authentication "
                        "or API quota before retrying further."
                    )
                    df.at[idx, "traffic_error"] = last_error
                    raise SystemExit(2)

                if response.status_code != 200:
                    last_error = f"HTTP_{response.status_code}"
                    if response.status_code >= 500 and attempt < MAX_ATTEMPTS:
                        time.sleep(BASE_DELAY_SECONDS * (2 ** (attempt - 1)))
                        continue
                    break

                try:
                    payload = response.json()
                except ValueError:
                    last_error = "INVALID_JSON"
                    break

                flow = payload.get("flowSegmentData")
                if not isinstance(flow, dict):
                    last_error = "MISSING_FLOW_SEGMENT_DATA"
                    break

                current = flow.get("currentSpeed")
                free_flow = flow.get("freeFlowSpeed")

                if (
                    not valid_number(current)
                    or not valid_number(free_flow)
                    or current < 0
                    or free_flow <= 0
                ):
                    last_error = "INVALID_SPEED_DATA"
                    break

                congestion = max(
                    0.0,
                    min(1.0, 1.0 - current / free_flow),
                )

                df.at[idx, "current_speed_kmh"] = current
                df.at[idx, "free_flow_speed_kmh"] = free_flow
                df.at[idx, "current_travel_time_sec"] = (
                    flow.get("currentTravelTime")
                )
                df.at[idx, "free_flow_travel_time_sec"] = (
                    flow.get("freeFlowTravelTime")
                )
                df.at[idx, "traffic_confidence"] = flow.get("confidence")
                df.at[idx, "road_closure"] = flow.get("roadClosure")
                df.at[idx, "congestion_ratio"] = congestion
                df.at[idx, "traffic_risk"] = congestion * 100.0
                df.at[idx, "traffic_status"] = "SUCCESS"
                df.at[idx, "traffic_error"] = None
                df.at[idx, "traffic_observation_time"] = (
                    pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
                )

                updated = True
                break

            except requests.exceptions.RequestException as exc:
                last_error = f"{type(exc).__name__}: {str(exc)[:250]}"

                if attempt < MAX_ATTEMPTS:
                    delay = (
                        BASE_DELAY_SECONDS * (2 ** (attempt - 1))
                        + random.uniform(0, 1)
                    )
                    time.sleep(delay)

        if updated:
            success_count += 1
        else:
            failure_count += 1
            df.at[idx, "traffic_status"] = "FAILED"
            df.at[idx, "traffic_error"] = last_error or "UNKNOWN_ERROR"
            df.at[idx, "traffic_observation_time"] = (
                pd.Timestamp.now(tz="Asia/Kolkata").isoformat()
            )

        if position % CHECKPOINT_EVERY == 0 or position == len(failed_indices):
            print(
                f"Progress {position}/{len(failed_indices)} | "
                f"Recovered this run: {success_count} | "
                f"Still failed this run: {failure_count}"
            )

        time.sleep(1.5)

finally:
    session.close()

# Validate the dataset before publishing it.
import math

if df.empty:
    raise SystemExit("Validation failed: dataset is empty.")

if df.columns.duplicated().any():
    raise SystemExit("Validation failed: duplicate column names.")

if df["traffic_status"].isna().any():
    raise SystemExit("Validation failed: missing traffic statuses.")

allowed_statuses = {"SUCCESS", "FAILED"}
unexpected = set(df["traffic_status"].astype(str)) - allowed_statuses
if unexpected:
    raise SystemExit(f"Validation failed: unexpected statuses: {sorted(unexpected)}")

successful = df["traffic_status"].eq("SUCCESS")

for column in ("current_speed_kmh", "free_flow_speed_kmh", "traffic_risk"):
    values = pd.to_numeric(df.loc[successful, column], errors="coerce")
    if values.isna().any() or not values.map(
        lambda value: math.isfinite(float(value))
    ).all():
        raise SystemExit(f"Validation failed: invalid {column} values.")

current = pd.to_numeric(df.loc[successful, "current_speed_kmh"], errors="coerce")
free_flow = pd.to_numeric(df.loc[successful, "free_flow_speed_kmh"], errors="coerce")
risk = pd.to_numeric(df.loc[successful, "traffic_risk"], errors="coerce")

if (current < 0).any() or (free_flow <= 0).any():
    raise SystemExit("Validation failed: invalid speed ranges.")

if ((risk < 0) | (risk > 100)).any():
    raise SystemExit("Validation failed: traffic risk outside 0–100.")

# Publish only after temporary-file verification.
output_path = Path(OUTPUT_FILE)
temp_path = output_path.with_name(output_path.name + ".tmp")

try:
    df.to_csv(temp_path, index=False)
    check = pd.read_csv(temp_path)

    if len(check) != len(df):
        raise RuntimeError("Temporary-file validation failed: row count mismatch.")

    if list(check.columns) != list(df.columns):
        raise RuntimeError("Temporary-file validation failed: column mismatch.")

    if check["traffic_status"].isna().any():
        raise RuntimeError("Temporary-file validation failed: missing statuses.")

    if not check["traffic_status"].astype(str).reset_index(drop=True).equals(
        df["traffic_status"].astype(str).reset_index(drop=True)
    ):
        raise RuntimeError("Temporary-file validation failed: status mismatch.")

    temp_path.replace(output_path)
except Exception:
    if temp_path.exists():
        temp_path.unlink()
    raise

print("\nRetry complete.")
print("Roads recovered during retry:", success_count)
print("Roads still failing during retry:", failure_count)
print("\nFinal status counts:")
print(df["traffic_status"].value_counts(dropna=False))
print("\nRemaining error types:")
print(
    df.loc[df["traffic_status"] != "SUCCESS", "traffic_error"]
      .value_counts(dropna=False)
)
print("\nUpdated file:", OUTPUT_FILE)
