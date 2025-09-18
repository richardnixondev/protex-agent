"""
Edge Device Monitoring Agent
----------------------------
This Python script is designed to run on a Linux-based edge device (e.g., Raspberry Pi,
industrial PCs, or AWS Greengrass-managed nodes). It collects key system metrics (CPU, RAM,
Disk, GPU usage) and publishes them securely to AWS IoT Core using MQTT with TLS (mutual auth).

Key Features:
- Periodic collection of system metrics using psutil and NVIDIA's nvidia-smi (if GPU present).
- Lightweight and asynchronous (asyncio-based), ensuring minimal overhead.
- Secure TLS connection using X.509 device certificates.
- Self-monitoring: tracks its own CPU and memory usage to avoid interfering with workloads.
- Local warning if CPU exceeds a threshold (>90%).
"""

# ----------------------------
# Standard Library Imports
# ----------------------------
import asyncio          # For the asynchronous event loop
import json             # To encode metrics into JSON for MQTT messages
import os               # To access environment variables
import ssl              # To configure TLS encryption for MQTT
import subprocess       # To call system commands like `nvidia-smi` for GPU metrics
import time             # For timestamps in the metrics

# ----------------------------
# Third-Party Imports
# ----------------------------
import psutil           # For CPU, RAM, Disk, and process usage statistics
from gmqtt import Client as MQTTClient   # Async MQTT client library
from dotenv import load_dotenv           # Load configuration from a .env file

# ----------------------------
# Load Configuration
# ----------------------------
load_dotenv()  # Load key-value pairs from `.env` file into environment variables

# Device identity and connection details (configured via .env)
DEVICE_ID   = os.getenv("DEVICE_ID", "device-iot-001")
MQTT_BROKER = os.getenv("MQTT_BROKER")  # AWS IoT Core endpoint (e.g., xxx-ats.iot.us-east-1.amazonaws.com)
MQTT_PORT   = int(os.getenv("MQTT_PORT", "8883"))  # Default AWS IoT Core TLS port is 8883

# Certificate paths for mutual TLS authentication
CA_CERT     = os.getenv("CA_CERT", "AmazonRootCA1.pem")  # Amazon Root CA
CLIENT_CERT = os.getenv("CLIENT_CERT", "device.cert.pem")  # Device certificate
CLIENT_KEY  = os.getenv("CLIENT_KEY", "device.private.key")  # Device private key

# Publishing frequency (seconds)
INTERVAL    = int(os.getenv("INTERVAL", "10"))

# MQTT topic for publishing metrics. Convention: devices/{device_id}/metrics
TOPIC       = f"devices/{DEVICE_ID}/metrics"

# ----------------------------
# Process Reference
# ----------------------------
# We keep a reference to the current process to measure the agent’s own overhead
# (CPU% and memory usage). This ensures the agent itself does not cause significant
# load on the edge device.
process = psutil.Process(os.getpid())


# ----------------------------
# Metrics Collection
# ----------------------------
def collect_metrics():
    """
    Collect system metrics from the device:
    - CPU utilization (%)
    - RAM utilization (%)
    - Disk usage (%)
    - GPU utilization (%), if available via NVIDIA SMI
    - Agent's own CPU and memory usage
    """

    # CPU usage in percentage (across all cores)
    cpu = psutil.cpu_percent(interval=None)

    # Memory usage in percentage
    mem = psutil.virtual_memory().percent

    # Disk usage for the root filesystem
    disk = psutil.disk_usage("/").percent

    # GPU usage (optional, NVIDIA only)
    try:
        # Call `nvidia-smi` to query GPU utilization and memory usage
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ]
        ).decode().strip()
        # Example output: "15, 200, 8000" (gpu%, mem_used, mem_total)
        gpu_util, _, _ = out.split(",")
        gpu = float(gpu_util)
    except Exception:
        # If no GPU is present, or command fails, fallback to None
        gpu = None

    # Agent's own resource usage
    agent_mem = process.memory_info().rss / (1024 * 1024)  # Resident memory (MB)
    agent_cpu = process.cpu_percent(interval=None)         # CPU % just for this process

    # Return structured metrics as a JSON-compatible dictionary
    return {
        "device_id": DEVICE_ID,
        "timestamp": int(time.time()),  # Epoch timestamp (seconds)
        "cpu_percent": cpu,
        "mem_percent": mem,
        "disk_percent": disk,
        "gpu_percent": gpu,
        "agent_cpu_percent": agent_cpu,
        "agent_mem_mb": agent_mem,
    }


# ----------------------------
# Main Async Routine
# ----------------------------
async def main():
    """
    Main coroutine that:
    - Establishes a secure MQTT connection to AWS IoT Core
    - Periodically collects system metrics
    - Publishes them to the MQTT topic
    - Monitors its own health and warns if CPU usage > 90%
    """

    # Initialize MQTT client with the device ID as client_id
    client = MQTTClient(DEVICE_ID)

    # Event handlers (callbacks from gmqtt)
    def on_connect(_client, _flags, _rc, _properties):
        """Triggered when the agent connects to AWS IoT Core."""
        print(f"[{DEVICE_ID}] ✅ Connected to AWS IoT Core")

    def on_disconnect(_client, _packet, _exc=None):
        """Triggered when the agent disconnects from AWS IoT Core."""
        print(f"[{DEVICE_ID}] ❌ Disconnected from AWS IoT Core")

    # Register the event handlers
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect

    # ----------------------------
    # TLS Configuration
    # ----------------------------
    ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ssl_ctx.load_verify_locations(CA_CERT)               # Root CA
    ssl_ctx.load_cert_chain(certfile=CLIENT_CERT, keyfile=CLIENT_KEY)  # Device cert + key

    # ----------------------------
    # Connect to AWS IoT Core
    # ----------------------------
    await client.connect(MQTT_BROKER, MQTT_PORT, ssl=ssl_ctx)

    try:
        # Infinite loop for metric collection and publishing
        while True:
            metrics = collect_metrics()

            # Local alert: if CPU usage is critical, print warning to stdout
            if metrics["cpu_percent"] > 90:
                print(f"⚠️ WARN: CPU > 90% ({metrics['cpu_percent']}%)")

            # Debug info: print the agent’s own CPU and memory usage
            print(
                f"[DEBUG] agent_cpu={metrics['agent_cpu_percent']}%, "
                f"agent_mem={metrics['agent_mem_mb']:.2f} MB"
            )

            # Publish metrics to AWS IoT Core via MQTT
            # QoS=1 ensures at-least-once delivery
            # retain=False means message is not stored by broker for future subscribers
            client.publish(TOPIC, json.dumps(metrics), qos=1, retain=False)

            # Sleep asynchronously (non-blocking) before next iteration
            await asyncio.sleep(INTERVAL)

    except asyncio.CancelledError:
        # Graceful cancellation (e.g., service stop)
        print(f"[{DEVICE_ID}] Agent cancelled")

    finally:
        # Disconnect cleanly from AWS IoT Core before exit
        await client.disconnect()


# ----------------------------
# Entry Point
# ----------------------------
if __name__ == "__main__":
    # Start the asyncio event loop
    asyncio.run(main())
