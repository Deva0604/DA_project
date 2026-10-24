import pandas as pd

FILE = "data/raw/accidents/indian_roads_dataset.csv"

df = pd.read_csv(FILE)

print("=" * 60)
print("SAFEROUTE DATASET INSPECTION")
print("=" * 60)

print("\nShape:")
print(df.shape)

print("\nColumns:")
for column in df.columns:
    print(" -", column)

print("\nMissing values:")
print(df.isnull().sum())

print("\nDuplicate rows:")
print(df.duplicated().sum())

print("\nCities:")
print(df["city"].value_counts())

print("\nAccident severity:")
print(df["accident_severity"].value_counts())

print("\nDate range:")
print(df["date"].min(), "to", df["date"].max())

print("\nLatitude:")
print(df["latitude"].min(), "to", df["latitude"].max())

print("\nLongitude:")
print(df["longitude"].min(), "to", df["longitude"].max())