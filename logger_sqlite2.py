# logger_sqlite_tracker_csv.py
import serial
import sqlite3
from datetime import datetime

# --- CONFIG ---
SERIAL_PORT = "/dev/ttyUSB0"   # adjust if needed (/dev/ttyACM0 sometimes)
BAUD_RATE = 9600
DB_FILE = "/home/pi/Documents/solar-ai/data/solar_tracker.db"

# --- SETUP SQLITE ---
conn = sqlite3.connect(DB_FILE)
conn.execute("PRAGMA journal_mode=WAL;")  # Enable concurrent access
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tracker_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    lt INTEGER,
    rt INTEGER,
    ld INTEGER,
    rd INTEGER,
    h_angle INTEGER,
    v_angle INTEGER,
    v_panel REAL,
    i_panel REAL,
    p_panel REAL
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS energy_forecast (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT,
    location_lat REAL,
    location_lon REAL,
    irradiance REAL,         -- from weather API (W/m²)
    temp_air REAL,           -- ambient temperature (°C)
    predicted_power_W REAL,  -- instantaneous AI-predicted power
    energy_yield_Wh REAL     -- accumulated or forecasted yield (Wh)
)
""")
conn.commit()

# --- SETUP SERIAL ---
ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=1)
print("[OK] CSV Logger started. Waiting for Arduino data...")

try:
    while True:
        line = ser.readline().decode("utf-8").strip()
        if line and not line.startswith("//"):  # ignore comments/header
            try:
                parts = line.split(",")
                if len(parts) == 9:
                    lt, rt, ld, rd, h_angle, v_angle, v_panel, i_panel, p_panel = parts

                    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    cursor.execute("""
                        INSERT INTO tracker_readings 
                        (timestamp, lt, rt, ld, rd, h_angle, v_angle, v_panel, i_panel, p_panel)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        ts, int(lt), int(rt), int(ld), int(rd),
                        int(h_angle), int(v_angle),
                        float(v_panel), float(i_panel), float(p_panel)
                    ))
                    conn.commit()
                    print(f"[{ts}] Saved row → {line}")
            except Exception as e:
                print("Parse error:", e, " | Line:", line)

except KeyboardInterrupt:
    print("\n[STOP] Logger stopped by user.")
finally:
    ser.close()
    conn.close()
