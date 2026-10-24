import requests


# ============================================================
# SAFEROUTE - OPEN-METEO WEATHER API TEST
# ============================================================

LATITUDE = 13.0827
LONGITUDE = 80.2707

URL = "https://api.open-meteo.com/v1/forecast"

params = {
    "latitude": LATITUDE,
    "longitude": LONGITUDE,
    "current": ",".join([
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "rain",
        "weather_code",
        "wind_speed_10m",
        "wind_direction_10m"
    ]),
    "timezone": "Asia/Kolkata"
}


print("=" * 70)
print("SAFEROUTE - OPEN-METEO WEATHER API TEST")
print("=" * 70)

print()
print("Location : Chennai")
print(f"Latitude : {LATITUDE}")
print(f"Longitude: {LONGITUDE}")
print()

print("Requesting current weather...")

try:

    response = requests.get(
        URL,
        params=params,
        timeout=30
    )

    print()
    print(f"HTTP Status: {response.status_code}")

    response.raise_for_status()

    data = response.json()

    current = data["current"]

    print()
    print("SUCCESS!")
    print("-" * 70)

    print(f"Observation Time : {current.get('time')}")
    print(f"Temperature      : {current.get('temperature_2m')} °C")
    print(f"Humidity         : {current.get('relative_humidity_2m')} %")
    print(f"Precipitation    : {current.get('precipitation')} mm")
    print(f"Rain             : {current.get('rain')} mm")
    print(f"Weather Code     : {current.get('weather_code')}")
    print(f"Wind Speed       : {current.get('wind_speed_10m')} km/h")
    print(f"Wind Direction   : {current.get('wind_direction_10m')}°")

    print()
    print("=" * 70)

except requests.exceptions.Timeout:

    print()
    print("ERROR: Weather request timed out.")

except requests.exceptions.RequestException as e:

    print()
    print(f"ERROR: Weather API request failed: {e}")

except Exception as e:

    print()
    print(f"ERROR: {e}")
