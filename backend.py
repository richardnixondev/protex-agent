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
from websockets import serve  # websockets >= 10
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

# MQTT configs
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
TOPIC = os.getenv("TOPIC", "devices/+/metrics")

# WebSocket configs
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")
WS_PORT = int(os.getenv("WS_PORT", "6789"))

# App configs
PRUNE_SECONDS = int(os.getenv("PRUNE_SECONDS", "30"))
CPU_ALERT_TH = float(os.getenv("CPU_ALERT_TH", "90"))
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")
SUMMARY_INTERVAL = int(os.getenv("SUMMARY_INTERVAL", "60"))

clients = set()
device_state = {}
last_seen = {}


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
    print(f"[WS] connected. total={len(clients)}")
    try:
        snap = active_snapshot()
        if snap:
            print(f"[WS] sending initial snapshot with {len(snap)} devices")
            await websocket.send(json.dumps(snap))

        async for _ in websocket:
            pass
    except Exception as e:
        print(f"[WS ERROR] {e}")
    finally:
        clients.discard(websocket)
        print(f"[WS] disconnected. total={len(clients)}")


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
    except Exception as err:
        print(f"[SLACK] unexpected error: {err}")


async def mqtt_loop():
    """Main MQTT loop: subscribes and processes messages."""
    client = MQTTClient("backend-bridge")

    # ---------------- Callbacks (must be sync defs) ----------------
    def on_connect(c, flags, rc, properties):
        print(f"[MQTT] CONNECTED rc={rc}, flags={flags}, props={properties}")
        try:
            c.subscribe(TOPIC, qos=1)
            print(f"[MQTT] SUBSCRIBE request sent to {TOPIC}")
        except Exception as e:
            print(f"[MQTT ERROR] failed to subscribe: {e}")

    def on_disconnect(c, packet, exc=None):
        print(f"[MQTT] DISCONNECTED. packet={packet}, exc={exc}")

    def on_subscribe(c, mid, qos, properties):
        print(f"[MQTT] SUBSCRIBED mid={mid}, qos={qos}, props={properties}")

    def on_message(_c, topic, payload, _qos, _properties):
        """Handle incoming MQTT messages from devices."""
        try:
            raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
            print(f"[MQTT RAW] topic={topic}, payload={raw[:100]}...")
            data = json.loads(raw)
        except Exception as e:
            print(f"[MQTT ERROR] could not parse payload: {e}")
            return

        device_id = data.get("device_id", "unknown")
        device_state[device_id] = data
        last_seen[device_id] = time.time()

        # broadcast to WebSocket clients
        if clients:
            msg = json.dumps({device_id: data})
            print(f"[WS] broadcasting update for {device_id} to {len(clients)} clients")
            for ws in list(clients):
                try:
                    asyncio.create_task(ws.send(msg))
                except Exception as e:
                    print(f"[WS ERROR] failed to send to client: {e}")
                    clients.discard(ws)


        # 🚨 Slack alert if CPU too high
        cpu = data.get("cpu_percent")
        if isinstance(cpu, (int, float)) and cpu >= CPU_ALERT_TH:
            text = (
                f":rotating_light: CPU ALERT at {device_id} — "
                f"CPU {cpu:.1f}%, RAM {data.get('mem_percent')}%"
            )
            print(f"[ALERT] {text}")
            asyncio.create_task(post_slack(text))

    # Attach callbacks
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_subscribe = on_subscribe
    client.on_message = on_message

    try:
        print(f"[MQTT] trying to connect to {MQTT_BROKER}:{MQTT_PORT}")

        import ssl
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.load_verify_locations(os.getenv("CA_CERT"))
        ssl_ctx.load_cert_chain(
            certfile=os.getenv("CLIENT_CERT"),
            keyfile=os.getenv("CLIENT_KEY"),
        )

        await client.connect(
            MQTT_BROKER,
            port=MQTT_PORT,
            ssl=ssl_ctx
        )

        print("[MQTT] connect() call completed")

    except Exception as e:
        print(f"[MQTT ERROR] failed to connect: {e}")
        return

    while True:
        await asyncio.sleep(1)


async def slack_summary_loop():
    """Periodically send a summary of active devices to Slack."""
    while True:
        await asyncio.sleep(SUMMARY_INTERVAL)
        snapshot = active_snapshot()
        if not snapshot:
            print("[SLACK] no active devices to summarize")
            continue

        lines = ["Metrics summary (last interval):", ""]
        for did, data in snapshot.items():
            lines.append(
                f"{did:15} | CPU {data.get('cpu_percent', '?')}% "
                f"| RAM {data.get('mem_percent', '?')}% "
                f"| Disk {data.get('disk_percent', '?')}% "
                f"| GPU {data.get('gpu_percent', '?')}"
            )

        formatted = "```\n" + "\n".join(lines) + "\n```"
        print("[SLACK] sending periodic summary")
        await post_slack(formatted)


async def main():
    """Start WebSocket server, MQTT loop, and Slack summary loop."""
    async with serve(ws_handler, WS_HOST, WS_PORT):
        print(f"[WS] server running at ws://{WS_HOST}:{WS_PORT}")
        await asyncio.gather(
            mqtt_loop(),
            slack_summary_loop(),
        )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Backend stopped by user")
