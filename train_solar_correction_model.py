import sqlite3
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from joblib import dump
from datetime import datetime

DB_PATH = "/home/pi/Documents/solar-ai/data/solar_tracker.db"

# --- Load both tables ---
conn = sqlite3.connect(DB_PATH)

df_measured = pd.read_sql_query("""
    SELECT timestamp, p_panel AS measured_power_W
    FROM tracker_readings
    WHERE p_panel > 0
""", conn)

df_forecast = pd.read_sql_query("""
    SELECT timestamp, irradiance, temp_air
    FROM energy_forecast
    WHERE irradiance > 0
""", conn)

conn.close()

# --- Convert timestamps to datetime ---
df_measured["datetime"] = pd.to_datetime(df_measured["timestamp"])
df_forecast["datetime"] = pd.to_datetime(df_forecast["timestamp"])

# --- Merge (nearest timestamp match, within 10 minutes tolerance) ---
df = pd.merge_asof(
    df_measured.sort_values("datetime"),
    df_forecast.sort_values("datetime"),
    on="datetime",
    direction="nearest",
    tolerance=pd.Timedelta("10m")
)

# --- Drop missing or unmatched rows ---
df = df.dropna(subset=["irradiance", "temp_air", "measured_power_W"])

# --- Add hour feature ---
df["hour"] = df["datetime"].dt.hour + df["datetime"].dt.minute / 60

# --- Compute baseline physical model ---
panel_area = 0.016485
panel_efficiency = 0.17

df["baseline_power"] = df["irradiance"] * panel_area * panel_efficiency

df = df[df["irradiance"] > 200]  # strong daylight only

# --- Correction factor (what ML learns) ---
df["correction_factor"] = (df["measured_power_W"] - df["baseline_power"]) / df["baseline_power"]

# --- Train ML model ---
X = df[["irradiance", "temp_air", "hour"]]
y = df["correction_factor"]

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

model = RandomForestRegressor(n_estimators=200, random_state=42)
model.fit(X_train, y_train)

# --- Save model ---
dump(model, "/home/pi/Documents/solar-ai/models/solar_correction_model.pkl")
print("✅ Model trained and saved as solar_correction_model.pkl")

# --- Optional: Evaluate briefly ---
score = model.score(X_test, y_test)
print(f"✅ Model R² score: {score:.3f}")
print(df.head())
