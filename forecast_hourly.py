#!/usr/bin/env python3
import os
import requests
import pandas as pd
from datetime import datetime
import pytz
from pysolar.solar import get_altitude
import joblib
import math
import sqlite3

# -----------------------------
# CONFIGURATION
# -----------------------------
LAT, LON = 2.3098, 111.8304
API_KEY = "***********************************"
MODEL_PATH = os.path.expanduser("~/Documents/solar-ai/models/solar_correction_model.pkl")
TIMEZONE = pytz.timezone("Asia/Kuala_Lumpur")
DB_PATH = os.path.expanduser("~/Documents/solar-ai/data/solar_forecast.db")

#-----------------------------
# Database functions
#-----------------------------
def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Table for hourly forecast
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hourly_forecast (
            datetime TEXT PRIMARY KEY,
            predicted_power_W REAL,
            irradiance REAL,
            temp_air REAL,
            sun_altitude_deg REAL
        )
    """)

    # Table for daily forecast
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_forecast (
            date TEXT PRIMARY KEY,
            predicted_daily_yield_Wh REAL,
            clouds REAL,
            sun_hours REAL,
            temp_day REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_forecast_48hours (
            date TEXT PRIMARY KEY,
            predicted_daily_yield_Wh REAL,
            updated_at TEXT
        )
    """)

    conn.commit()
    conn.close()

def save_hourly_forecast(hourly_results):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for r in hourly_results:
        cursor.execute("""
            INSERT OR REPLACE INTO hourly_forecast
            (datetime, predicted_power_W, irradiance, temp_air, sun_altitude_deg)
            VALUES (?, ?, ?, ?, ?)
        """, (
            r["datetime"].strftime("%Y-%m-%d %H:%M"),
            r["predicted_power_W"],
            r["irradiance"],
            r["temp_air"],
            r["sun_altitude_deg"]
        ))

    conn.commit()
    conn.close()
    print("✅ Hourly forecast saved to DB")

def save_daily_forecast(daily_7days_summary):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    for d in daily_7days_summary:
        cursor.execute("""
            INSERT OR REPLACE INTO daily_forecast
            (date, predicted_daily_yield_Wh, clouds, sun_hours, temp_day)
            VALUES (?, ?, ?, ?, ?)
        """, (
            str(d["date"]),
            d["predicted_daily_yield_Wh"],
            d["clouds"],
            d["sun_hours"],
            d["temp_day"]
        ))

    conn.commit()
    conn.close()
    print("✅ Daily forecast saved to DB")

def save_daily_forecast_48hours(daily_summary):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    for d in daily_summary:
        date_str = str(d["date"])
        yield_wh = float(d["predicted_daily_yield_Wh"])
        updated_at = datetime.now().isoformat()

        cur.execute("""
            INSERT OR REPLACE INTO daily_forecast_48hours
            (date, predicted_daily_yield_Wh, updated_at)
            VALUES (?, ?, ?)
        """, (date_str, yield_wh, updated_at))

    conn.commit()
    conn.close()
    print("✅ Daily forecast based on 48 hours saved to database.")

# -----------------------------
# HELPER FUNCTIONS
# -----------------------------
def compute_irradiance(clouds, lat, lon, unix_time):
    """Estimate irradiance from sun angle and cloud cover."""
    dt = datetime.fromtimestamp(unix_time, tz=pytz.UTC)
    sun_angle = get_altitude(lat, lon, dt)
    if sun_angle > 0:
        # More realistic irradiance: proportional to sin of sun altitude
        clear_sky_irr = 1000 * math.sin(math.radians(sun_angle))

        # Apply cloud reduction: 0–100% → fractional reduction
        cloudy_irr = clear_sky_irr * (1 - clouds / 100.0)

        return max(0.0, cloudy_irr), sun_angle
    return 0.0, 0.0

DISABLE_WEATHER_API = False

