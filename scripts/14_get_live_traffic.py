import os
import sys
import requests
from dotenv import load_dotenv


# ============================================================
# SAFEROUTE - LIVE TOMTOM TRAFFIC ENGINE
# ============================================================

load_dotenv()

API_KEY = os.getenv("TOMTOM_API_KEY")

if not API_KEY:
    print("ERROR: TOMTOM_API_KEY not found in .env")
    sys.exit(1)


# Chennai test location
LATITUDE = 13.0827
LONGITUDE = 80.2707

URL = (
    "https://api.tomtom.com/traffic/services/4/"
    "flowSegmentData/absolute/10/json"
)


def get_traffic(lat, lon):

    params = {
        "point": f"{lat},{lon}",
        "unit": "KMPH",
        "key": API_KEY,
    }

    response = requests.get(
        URL,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data["flowSegmentData"]


def calculate_congestion(current_speed, free_flow_speed):

    if current_speed is None:
        return None

    if free_flow_speed is None or free_flow_speed <= 0:
        return None

    congestion = 1 - (
        current_speed / free_flow_speed
    )

    # Prevent negative congestion
    # and cap extreme values.
    congestion = max(0.0, min(1.0, congestion))

    return congestion


def calculate_traffic_risk(congestion):

    if congestion is None:
        return None

    return congestion * 100


def classify_traffic_risk(traffic_risk):

    if traffic_risk < 15:
        return "LOW"

    elif traffic_risk < 35:
        return "MEDIUM"

    elif traffic_risk < 60:
        return "HIGH"

    else:
        return "SEVERE"


print("=" * 70)
print("SAFEROUTE - LIVE TOMTOM TRAFFIC ENGINE")
print("=" * 70)

print()
print("Location : Chennai")
print(f"Latitude : {LATITUDE}")
print(f"Longitude: {LONGITUDE}")

print()
print("Fetching live traffic...")

try:

    flow = get_traffic(
        LATITUDE,
        LONGITUDE
    )

    current_speed = flow.get("currentSpeed")
    free_flow_speed = flow.get("freeFlowSpeed")
    current_travel_time = flow.get("currentTravelTime")
    free_flow_travel_time = flow.get("freeFlowTravelTime")
    confidence = flow.get("confidence")
    road_closure = flow.get("roadClosure")

    congestion = calculate_congestion(
        current_speed,
        free_flow_speed
    )

    traffic_risk = calculate_traffic_risk(
        congestion
    )

    traffic_category = classify_traffic_risk(
        traffic_risk
    )

    print()
    print("LIVE TRAFFIC")
    print("-" * 70)

    print(
        f"Current Speed        : "
        f"{current_speed} km/h"
    )

    print(
        f"Free Flow Speed      : "
        f"{free_flow_speed} km/h"
    )

    print(
        f"Current Travel Time  : "
        f"{current_travel_time} sec"
    )

    print(
        f"Free Flow Travel Time: "
        f"{free_flow_travel_time} sec"
    )

    print(
        f"Confidence           : "
        f"{confidence}"
    )

    print(
        f"Road Closure         : "
        f"{road_closure}"
    )

    print()
    print("DERIVED TRAFFIC FEATURES")
    print("-" * 70)

    print(
        f"Congestion Ratio     : "
        f"{congestion:.4f}"
    )

    print(
        f"Congestion           : "
        f"{congestion * 100:.2f}%"
    )

    print(
        f"Traffic Risk         : "
        f"{traffic_risk:.2f}/100"
    )

    print(
        f"Traffic Category     : "
        f"{traffic_category}"
    )

    print()
    print("=" * 70)
    print("TRAFFIC DATA COLLECTION SUCCESSFUL")
    print("=" * 70)


except requests.exceptions.Timeout:

    print()
    print("ERROR: TomTom request timed out.")

except requests.exceptions.HTTPError as e:

    print()
    print(f"ERROR: TomTom API HTTP error: {e}")

except requests.exceptions.RequestException as e:

    print()
    print(f"ERROR: Network request failed: {e}")

except Exception as e:

    print()
    print(f"ERROR: {e}")