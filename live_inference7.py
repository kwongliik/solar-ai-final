#!/usr/bin/env python3
import sqlite3
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import r2_score, mean_squared_error
from pysolar.solar import get_altitude # for solar position calculations
from datetime import datetime, timezone
import os
import time
import numpy as np
import requests

# === SETTINGS ===
DB_PATH = os.path.expanduser("~/Documents/solar-ai/data/solar_tracker.db")
MODEL_PATH = os.path.expanduser("~/Documents/solar-ai/models/solar_ai_model.pkl")
RETRAIN_INTERVAL_ROWS = 500
#lat, lon = 3.139, 101.6869   # Example: Kuala Lumpur
lat, lon = 2.3098, 111.8304  # Example: Sibu, Malaysia

# === Load model if exists ===
if os.path.exists(MODEL_PATH):
    model = joblib.load(MODEL_PATH)
    print(f"[{datetime.now()}] Loaded existing model from {MODEL_PATH}")
else:
    model = None
    print(f"[{datetime.now()}] No existing model found — waiting to train...")

# === Weather Data Fetching Function ===
def get_weather_data(lat, lon, api_key):
    url = f"https://api.openweathermap.org/data/3.0/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric"
    try:
        data = requests.get(url).json()
        irradiance = max(0, 1000 * (1 - data["clouds"]["all"]/100))  # rough est. (1000 W/m² at clear sky)
        temp_air = data["main"]["temp"]
        return irradiance, temp_air
    except Exception as e:
        print("Weather fetch error:", e)
        return None, None

# === Feature Engineering Function ===
def feature_engineering(df):
    # --- Match Arduino logic ---
    df["avt"] = (df["lt"] + df["rt"]) / 2.0   # top avg
    df["avd"] = (df["ld"] + df["rd"]) / 2.0   # bottom avg
    df["avl"] = (df["lt"] + df["ld"]) / 2.0   # left avg
    df["avr"] = (df["rt"] + df["rd"]) / 2.0   # right avg

    # Errors same as Arduino
    df["err_tb"] = df["avt"] - df["avd"]   # vertical error
    df["err_lr"] = df["avl"] - df["avr"]   # horizontal error
    df["err_total"] = df["err_lr"].abs() + df["err_tb"].abs()

    # Brightness and time
    df["avg_light"] = df[["lt", "rt", "ld", "rd"]].mean(axis=1)
    df["brightness_norm"] = df["avg_light"] / 1023.0
    df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour

    # Fill missing weather data if any
    if "irradiance" not in df.columns:
        df["irradiance"] = np.nan
    if "temp_air" not in df.columns:
        df["temp_air"] = np.nan

    # Features & target (must match training exactly!)
    features = [
        "avg_light", "err_lr", "err_tb", "err_total",
        "brightness_norm", "hour",
        "h_angle", "v_angle",
        "irradiance", "temp_air"
    ]

    target = "p_panel"

    return df, features, target

def ensure_predictions_table():
    """Create predictions table if not exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")  # Enable concurrent access
    conn.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            timestamp TEXT PRIMARY KEY,
            predicted_power_W REAL
        )
    """)
    conn.commit()
    conn.close()

def retrain_model():
    global model
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")  # Enable concurrent access
    df = pd.read_sql_query("SELECT * FROM tracker_readings", conn)
    conn.close()

    df, features, target = feature_engineering(df)

    if target is None or df[target].isnull().all():
        print(f"[{datetime.now()}] No p_panel data available — skipping retrain.")
        return

    X = df[features]
    y = df[target]

    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X, y)

    y_pred = model.predict(X)
    r2 = r2_score(y, y_pred)
    rmse = np.sqrt(mean_squared_error(y, y_pred))

    joblib.dump(model, MODEL_PATH)
    print(f"[{datetime.now()}] Retrained model → R²={r2:.3f}, RMSE={rmse:.3f} W, saved to {MODEL_PATH}")

