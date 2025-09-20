import asyncio
import json
import os
import ssl
import subprocess
import time
import psutil
from gmqtt import Client as MQTTClient
from dotenv import load_dotenv
from collections import deque

# Load environment variables
load_dotenv()

DEVICE_ID = os.getenv("DEVICE_ID", "device-iot-001")
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
CA_CERT = os.getenv("CA_CERT", "AmazonRootCA1.pem")
CLIENT_CERT = os.getenv("CLIENT_CERT", "device.cert.pem")
CLIENT_KEY = os.getenv("CLIENT_KEY", "device.private.key")
INTERVAL = int(os.getenv("INTERVAL", "10"))
TOPIC = f"devices/{DEVICE_ID}/metrics"

# Queue for unsent metrics (max 1000 items to avoid memory explosion)
offline_queue = deque(maxlen=1000)

process = psutil.Process(os.getpid())


def collect_metrics():
    """Collect CPU, RAM, Disk, GPU (if available) and agent self-metrics."""
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage("/").percent

    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ]
        ).decode().strip()
        gpu_util, _, _ = out.split(",")
        gpu = float(gpu_util)
    except Exception:
        gpu = None

    agent_mem = process.memory_info().rss / (1024 * 1024)
    agent_cpu = process.cpu_percent(interval=None)

    return {
        "device_id": DEVICE_ID,
        "timestamp": int(time.time()),
        "cpu_percent": cpu,
        "mem_percent": mem,
        "disk_percent": disk,
        "gpu_percent": gpu,
        "agent_cpu_percent": agent_cpu,
        "agent_mem_mb": agent_mem,
    }


async def main():
    client = MQTTClient(DEVICE_ID)

    def on_connect(_client, _flags, _rc, _properties):
        print(f"[{DEVICE_ID}] ✅ Connected to AWS IoT Core")

    def on_disconnect(_client, _packet, _exc=None):
        print(f"[{DEVICE_ID}] ❌ Disconnected from AWS IoT Core")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_verify_locations(CA_CERT)
    ssl_ctx.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)

    await client.connect(MQTT_BROKER, MQTT_PORT, ssl=ssl_ctx)

    try:
        while True:
            metrics = collect_metrics()

            if metrics["cpu_percent"] > 90:
                print(f"⚠️ WARN: CPU > 90% ({metrics['cpu_percent']}%)")

            print(
                f"[DEBUG] agent_cpu={metrics['agent_cpu_percent']}%, "
                f"agent_mem={metrics['agent_mem_mb']:.2f} MB"
            )

            payload = json.dumps(metrics)

            try:
                # First: flush offline queue
                while offline_queue:
                    queued = offline_queue.popleft()
                    print(f"[QUEUE] Resending queued metric: {queued[:60]}...")
                    client.publish(TOPIC, queued, qos=1, retain=False)

                # Then: publish current metric
                client.publish(TOPIC, payload, qos=1, retain=False)

            except Exception as e:
                # If publish fails, push to offline queue
                offline_queue.append(payload)
                print(f"[QUEUE] Failed to send, stored in queue (size={len(offline_queue)}) | Error: {e}")

            await asyncio.sleep(INTERVAL)

    except asyncio.CancelledError:
        print(f"[{DEVICE_ID}] Agent cancelled")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
