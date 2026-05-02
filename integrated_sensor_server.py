import os
from datetime import datetime

import mysql.connector
from flask import Flask, jsonify, request, send_from_directory

# ================= DATABASE CONFIG =================
DB_CONFIG = {
    "host": os.getenv("MYSQL_HOST", "localhost"),
    "port": int(os.getenv("MYSQL_PORT", "3306")),
    "user": os.getenv("MYSQL_USER", "root"),
    "password": os.getenv("MYSQL_PASSWORD", "Aditya"),
    "database": os.getenv("MYSQL_DATABASE", "pump_monitoring"),
}

TABLE_NAME = "integrated_sensor_readings"

app = Flask(__name__)

# ================= CORS =================
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# ================= DATABASE =================
def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)

def create_database_if_missing():
    config = DB_CONFIG.copy()
    db = config.pop("database")

    conn = mysql.connector.connect(**config)
    cur = conn.cursor()
    cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}`")
    cur.close()
    conn.close()

def create_table_if_missing():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            temperature FLOAT NULL,
            humidity FLOAT NULL,
            soil_moisture FLOAT NULL,
            soil_raw_value FLOAT NULL,
            ph FLOAT NULL,
            ph_raw_value FLOAT NULL,
            nitrogen FLOAT NULL,
            phosphorus FLOAT NULL,
            potassium FLOAT NULL,
            source VARCHAR(50) NOT NULL,
            received_at DATETIME NOT NULL
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

# ================= HELPERS =================
def read_number(data, *keys):
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return float(data[key])
    return None

def clamp(value, minimum=0.0, maximum=100.0):
    return max(minimum, min(maximum, value))

def raw_soil_to_percent(raw_value):
    dry_raw = int(os.getenv("SOIL_DRY_RAW", "4095"))
    wet_raw = int(os.getenv("SOIL_WET_RAW", "1200"))

    percent = (dry_raw - raw_value) * 100 / (dry_raw - wet_raw)
    return clamp(percent)

# ================= PARSE =================
def parse_sensor_payload(data, source="combined"):

    soil_moisture = read_number(data, "soil_moisture", "soilMoisture", "moisture", "percent")
    soil_raw_value = read_number(data, "soil_raw_value", "soilRaw", "raw_soil")

    ph = read_number(data, "ph", "pH")
    ph_raw_value = read_number(data, "ph_raw_value", "phRaw")

    reading = {
        "temperature": read_number(data, "temperature", "temp"),
        "humidity": read_number(data, "humidity", "hum"),
        "soil_moisture": round(clamp(soil_moisture), 2) if soil_moisture else None,
        "soil_raw_value": soil_raw_value,
        "ph": ph,
        "ph_raw_value": ph_raw_value,
        "nitrogen": read_number(data, "nitrogen", "n"),
        "phosphorus": read_number(data, "phosphorus", "p"),
        "potassium": read_number(data, "potassium", "k"),
        "source": source,
    }

    if not any(v is not None for k, v in reading.items() if k != "source"):
        raise KeyError("No sensor values")

    return reading

# ================= INSERT =================
def insert_reading(reading):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(f"""
        INSERT INTO {TABLE_NAME}
        (temperature, humidity, soil_moisture, soil_raw_value,
         ph, ph_raw_value, nitrogen, phosphorus, potassium, source, received_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        reading["temperature"],
        reading["humidity"],
        reading["soil_moisture"],
        reading["soil_raw_value"],
        reading["ph"],
        reading["ph_raw_value"],
        reading["nitrogen"],
        reading["phosphorus"],
        reading["potassium"],
        reading["source"],
        datetime.now()
    ))

    conn.commit()
    last_id = cur.lastrowid
    cur.close()
    conn.close()
    return last_id

# ================= DEBUG SAVE =================
def save_payload(source):
    data = request.get_json(silent=True) or {}

    print("\n==============================")
    print("📡 INCOMING DATA FROM ESP32")
    print("Raw:", data)
    print("==============================\n")

    if not data:
        print("❌ No data received")
        return jsonify({"error": "No data"}), 400

    try:
        reading = parse_sensor_payload(data, source)
        print("✅ Parsed:", reading)

        rid = insert_reading(reading)
        print(f"💾 Stored in DB ID: {rid}")

    except Exception as e:
        print("❌ ERROR:", str(e))
        return jsonify({"error": str(e)}), 400

    return jsonify({"message": "saved", "id": rid}), 201

# ================= ROUTES =================

@app.route("/")
def home():
    return "Server Running 🚀"

@app.route("/health")
def health():
    return {"status": "ok"}

@app.route("/debug", methods=["POST"])
def debug():
    data = request.get_json()
    print("🔥 DEBUG HIT:", data)
    return {"status": "received"}

@app.route("/api/sensors", methods=["POST"])
def sensors():
    return save_payload("combined")

@app.route("/api/readings")
def readings():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    cur.execute(f"SELECT * FROM {TABLE_NAME} ORDER BY id DESC LIMIT 20")
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return jsonify(rows)

# ================= MAIN =================
if __name__ == "__main__":
    print("🚀 Starting Server...")
    print("👉 POST URL: /api/sensors")
    print("👉 Health: /health")

    create_database_if_missing()
    create_table_if_missing()

    app.run(host="0.0.0.0", port=5010, debug=True)