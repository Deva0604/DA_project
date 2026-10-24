import pandas as pd

FILE = "data/raw/accidents/indian_roads_dataset.csv"

df = pd.read_csv(FILE)

# Select Chennai
chennai = df[
    df["city"].astype(str).str.strip().str.lower() == "chennai"
].copy()

print("=" * 60)
print("CHENNAI DATA VALIDATION")
print("=" * 60)

print(f"\nChennai records: {len(chennai)}")

print("\nLatitude range:")
print(f"Min: {chennai['latitude'].min()}")
print(f"Max: {chennai['latitude'].max()}")

print("\nLongitude range:")
print(f"Min: {chennai['longitude'].min()}")
print(f"Max: {chennai['longitude'].max()}")

print("\nBasic statistics:")
print(
    chennai[
        ["latitude", "longitude", "visibility",
         "temperature", "traffic_density",
         "vehicles_involved", "casualties", "risk_score"]
    ].describe()
)

print("\nAccident severity:")
print(chennai["accident_severity"].value_counts())

print("\nWeather:")
print(chennai["weather"].value_counts())

print("\nRoad type:")
print(chennai["road_type"].value_counts())

print("\nTraffic density:")
print(chennai["traffic_density"].value_counts())

print("\nPeak hour:")
print(chennai["is_peak_hour"].value_counts())

print("\nDay of week:")
print(chennai["day_of_week"].value_counts())

# Save Chennai dataset
chennai.to_csv(
    "data/processed/chennai_accidents.csv",
    index=False
)

print("\nSaved:")
print("data/processed/chennai_accidents.csv")