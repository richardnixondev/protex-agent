"""
Backend bridge:
- Subscribes to MQTT broker (Mosquitto / AWS IoT Core).
- Broadcasts device metrics to WebSocket clients.
- Sends alerts and summaries to Slack via webhook.
"""

import asyncio
import json
import os
import time
import aiohttp
from gmqtt import Client as MQTTClient
from websockets import serve  # correct import for websockets >= 10
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# MQTT configs
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT"))
TOPIC = os.getenv("TOPIC")

# WebSocket configs
WS_HOST = os.getenv("WS_HOST")
WS_PORT = int(os.getenv("WS_PORT"))

# App configs
PRUNE_SECONDS = int(os.getenv("PRUNE_SECONDS"))
CPU_ALERT_TH = float(os.getenv("CPU_ALERT_TH"))
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SUMMARY_INTERVAL = 60  # seconds, how often to post a summary

clients = set()
device_state = {}  # device_id -> last payload
last_seen = {}  # device_id -> epoch seconds


def active_snapshot():
    """Return only devices that have updated within PRUNE_SECONDS."""
    now = time.time()
    return {
        did: payload
        for did, payload in device_state.items()
        if (now - last_seen.get(did, 0)) <= PRUNE_SECONDS
    }


async def ws_handler(websocket):
    """Handle WebSocket connections and broadcast initial snapshot."""
    clients.add(websocket)
    print(f"WS connected. total={len(clients)}")
    try:
        snap = active_snapshot()
        if snap:
            await websocket.send(json.dumps(snap))

        # keep the connection alive, ignore incoming messages from frontend
        async for _ in websocket:
            pass
    finally:
        clients.discard(websocket)
        print(f"WS disconnected. total={len(clients)}")


async def post_slack(text: str):
    """Send a notification to Slack using the webhook."""
    if not SLACK_WEBHOOK_URL:
        print("[SLACK] Webhook URL not configured")
        return
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(
                SLACK_WEBHOOK_URL, json={"text": text}, timeout=10
            )
            body = await resp.text()
            print(f"[SLACK] status={resp.status}, body={body}")
    except aiohttp.ClientError as err:
        print(f"[SLACK] network error: {err}")
    except Exception as err:  # pylint: disable=broad-exception-caught
        print(f"[SLACK] unexpected error: {err}")


async def mqtt_loop():
    """Main MQTT loop: subscribes and processes messages."""
    client = MQTTClient("backend-bridge")

    async def on_message(_c, _topic, payload, _qos, _properties):
        """Handle incoming MQTT messages from devices."""
        try:
            raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
            data = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return

        device_id = data.get("device_id", "unknown")
        device_state[device_id] = data
        last_seen[device_id] = time.time()

        # broadcast to all connected frontends
        if clients:
            msg = json.dumps({device_id: data})
            targets = [ws for ws in list(clients) if ws.open]
            if targets:
                await asyncio.gather(
                    *(ws.send(msg) for ws in targets), return_exceptions=True
                )

        # 🚨 send Slack alert if CPU usage is too high
        cpu = data.get("cpu_percent")
        if isinstance(cpu, (int, float)) and cpu >= CPU_ALERT_TH:
            text = (
                f":rotating_light: CPU ALERT at {device_id} — "
                f"CPU {cpu:.1f}%, RAM {data.get('mem_percent')}% "
            )
            asyncio.create_task(post_slack(text))

    client.on_message = on_message
    await client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(TOPIC, qos=1)

    while True:
        await asyncio.sleep(1)


async def slack_summary_loop():
    """Periodically send a summary of active devices to Slack."""
    while True:
        await asyncio.sleep(SUMMARY_INTERVAL)
        snapshot = active_snapshot()
        if not snapshot:
            continue

        # build formatted block
        lines = ["Metrics summary (last minute):", ""]
        for did, data in snapshot.items():
            lines.append(
                f"{did:15} | CPU {data.get('cpu_percent', '?')}% "
                f"| RAM {data.get('mem_percent', '?')}% "
                f"| Disk {data.get('disk_percent', '?')}% "
                f"| GPU {data.get('gpu_percent', '?')}"
            )

        formatted = "```\n" + "\n".join(lines) + "\n```"
        await post_slack(formatted)


async def main():
    """Start WebSocket server, MQTT loop, and Slack summary loop."""
    async with serve(ws_handler, WS_HOST, WS_PORT):
        print(f"WebSocket running at ws://{WS_HOST}:{WS_PORT}")
        await asyncio.gather(
            mqtt_loop(),
            slack_summary_loop()
        )


if __name__ == "__main__":
    asyncio.run(main())
