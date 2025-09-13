
import asyncio
import json
import os
import time
from gmqtt import Client as MQTTClient
from websockets.server import serve 
import aiohttp 
from dotenv import load_dotenv


load_dotenv()

MQTT_BROKER = "localhost"
MQTT_PORT   = 1883
TOPIC       = "devices/+/metrics"

PRUNE_SECONDS = 30  
CPU_ALERT_TH  = 90  

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

clients      = set()
device_state = {}   
last_seen    = {}   

def active_snapshot():
    now = time.time()
    return {
        did: payload
        for did, payload in device_state.items()
        if (now - last_seen.get(did, 0)) <= PRUNE_SECONDS
    }

async def ws_handler(websocket):
    clients.add(websocket)
    print(f"WS conectado. total={len(clients)}")
    try:
        snap = active_snapshot()
        if snap:
            await websocket.send(json.dumps(snap))

        async for _ in websocket:
            pass
    finally:
        clients.discard(websocket)
        print(f"WS desconectado. total={len(clients)}")

async def post_slack(text: str):
    if not SLACK_WEBHOOK_URL:
        print("[SLACK] URL não configurada")
        return
    try:
        async with aiohttp.ClientSession() as session:
            resp = await session.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
            body = await resp.text()
            print(f"[SLACK] status={resp.status}, body={body}")
    except Exception as e:
        print(f"[SLACK] erro ao enviar: {e}")

async def mqtt_loop():
    client = MQTTClient("backend-bridge")

    async def on_message(c, topic, payload, qos, properties):
        try:
            raw = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
            data = json.loads(raw)
        except Exception:
            return

        device_id = data.get("device_id", "unknown")
        device_state[device_id] = data
        last_seen[device_id]    = time.time()

    
        if clients:
            msg = json.dumps({device_id: data})
            targets = [ws for ws in list(clients) if ws.open]
            if targets:
                await asyncio.gather(*(ws.send(msg) for ws in targets), return_exceptions=True)

     
        cpu = data.get("cpu_percent")
        if isinstance(cpu, (int, float)) and cpu >= CPU_ALERT_TH:
            text = (f":rotating_light: CPU ALERT at {device_id} — "
                    f"CPU {cpu:.1f}%, RAM {data.get('mem_percent')}% :rotating_light:")
            asyncio.create_task(post_slack(text))

    client.on_message = on_message
    await client.connect(MQTT_BROKER, MQTT_PORT)
    client.subscribe(TOPIC, qos=1)

    while True:
        await asyncio.sleep(1)

async def main():
    async with serve(ws_handler, "localhost", 6789):
        print("WebSocket running at ws://localhost:6789")
        await mqtt_loop()

if __name__ == "__main__":
    asyncio.run(main())
