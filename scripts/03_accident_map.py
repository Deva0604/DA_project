import pandas as pd
import folium

# --------------------------------------------------
# 1. Load Chennai accident data
# --------------------------------------------------

FILE = "data/processed/chennai_accidents.csv"

df = pd.read_csv(FILE)

print(f"Loaded {len(df)} Chennai accident records")


# --------------------------------------------------
# 2. Create Chennai map
# --------------------------------------------------

center_lat = df["latitude"].mean()
center_lon = df["longitude"].mean()

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=11,
    tiles="OpenStreetMap"
)


# --------------------------------------------------
# 3. Add accident points
# --------------------------------------------------

severity_colors = {
    "minor": "green",
    "major": "orange",
    "fatal": "red"
}

for _, row in df.iterrows():

    severity = str(row["accident_severity"]).lower()

    color = severity_colors.get(
        severity,
        "blue"
    )

    popup = f"""
    <b>Accident ID:</b> {row['accident_id']}<br>
    <b>Severity:</b> {row['accident_severity']}<br>
    <b>Date:</b> {row['date']}<br>
    <b>Time:</b> {row['time']}<br>
    <b>Weather:</b> {row['weather']}<br>
    <b>Traffic:</b> {row['traffic_density']}<br>
    <b>Road:</b> {row['road_type']}<br>
    <b>Vehicles:</b> {row['vehicles_involved']}<br>
    <b>Casualties:</b> {row['casualties']}<br>
    """

    folium.CircleMarker(
        location=[
            row["latitude"],
            row["longitude"]
        ],
        radius=4,
        color=color,
        fill=True,
        fill_color=color,
        fill_opacity=0.7,
        popup=folium.Popup(
            popup,
            max_width=300
        )
    ).add_to(m)


# --------------------------------------------------
# 4. Save map
# --------------------------------------------------

OUTPUT = "data/processed/chennai_accident_map.html"

m.save(OUTPUT)

print(f"Map saved to: {OUTPUT}")