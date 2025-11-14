from flask import Flask, render_template, request, jsonify
import sqlite3
import os
import requests
from datetime import datetime

app = Flask(__name__)

# ✅ Change this to match your SQLite DB location
DB_PATH = os.path.expanduser("~/Documents/solar-ai/data/solar_tracker.db")
DB_PATH = os.path.expanduser("~/Documents/solar-ai/data/solar_forecast.db")

# --- CONFIG ---
WEATHER_API_KEY = "73b147888b61870b0c5ad612821bfd63"  # replace with your actual key
WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def query_db(query, args=()):
    """Helper function to fetch database results as dictionaries"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(query, args)
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.route("/")
def dashboard():

    # ✅ Fetch all chart data
    power_data = query_db(
        "SELECT datetime, predicted_power_W "
        "FROM hourly_forecast ORDER BY datetime ASC"
    )

    daily_data = query_db(
        "SELECT date, predicted_daily_yield_Wh "
        "FROM daily_forecast_48hours ORDER BY date ASC"
    )

    weather_data = query_db(
        "SELECT date, predicted_daily_yield_Wh, clouds, sun_hours, temp_day "
        "FROM daily_forecast ORDER BY date ASC"
    )

    # ✅ Add default coordinates here
    latitude = 2.3098
    longitude = 111.8304

    return render_template(
        "dashboard.html",
        power_data=power_data,
        daily_data=daily_data,
        weather_data=weather_data,
        latitude=latitude,
        longitude=longitude
    )

@app.route("/api/latest")
def api_latest():
    try:
        conn = get_db_connection()
        
        # Get latest measured power
        measured = conn.execute("""
            SELECT timestamp, p_panel AS measured
            FROM tracker_readings
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()
        
        # Get latest predicted power
        predicted = conn.execute("""
            SELECT predicted_power_W AS predicted
            FROM predictions
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()

        # Get latest prediction details (from energy_forecast)
        forecast = conn.execute("""
            SELECT timestamp,
                   energy_yield_Wh AS total_energy,
                   daily_yield_Wh AS daily_energy,
                   solar_altitude_deg AS solar_altitude
            FROM energy_forecast
            ORDER BY timestamp DESC LIMIT 1
        """).fetchone()

        if not measured:
            return jsonify({"error": "No measured data"}), 404

        result = {
            "timestamp": measured["timestamp"],
            "measured": measured["measured"],
            "predicted": predicted["predicted"] if predicted else None,
            "latest_ts_str": forecast["timestamp"] if forecast else None,
            "total_energy": forecast["total_energy"] if forecast else None,
            "daily_energy": forecast["daily_energy"] if forecast else None,
            "solar_altitude": forecast["solar_altitude"] if forecast else None
        }
        print("[DEBUG] Forecast data fetched:", dict(forecast) if forecast else "None")
        return jsonify(result)

    except sqlite3.OperationalError:
        return jsonify({"error": "Database busy, retry"}), 503
    finally:
        if 'conn' in locals():
            conn.close()

# --- NEW WEATHER API ROUTE ---
@app.route("/api/weather")
def api_weather():
    latitude = request.args.get("lat", default=2.3098, type=float)
    longitude = request.args.get("lon", default=111.8304, type=float)

    params = {
        "lat": latitude,
        "lon": longitude,
        "appid": WEATHER_API_KEY,
        "units": "metric"
    }

    try:
        r = requests.get(WEATHER_URL, params=params, timeout=5)
        data = r.json()

        if r.status_code != 200:
            return jsonify({"error": data.get("message", "Weather API error")}), 500

        weather_info = {
            "location": data.get("name", "Unknown"),
            "temperature": data["main"]["temp"],
            "humidity": data["main"]["humidity"],
            "description": data["weather"][0]["description"].capitalize(),
            "icon": data["weather"][0]["icon"],
            "timestamp": datetime.now().isoformat()
        }

        return jsonify(weather_info)
    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 503

# --- NEW GEOCODING API ROUTE ---
@app.route("/api/geocode")
def api_geocode():
    place = request.args.get("place", "")
    if not place:
        return jsonify({"error": "Place name required"}), 400

    GEO_URL = "http://api.openweathermap.org/geo/1.0/direct"
    params = {
        "q": place,
        "limit": 1,
        "appid": WEATHER_API_KEY
    }

    try:
        r = requests.get(GEO_URL, params=params, timeout=5)
        data = r.json()

        if not data:
            return jsonify({"error": f"No location found for '{place}'"}), 404

        location = data[0]
        return jsonify({
            "name": location["name"],
            "lat": location["lat"],
            "lon": location["lon"],
            "country": location.get("country", "")
        })

    except requests.exceptions.RequestException as e:
        return jsonify({"error": str(e)}), 503
    
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
