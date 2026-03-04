import socket
import threading
import json
import re
from datetime import datetime, timezone
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

# =========================
# CONFIG
# =========================

HOST = "0.0.0.0"
PORT = 5001

MQTT_BROKER = "192.168.1.4"
MQTT_PORT = 1883

settings = {
    "client_id": "pulseox"
}

TOPICS = [
    "shh/spo2/state",
    "shh/bpm/state",
    "shh/pa/state"
]


def on_connect(client, userdata, flags, rc):
    status = "connected" if rc == 0 else f"failed (code {rc})"
    print(f"MQTT: {status}")

def on_disconnect(client, userdata, rc):
    print(f"MQTT: disconnected (code {rc})")

def setup_mqtt_client(username=None, password=None):
    client = mqtt.Client(client_id=settings["client_id"])
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    if username:
        client.username_pw_set(username, password)
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
    except Exception as e:
        print(f"MQTT: connection error: {e}")
    client.loop_start()
    return client

# =========================
# LINE PARSER
# =========================

line_pattern = re.compile(
    r"\d{2}-\w{3}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+(\d{2,3}\*?|---)\s+(\d{2,3}\*?|---)\s+(\d+)"
)

def publish_payload(spo2_val, bpm_val, perfusion_val, spo2_alarm=False, bpm_alarm=False):
    timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        "timestamp": timestamp,
        "spo2": spo2_val,
        "spo2_alarm": spo2_alarm,
        "bpm": bpm_val,
        "bpm_alarm": bpm_alarm,
        "perfusion": perfusion_val,
        "origin": settings["client_id"]
    }

    payload_json = json.dumps(payload)

    success = 0
    for topic in TOPICS:
        result = mqtt_client.publish(topic, payload_json)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            success += 1

    print(f"MQTT: {success}/{len(TOPICS)} | Published: {payload_json}")


# =========================
# CONNECTION HANDLER
# =========================

def handle_client(conn, addr):
    print(f"Connected from {addr}")

    buffer = ""

    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break

            buffer += data.decode(errors="ignore")

            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()

                print("Raw:", line)
                match = line_pattern.search(line)
                if not match:
                    continue

                spo2 = match.group(1)
                bpm = match.group(2)
                pa = match.group(3)

                if spo2 == "---" or bpm == "---":
                    continue

                spo2_alarm = spo2.endswith("*")
                bpm_alarm = bpm.endswith("*")

                publish_payload(
                    spo2_val=int(spo2.rstrip("*")),
                    bpm_val=int(bpm.rstrip("*")),
                    perfusion_val=int(pa),
                    spo2_alarm=spo2_alarm,
                    bpm_alarm=bpm_alarm
                )

    except Exception as e:
        print("Client error:", e)

    finally:
        conn.close()
        print(f"Disconnected {addr}")


# =========================
# SERVER LOOP
# =========================

def main():
    load_dotenv()
    username = os.getenv("MQTT_USERNAME")
    password = os.getenv("MQTT_PASSWORD")

    global mqtt_client
    mqtt_client = setup_mqtt_client(username, password)

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(10)

    print(f"Listening on {HOST}:{PORT}")

    while True:
        conn, addr = server.accept()
        thread = threading.Thread(
            target=handle_client,
            args=(conn, addr),
            daemon=True
        )
        thread.start()


if __name__ == "__main__":
    main()