def get_hourly_weather_forecast(lat, lon, api_key):
    if DISABLE_WEATHER_API:
        print("⏸️ Weather API disabled")
        return []
    
    """Fetch hourly forecast (next 48h) from OpenWeatherMap One Call 3.0."""
    url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&exclude=minutely,daily,alerts,current&units=metric&appid={api_key}"
    try:
        data = requests.get(url).json()
        if "hourly" not in data:
            print("⚠️ No 'hourly' data in response:", data)
            return []

        hourly_forecasts = []
        for h in data["hourly"]:
            unix_time = h["dt"]
            dt_local = datetime.fromtimestamp(unix_time, tz=TIMEZONE)
            clouds = h.get("clouds", 0)
            temp = h.get("temp", 25.0)
            irr, alt = compute_irradiance(clouds, lat, lon, unix_time)

            hourly_forecasts.append({
                "datetime": dt_local,
                "hour": dt_local.hour + dt_local.minute / 60,
                "irradiance": irr,
                "temp_air": temp,
                "sun_altitude_deg": alt
            })
        return hourly_forecasts

    except Exception as e:
        print("Forecast fetch error:", e)
        return []

def predict_hourly_power(model, hourly_forecasts):
    """Predict hourly power and compute daily yield."""
    results = []
    for h in hourly_forecasts:
             
        # Predict using physical model instead of ML model
        panel_area = 0.016485
        panel_efficiency = 0.17
        temp_coeff = -0.0045  # PV efficiency drop per °C above 25°C
        
        # Base power from sunlight only
        power_W = h["irradiance"] * panel_area * panel_efficiency

        # Temperature derating (hot = less efficient)
        temp_factor = 1 + temp_coeff * max(0, h["temp_air"] - 25)
        power_W *= temp_factor

        # === Hybrid ML Correction ===
        irradiance = h.get("irradiance", 0)
        temp_air = h.get("temp_air", 25)
        hour = h["datetime"].hour + h["datetime"].minute / 60

        X = pd.DataFrame([{
            "irradiance": irradiance,
            "temp_air": temp_air,
            "hour": hour
        }])

        correction_factor = model.predict(X)[0]
        correction_factor = max(-0.5, min(0.5, correction_factor))  # slight clamp optional

        pred_power = max(0, power_W * (1 + correction_factor))
        
        results.append({
            "datetime": h["datetime"],
            "predicted_power_W": round(pred_power, 3),
            "irradiance": round(h["irradiance"], 2),
            "temp_air": h["temp_air"],
            "sun_altitude_deg": round(h["sun_altitude_deg"], 2)
        })

    return results

DISABLE_DAILY_FORECAST_API = False