def save_prediction(ts, pred_power):
    """Save predicted power with timestamp into predictions table."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")  # Enable concurrent access
    conn.execute("""
        INSERT OR REPLACE INTO predictions (timestamp, predicted_power_W)
        VALUES (?, ?)
    """, (ts, float(pred_power)))
    conn.commit()
    conn.close()

# === Ensure predictions table exists ===
ensure_predictions_table()

# === Main loop ===
while True:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL;")  # Enable concurrent access
    latest_df = pd.read_sql_query(
        "SELECT * FROM tracker_readings ORDER BY timestamp DESC LIMIT 1",
        conn
    )
    total_rows = pd.read_sql_query("SELECT COUNT(*) AS cnt FROM tracker_readings", conn)['cnt'][0]
    conn.close()

    if latest_df.empty:
        time.sleep(1)
        continue
    
    latest_ts_str = str(latest_df['timestamp'].iloc[0])

    irradiance, temp_air = get_weather_data(lat, lon, "************************************")
    print(f"Weather: irradiance={irradiance:.1f} W/m², temp={temp_air:.1f}°C")
    latest_df["irradiance"] = irradiance
    latest_df["temp_air"] = temp_air

    latest_df, features, _ = feature_engineering(latest_df)

    pred_power = 0

    if model is not None:
        solar_altitude = get_altitude(lat, lon, datetime.now(timezone.utc))
        pred_power = max(0, model.predict(latest_df[features])[0])
        print(f"[{datetime.now()}] Predicted Power: {pred_power:.3f} W | Solar Altitude: {solar_altitude:.2f}°")
        save_prediction(latest_ts_str, pred_power)

    # Retrain periodically
    if total_rows % RETRAIN_INTERVAL_ROWS == 0:
        retrain_model()

    # --- Energy calculation ---
    try:
        # Load last predicted energy
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL;")
        df_prev = pd.read_sql_query("SELECT * FROM energy_forecast ORDER BY timestamp DESC LIMIT 1", conn)
        conn.close()

        # Initialize defaults
        prev_energy = 0.0
        prev_daily = 0.0
        prev_date = None

        if not df_prev.empty:
            prev_ts = pd.to_datetime(df_prev["timestamp"].iloc[0])
            prev_date = prev_ts.date()
            prev_energy = float(df_prev.get("energy_yield_Wh", pd.Series([0.0])).infer_objects(copy=False).fillna(0.0).iloc[0])
            prev_daily  = float(df_prev.get("daily_yield_Wh", pd.Series([0.0])).infer_objects(copy=False).fillna(0.0).iloc[0])
        else:
            prev_ts = pd.to_datetime(latest_ts_str)
            prev_energy = 0.0
            prev_daily = 0.0

        now_ts = pd.to_datetime(latest_ts_str)
        now_date = now_ts.date()
        delta_t = (now_ts - prev_ts).total_seconds() / 3600.0  # hours
        delta_energy = pred_power * delta_t  # Wh

        total_energy = max(0, prev_energy + delta_energy)

        # --- Daily energy logic ---
        if prev_date is None or now_date != prev_date:
            # New day starts → reset daily energy
            daily_energy = delta_energy
        else:
            daily_energy = max(0, prev_daily + delta_energy)

        # Save energy + weather + predicted power
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("""
            INSERT INTO energy_forecast 
            (timestamp, location_lat, location_lon, irradiance, temp_air, predicted_power_W, 
             energy_yield_Wh, daily_yield_Wh, solar_altitude_deg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (latest_ts_str, lat, lon, irradiance, temp_air, pred_power, total_energy, daily_energy, solar_altitude))
        conn.commit()
        conn.close()

        print(f"[{datetime.now()}] Yield: +{delta_energy:.6f} Wh → Total {total_energy:.3f} Wh → Daily {daily_energy:.3f} Wh")
    except Exception as e:
        print("Energy calc error:", e)

    time.sleep(3)
