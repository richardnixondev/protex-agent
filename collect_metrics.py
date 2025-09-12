# requirements: psutil, gmqtt
import asyncio
import json
import psutil
import subprocess
import time
import os
from gmqtt import Client as MQTTClient

DEVICE_ID = "device-iot-001"
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
INTERVAL = 10  # frequency of checking in seconds
TOPIC = f"devices/{DEVICE_ID}/metrics"

# get measure agent consumption
process = psutil.Process(os.getpid())


def collect_metrics():
    """Collects CPU, RAM, Disk, GPU and self-metrics (agent)"""
    cpu = psutil.cpu_percent(interval=None)
    mem = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"]
        ).decode().strip()
        gpu_util, mem_used, mem_total = out.split(",")
        gpu = float(gpu_util)
    except Exception:
        gpu = None # If there was no gpu set it to none

    # agent metrics (memory in MB, cpu in %)
    agent_mem = process.memory_info().rss / (1024 * 1024)  # MB
    agent_cpu = process.cpu_percent(interval=None)  # %
    return {
        "device_id": DEVICE_ID,
        "timestamp": int(time.time()),
        "cpu_percent": cpu,
        "mem_percent": mem,
        "disk_percent": disk,
        "gpu_percent": gpu,
        "agent_cpu_percent": agent_cpu,
        "agent_mem_mb": agent_mem
    }


async def main():
    client = MQTTClient(DEVICE_ID)

    # Handlers
    def on_connect(c, flags, rc, properties):
        print(f"[{DEVICE_ID}] Connected to Mosquitto or Aws Iot!")

    def on_disconnect(c, packet, exc=None):
        print(f"[{DEVICE_ID}] Disconnected Mosquitto or Aws Iot!")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    await client.connect(MQTT_BROKER, MQTT_PORT)

    try:
        while True:
            metrics = collect_metrics()

            # notify if CPU usage exceeds 90%
            if metrics["cpu_percent"] > 90:
                print(f"WARN: CPU > 90% ({metrics['cpu_percent']}%)")

            # debug output to monitor the agent's resource consumption
            print(f"[DEBUG] agent_cpu={metrics['agent_cpu_percent']}%, "
                  f"agent_mem={metrics['agent_mem_mb']:.2f} MB")

            # Publish ALL metrics to MQTT broker
            client.publish(TOPIC, json.dumps(metrics), qos=1, retain=False)

            await asyncio.sleep(INTERVAL)

    except asyncio.CancelledError:
        print(f"[{DEVICE_ID}] Agent cancelled")
    finally:
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
