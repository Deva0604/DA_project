import os
import sys
import requests
from dotenv import load_dotenv


# ============================================================
# SAFEROUTE - TOMTOM TRAFFIC API TEST
# ============================================================

load_dotenv()

API_KEY = os.getenv("TOMTOM_API_KEY")

if not API_KEY:
    print("ERROR: TOMTOM_API_KEY not found in .env")
    sys.exit(1)


# Chennai coordinates
LATITUDE = 13.0827
LONGITUDE = 80.2707


# TomTom Traffic Flow Segment Data API
url = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"


params = {
    "point": f"{LATITUDE},{LONGITUDE}",
    "unit": "KMPH",
    "key": API_KEY,
}


print("=" * 70)
print("SAFEROUTE - TOMTOM TRAFFIC API TEST")
print("=" * 70)

print()
print(f"Location : Chennai")
print(f"Latitude : {LATITUDE}")
print(f"Longitude: {LONGITUDE}")
print()

print("Requesting live traffic data...")

try:

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    print()
    print(f"HTTP Status: {response.status_code}")

    if response.status_code != 200:
        print()
        print("TomTom API request failed.")
        print("Response:")
        print(response.text[:1000])
        sys.exit(1)

    data = response.json()

    flow = data.get("flowSegmentData", {})

    print()
    print("SUCCESS!")
    print("-" * 70)

    print(f"Current Speed : {flow.get('currentSpeed')}")
    print(f"Free Flow     : {flow.get('freeFlowSpeed')}")
    print(f"Current Travel Time : {flow.get('currentTravelTime')}")
    print(f"Free Flow Travel Time: {flow.get('freeFlowTravelTime')}")
    print(f"Confidence    : {flow.get('confidence')}")
    print(f"Road Closure  : {flow.get('roadClosure')}")

    print()
    print("=" * 70)


except requests.exceptions.Timeout:

    print()
    print("ERROR: TomTom request timed out.")

except requests.exceptions.RequestException as e:

    print()
    print(f"ERROR: Network/API request failed: {e}")

except Exception as e:

    print()
    print(f"ERROR: {e}")
