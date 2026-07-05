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
| Covidien Nellcor PM1000N bedside respiratory monitor | USB serial or LAN |
| Covidien Nellcor PM100N bedside SpO₂ monitor | USB serial |

Readings captured: SpO₂, heart rate, and perfusion.

Have a different monitor? [Ask us to support it](https://smarthomehealth.org/#request)
— sample output from the device helps a lot.

## How it works

```
bedside monitor ──serial/LAN──▶ SHH Reader ──encrypted WebSocket──▶ Smart Home Health app
                                    │
                                    └─▶ optional MQTT (Home Assistant, etc.)
```

The Reader listens to the monitor, shows the live numbers on its own display
page, and sends them securely to your Smart Home Health app. Settings are
saved locally, so after a restart or power cut the Reader picks up where it
left off and starts reading again on its own.

## Setting it up

You don't need to know how to code. The Reader comes as a ready-made package
that Docker downloads and runs for you — there's nothing to build or compile.

**You'll need:**

- A small computer that can stay switched on near the monitor — a Raspberry Pi
  is perfect, but any Windows, Mac, or Linux machine works
- About 15 minutes
- An internet connection for the first setup

### Step 1 — Install Docker

Docker is a free program that downloads and runs the Reader for you.

> **Already running the Smart Home Health app with Docker?** Then you've done
> this before — skip to Step 2.

- **Windows or Mac:** download **Docker Desktop** from
  [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/),
  install it, and start it. Wait until it says it's **running**.
- **Raspberry Pi or Linux:** open a terminal and paste this one line, then
  press Enter:

  ```bash
  curl -fsSL https://get.docker.com | sh
  ```

### Step 2 — Create the Reader's settings file

1. Make a new folder somewhere you'll remember — call it `shh-reader`.
2. Inside that folder, create a plain text file named exactly
   **`docker-compose.yml`**.
3. Copy and paste this into the file, and save it:

```yaml
services:
  reader:
    image: ghcr.io/smart-home-health/shh-reader:latest
    ports:
      - "8080:8080"   # the Reader's own display page
      - "5001:5001"   # network-connected monitors send readings here
    volumes:
      - shh-data:/app/data
#    devices:
#      - /dev/ttyUSB0:/dev/ttyUSB0   # remove the two # signs above if your monitor plugs in by USB
    restart: unless-stopped

volumes:
  shh-data:
```

> **Is your monitor connected by USB cable?** Remove the `#` at the start of
> the two `devices:` lines so the Reader can see the USB port. If your monitor
> connects over your home network instead, leave the file exactly as it is.

### Step 3 — Start the Reader

Open a terminal **inside the folder** you just made:

- **Windows:** open the folder, click the address bar at the top, type `cmd`,
  and press Enter.
- **Mac:** right-click the folder and choose **New Terminal at Folder**.
- **Raspberry Pi / Linux:** open your terminal and `cd` into the folder.

Then copy and paste this line and press Enter:

```bash
docker compose up -d
```

The first time, Docker downloads the Reader — this can take a minute or two.
When the command finishes, the Reader is running and will start itself again
automatically after any restart or power cut.

### Step 4 — Open the Reader's page

Open a web browser and go to:

- **on the same computer:** `http://localhost:8080`
- **from another computer or phone:** `http://` followed by the Reader
  computer's address, then `:8080` — for example `http://192.168.1.42:8080`

Pick your monitor model and how it's connected, press **Start**, and the live
numbers appear. Then pair it with your Smart Home Health app from the app's
Readers page, and approve the request on the Reader's screen when it pops up.

### Updating later

When a new version comes out, run these two lines in the same folder:

```bash
docker compose pull
docker compose up -d
```

Your settings and pairing are kept — the Reader carries on where it left off.

> **Prefer things that never change on their own?** Instead of
> `shh-reader:latest` in your file, you can pin a specific version, like
> `shh-reader:0.1.1`. Then the Reader only updates when you change that line.

## For developers

The code is organized so that adding a new monitor is one small file:

- **Connections** (`connections/`): reads raw lines from the monitor over USB
  serial or a LAN TCP listener.
- **Devices** (`devices/`): a small driver per monitor model parses those lines
  into readings.
- **Transports** (`transport/`): sends readings to the app over an encrypted
  WebSocket, and optionally publishes them to an MQTT broker too.
- **Web UI** (`routes/`, `templates/`, `static/`): a setup page and a clear
  bedside display of the live numbers, served on port 8080.

### Building from source

```bash
git clone https://github.com/Smart-Home-Health/shh-reader.git
cd shh-reader
docker compose up -d --build
```

### Running without Docker

Python 3.12+:

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8080
```

### Running the tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

### Adding a device driver

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
