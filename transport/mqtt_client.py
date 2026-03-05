"""Optional MQTT publisher – sends vitals alongside the WebSocket transport."""

from __future__ import annotations

import asyncio
import json
import logging
import time

import paho.mqtt.client as paho

from app_state import state

log = logging.getLogger(__name__)


def _on_connect(client: paho.Client, _ud, _flags, rc, *_args):
    if rc == 0:
        log.info("MQTT: connected to %s:%s", state.mqtt_broker, state.mqtt_port)
    else:
        log.warning("MQTT: connect failed rc=%s", rc)


def _on_disconnect(client: paho.Client, _ud, *_args):
    log.info("MQTT: disconnected")


async def mqtt_publisher_loop() -> None:
    """Run in its own asyncio Task.  Reads from a dedicated queue and publishes."""
    broker = state.mqtt_broker
    port = state.mqtt_port
    if not broker:
        log.warning("MQTT: no broker configured – publisher exiting")
        return

    client = paho.Client(
        callback_api_version=paho.CallbackAPIVersion.VERSION1,
        client_id=state.mqtt_client_id or "shh-reader",
        protocol=paho.MQTTv311,
    )
    client.on_connect = _on_connect
    client.on_disconnect = _on_disconnect

    if state.mqtt_username:
        client.username_pw_set(state.mqtt_username, state.mqtt_password or None)

    log.info("MQTT: connecting to %s:%s (user=%s)", broker, port, state.mqtt_username or "<none>")

    loop = asyncio.get_running_loop()
    backoff = 2

    while state.is_running and state.mqtt_enabled:
        try:
            # paho connect is blocking – run in executor
            await loop.run_in_executor(None, client.connect, broker, port, 60)
            client.loop_start()
            backoff = 2
            log.info("MQTT: publisher ready")

            while state.is_running and state.mqtt_enabled:
                try:
                    parsed = await asyncio.wait_for(state.mqtt_queue.get(), timeout=5)
                except asyncio.TimeoutError:
                    continue

                payload = json.dumps({
                    "timestamp": time.time(),
                    "spo2": parsed.get("spo2"),
                    "bpm": parsed.get("bpm"),
                    "perfusion": parsed.get("perfusion"),
                    "origin": state.mqtt_client_id or "shh-reader",
                })

                topics = [t for t in (state.mqtt_topic1, state.mqtt_topic2) if t]
                for topic in topics:
                    info = client.publish(topic, payload, qos=1)
                    log.info("MQTT-PUB: topic=%s payload=%s mid=%s", topic, payload, info.mid)

        except asyncio.CancelledError:
            log.info("MQTT: publisher cancelled")
            break
        except Exception as exc:
            log.exception("MQTT: publisher error: %s", exc)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        finally:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass

    log.info("MQTT: publisher loop exited")
