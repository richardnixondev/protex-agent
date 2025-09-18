"""
Backend Bridge
--------------
This script acts as a bridge between the edge devices, Slack, and the frontend dashboard.

Main responsibilities:
1. Subscribes to an MQTT broker (Mosquitto or AWS IoT Core) to receive device metrics.
2. Broadcasts device metrics to connected WebSocket clients (e.g., dashboards).
3. Sends alerts and periodic summaries to Slack via webhook.
"""

# ----------------------------
# Standard Library imports
# ----------------------------
import asyncio       # For asynchronous programming (non-blocking tasks)
import json          # For encoding/decoding messages in JSON
import os            # For environment variables
import time          # For timestamps and time-based pruning

# ----------------------------
# Third-party imports
# ----------------------------
import aiohttp       # For sending HTTP requests to Slack
from gmqtt import Client as MQTTClient   # Async MQTT client library
from websockets import serve             # WebSocket server (>= v10)
from dotenv import load_dotenv           # Load environment variables from .env

# ----------------------------
# Load environment variables
# ----------------------------
load_dotenv()

# ----------------------------
# MQTT Configuration
# ----------------------------
MQTT_BROKER = os.getenv("MQTT_BROKER")             # AWS IoT endpoint or Mosquitto host
MQTT_PORT   = int(os.getenv("MQTT_PORT", "8883"))  # Default port for TLS MQTT
TOPIC       = os.getenv("TOPIC", "devices/+/metrics")  # Subscribe to all device metrics

# ----------------------------
# WebSocket Configuration
# ----------------------------
WS_HOST = os.getenv("WS_HOST", "0.0.0.0")          # WebSocket server binds to all interfaces
WS_PORT = int(os.getenv("WS_PORT", "6789"))        # Port for frontend connections

# ----------------------------
# Application Configurations
# ----------------------------
PRUNE_SECONDS   = int(os.getenv("PRUNE_SECONDS", "30"))  # Only keep devices active in last 30s
CPU_ALERT_TH    = float(os.getenv("CPU_ALERT_TH", "90")) # Alert threshold for CPU usage
SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")       # Slack webhook for notifications
SUMMARY_INTERVAL = int(os.getenv("SUMMARY_INTERVAL", "60")) # Summary every 60 seconds

# ----------------------------
# State
# ----------------------------
clients      = set()  # Active WebSocket clients
device_state = {}     # Stores last metrics per device_id
last_seen    = {}     # Tracks last update time per device_id


def active_snapshot():
    """
    Returns only devices that are "active".
    Active means: updated within the last PRUNE_SECONDS.
    """
    now = time.time()
    return {
        did: payload
        for did, payload in device_state.items()
        if (now - last_seen.get(did, 0)) <= PRUNE_SECONDS
    }


# ----------------------------
# WebSocket Handler
# ----------------------------
async def ws_handler(websocket):
    """
    Handles new WebSocket connections from frontends.
    - Adds new client to the set.
    - Immediately sends the current snapshot (if available).
    - Keeps connection alive until it closes.
    """
    clients.add(websocket)
    print(f"[WS] connected. total={len(clients)}")
    try:
        snap = active_snapshot()
        if snap:
            print(f"[WS] sending initial snapshot with {len(snap)} devices")
            await websocket.send(json.dumps(snap))

        async for _ in websocket:
            pass  # We ignore messages from the frontend, only push updates
    except Exception as e:
        print(f"[WS ERROR] {e}")
    finally:
        clients.discard(websocket)
        print(f"[WS] disconnected. total={len(clients)}")


# ----------------------------
# Slack Integration
# ----------------------------
async def post_slack(text: str):
    """
    Sends a text message to Slack via webhook.
    Used for CPU alerts and periodic summaries.
    """
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


# ----------------------------
# MQTT Loop
# ----------------------------
async def mqtt_loop():
    """
    Connects to MQTT broker and subscribes to device metrics.
    Handles incoming messages and broadcasts them to WebSocket clients.
    """
    client = MQTTClient("backend-bridge")

    # Callback when connected
    def on_connect(c, flags, rc, properties):
        print(f"[MQTT] CONNECTED rc={rc}, flags={flags}, props={properties}")
        try:
            c.subscribe(TOPIC, qos=1)
            print(f"[MQTT] SUBSCRIBE request sent to {TOPIC}")
        except Exception as e:
            print(f"[MQTT ERROR] failed to subscribe: {e}")

    # Callback when disconnected
    def on_disconnect(c, packet, exc=None):
        print(f"[MQTT] DISCONNECTED. packet={packet}, exc={exc}")

    # Callback when subscription acknowledged
    def on_subscribe(c, mid, qos, properties):
        print(f"[MQTT] SUBSCRIBED mid={mid}, qos={qos}, props={properties}")

    # Callback for messages
    def on_message(_c, topic, payload, _qos, _properties):
        """
        Handle metrics sent by devices.
        - Parse JSON payload
        - Store state
        - Broadcast to WebSocket clients
        - Send Slack alert if CPU too high
        """
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

        # Broadcast to WebSocket clients
        if clients:
            msg = json.dumps({device_id: data})
            print(f"[WS] broadcasting update for {device_id} to {len(clients)} clients")
            for ws in list(clients):
                try:
                    asyncio.create_task(ws.send(msg))
                except Exception as e:
                    print(f"[WS ERROR] failed to send to client: {e}")
                    clients.discard(ws)

        # Slack alert if CPU too high
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

    # TLS setup for AWS IoT Core
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

    # Keep loop alive
    while True:
        await asyncio.sleep(1)


# ----------------------------
# Slack Summary Loop
# ----------------------------
async def slack_summary_loop():
    """
    Periodically sends a summary of active devices to Slack.
    Useful for monitoring at-a-glance system health.
    """
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


# ----------------------------
# Main Entry Point
# ----------------------------
async def main():
    """Start WebSocket server, MQTT loop, and Slack summary loop concurrently."""
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