def get_daily_energy_forecast(model, lat, lon, api_key):
    if DISABLE_DAILY_FORECAST_API:
        print("⏸️ Daily Weather API disabled")
        return []
    
    """Fetch daily forecast (next 7 days) from OpenWeatherMap One Call 3.0."""
    url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&exclude=minutely,hourly,alerts,current&units=metric&appid={api_key}"
    try:
        data = requests.get(url).json()
        if "daily" not in data:
            print("⚠️ No 'daily' data in response:", data)
            return []

        forecasts = []

        panel_power_W = 5
        #panel_area = 0.016485
        panel_efficiency = 0.17
        temp_coeff = -0.0045  
        tracking_gain = 1.25

        # ✅ Calculate panel area from power rating (physics-based)
        panel_area = panel_power_W / (1000 * panel_efficiency)

        for d in data["daily"]:
            date = datetime.fromtimestamp(d["dt"], tz=TIMEZONE).date()
            clouds = d.get("clouds", 70)
            temp_day = d.get("temp", {}).get("day", 25.0)       

            # ✅ Estimate usable sun hours (more realistic than your version)
            max_sun_hours = 6.5
            
            # Minimum useful irradiance fraction even at 100 % clouds
            # ensures small but nonzero generation
            cloud_factor = max(0.15, 1 - clouds / 120)

            sun_hours = max(0.5, cloud_factor * max_sun_hours)
            
            # ✅ Total daily irradiance in kWh/m² (not just mid-day!)
            daily_irradiance_kWh_per_m2 = cloud_factor * max_sun_hours * 1.0  # 1 kW/m² clear-sky assumption

            # ✅ Energy hitting the panel
            incident_energy_kWh = daily_irradiance_kWh_per_m2 * panel_area

            # ✅ Convert to Wh & apply efficiency
            daily_Wh = incident_energy_kWh * 1000 * panel_efficiency

            # ✅ Temperature adjustment
            temp_factor = 1 + temp_coeff * max(0, temp_day - 25)
            daily_Wh *= temp_factor

            # ✅ ML model correction (mid-day conditions assumption)
            X = pd.DataFrame([{
                "irradiance": 1000,
                "temp_air": temp_day,
                "hour": 12
            }])
            correction_factor = max(-0.25, min(0.25, model.predict(X)[0]))
            daily_Wh *= (1 + correction_factor)

            # ✅ Dual-axis tracking performance boost
            daily_Wh *= tracking_gain

            # ✅ Clamp impossible negatives
            daily_Wh = max(0.2, min(daily_Wh, 25))            

            forecasts.append({
                "date": date,
                "predicted_daily_yield_Wh": round(daily_Wh, 2),
                "clouds": clouds,
                "sun_hours": round(sun_hours, 2),
                "temp_day": temp_day
            })

        return forecasts

    except Exception as e:
        print("Daily forecast fetch error:", e)
        return []

def summarize_daily_yield(hourly_results):
    if not hourly_results:
        print("⚠️ No hourly results to summarize.")
        return []
    
    #Group hourly power into daily Wh totals.
    df = pd.DataFrame(hourly_results)

    if "datetime" not in df.columns or "predicted_power_W" not in df.columns:
        print("⚠️ Missing required columns in hourly results DataFrame.")
        return []
    
    df["date"] = df["datetime"].dt.date
    # Integrate power (W) × 1 hour = Wh
    daily_yield = df.groupby("date")["predicted_power_W"].sum().reset_index()
    daily_yield.rename(columns={"predicted_power_W": "predicted_daily_yield_Wh"}, inplace=True)
    return daily_yield.to_dict(orient="records")


# -----------------------------
# MAIN SCRIPT
# -----------------------------
if __name__ == "__main__":
    init_db()

    if not os.path.exists(MODEL_PATH):
        print("❌ No trained model found.")
        exit(1)

    model = joblib.load(MODEL_PATH)
    forecast = get_hourly_weather_forecast(LAT, LON, API_KEY)
    hourly_results = predict_hourly_power(model, forecast)
    daily_summary = summarize_daily_yield(hourly_results)
    
    daily_7days_summary = get_daily_energy_forecast(model, LAT, LON, API_KEY)

    print("\n=== Solar Energy Forecast (Next 48 Hours) ===")
    for r in hourly_results[:24]:  # show first 24h sample
        print(f"{r['datetime']:%Y-%m-%d %H:%M} → {r['predicted_power_W']} W, Irradiance: {r['irradiance']} W/m², Temp: {r['temp_air']} °C, Sun Altitude: {r['sun_altitude_deg']}°")

    save_hourly_forecast(hourly_results)

    print("\n=== Daily Energy Yield Based on 48-hour Forecast Summary ===")
    for d in daily_summary:
        print(f"{d['date']}: {round(d['predicted_daily_yield_Wh'], 2)} Wh")
    
    save_daily_forecast_48hours(daily_summary)
    
    print("\n=== Daily Solar Energy Yield Forecast For 7 Days ===")
    for d in daily_7days_summary:
        print(f"{d['date']}: {round(d['predicted_daily_yield_Wh'], 2)} Wh, Clouds: {d['clouds']}%, Estimated Sun Hours: {d['sun_hours']} h, Temp: {d['temp_day']} °C")
    
    save_daily_forecast(daily_7days_summary)
