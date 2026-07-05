# SHH Reader

A small reader that brings a bedside monitor online — plug it in, and its
readings show up live in [Smart Home Health](https://smarthomehealth.org).

The Reader runs on a small computer (a Raspberry Pi works great) sitting next
to the monitor. It listens to the monitor over the cable the monitor already
uses, shows the current readings on its own simple display page, and sends
them on to your Smart Home Health app — no typing, no writing numbers down.

## Supported monitors

| Device | Connection |
| --- | --- |
| Mindray PM-1000N pulse oximeter | USB serial or LAN |
| Mindray PM-100N pulse oximeter | USB serial |

Readings captured: SpO₂, heart rate, and perfusion.

Have a different monitor? [Ask us to support it](https://smarthomehealth.org/#request)
— sample output from the device helps a lot.

## How it works

```
bedside monitor ──serial/LAN──▶ SHH Reader ──encrypted WebSocket──▶ Smart Home Health app
                                    │
                                    └─▶ optional MQTT (Home Assistant, etc.)
```

- **Connections** (`connections/`): reads raw lines from the monitor over USB
  serial or a LAN TCP listener.
- **Devices** (`devices/`): a small driver per monitor model parses those lines
  into readings.
- **Transports** (`transport/`): sends readings to the app over an encrypted
  WebSocket, and optionally publishes them to an MQTT broker too.
- **Web UI** (`routes/`, `templates/`, `static/`): a setup page and a clear
  bedside display of the live numbers, served on port 8080.

Settings are saved locally, so after a restart or power cut the Reader picks
up where it left off and starts reading again on its own.

## Quick start with Docker

No cloning or building needed — a ready-made image is published for both
regular PCs (amd64) and Raspberry Pi (arm64). Create a `docker-compose.yml`:

```yaml
services:
  reader:
    image: ghcr.io/smart-home-health/shh-reader:latest
    ports:
      - "8080:8080"   # web UI / bedside display
      - "5001:5001"   # LAN-connected monitors stream here
    volumes:
      - shh-data:/app/data
#    devices:
#      - /dev/ttyUSB0:/dev/ttyUSB0   # uncomment for USB-connected monitors
    restart: unless-stopped

volumes:
  shh-data:
```

Then:

```bash
docker compose up -d
```

Open `http://<reader-address>:8080` in a browser, pick your monitor model
and connection, and point it at your Smart Home Health app.

Prefer a fixed version over `latest`? Every release is also tagged, e.g.
`ghcr.io/smart-home-health/shh-reader:0.1.0`.

**Using a USB-connected monitor?** Uncomment the `devices:` lines so the
container can see the serial port.

**Using a LAN-connected monitor?** The Reader listens for it on port 5001
(already exposed in the compose file).

### Building from source instead

```bash
git clone https://github.com/Smart-Home-Health/shh-reader.git
cd shh-reader
docker compose up -d --build
```

## Running without Docker

Python 3.12+:

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Adding a device driver

Each supported monitor is one small class in `devices/` that extends
`BaseDevice` and implements `parse_line()` — turning a raw line of the
monitor's serial output into a readings dict. Pull requests welcome; if you
can capture some raw output from your device, that's most of the work.

## Part of Smart Home Health

The Reader is one piece of [Smart Home Health](https://smarthomehealth.org),
a free, open-source system for families and caregivers:

- [platform](https://github.com/Smart-Home-Health/platform)
  — the app: medications, vitals, tasks, records, and alerts in one place.
- **shh-reader** (this repo) — brings bedside monitors online.

## License

[AGPL-3.0](LICENSE) © John Carty
