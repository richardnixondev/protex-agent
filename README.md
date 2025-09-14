# Protex Agent
![License](https://img.shields.io/badge/license-MIT-green)
![PyPI - Python Version](https://img.shields.io/badge/python-3.12%2B-blue)
![AWS](https://img.shields.io/badge/AWS-%23FF9900.svg?&logo=amazon-aws&logoColor=white)
![pylint](https://img.shields.io/badge/PyLint-10.00-brightgreen?logo=python&logoColor=white)


A lightweight hardware monitoring agent for edge devices.  
It collects key system metrics (CPU, RAM, Disk, GPU, agent self-metrics) and makes them available for remote monitoring via MQTT, WebSocket, and Slack alerts.

---

## Table of Contents
- [Prerequisites](#prerequisites)
- [Install](#install)
- [Design Explanation](#design-explanation)
- [Environment Variables](#environment-variables)
- [Assignment Checklist (MVP)](#assignment-checklist-mvp)
- [Live Demo](#live-demo)

---

## Prerequisites
- Python **3.12+**
- Node.js **v23.7.0+** (only if running the frontend dashboard)
- Linux (Ubuntu/Debian) or macOS  
- Local MQTT broker (e.g., [Mosquitto](https://mosquitto.org/)) or an AWS IoT Core endpoint

---

## Install

1 - Clone repositoy and cd to the directory:
```bash
git clone https://github.com/richardnixondev/protex-agent

cd protex-agent
```
2 - Create and activate a virtual environment. </br>
It’s recommended to isolate dependencies in a virtualenv:
```bash
python3 -m venv .venv

source .venv/bin/activate   # on Linux / macOS
```
3 - Install Python dependencies
```bash
pip install --upgrade pip

pip install -r requirements.txt
```
4 - Configure environment variables
```bash
cp env_sample .env
```
Update .env with your broker, WebSocket, and Slack settings.
See [Environment Variables](#-environment-variables) for details.

5 - Run the agent </br>
Starts collecting metrics and publishing them to MQTT.
```bash
python collect_metrics.py
```
6 - Run the backend (bridge MQTT → WebSocket + Slack)</br>
Makes metrics available to frontends and sends Slack alerts.
```bash
python backend.py
```
The backend exposes a WebSocket server at ws://localhost:6789

7 - Run the frontend (React dashboard, optional)
```bash
cd frontend
npm install
npm start
```

The dashboard will be available at: http://localhost:5173

---

## Design Explanation

See [DESIGN.md](./docs/DESIGN.md) for architecture choices, trade-offs,suggestions for improvements, scalability and security considerations.

---

## Environment Variables

- **MQTT_BROKER**: Hostname or endpoint of the MQTT broker (e.g., Mosquitto or AWS IoT Core).  
- **MQTT_PORT**: Port where the MQTT broker listens (default: `1883` for insecure, `8883` for TLS).  
- **TOPIC**: MQTT topic pattern used to publish device metrics.  
- **WS_HOST**: Host/IP where the WebSocket server should bind.  
- **WS_PORT**: Port where the WebSocket server should listen.  
- **PRUNE_SECONDS**: Time window (in seconds) to consider a device as “active” before pruning.  
- **CPU_ALERT_TH**: CPU usage threshold (%) to trigger alerts (e.g., Slack).  
- **SLACK_WEBHOOK_URL**: Slack Incoming Webhook URL used for sending notifications.  
- **DEVICE_ID**: Unique identifier for the device running the agent.  
- **INTERVAL**: Collection interval (in seconds) between metric samples.  
- **CA_CERT**: Path to the CA certificate file (for TLS/mTLS).  
- **CLIENT_CERT**: Path to the device’s client certificate (for TLS/mTLS).  
- **CLIENT_KEY**: Path to the device’s private key (for TLS/mTLS).  

---

## Assignment Checklist MVP

See [MVP.md](./docs/MVP.md) list of tasks performed based on the Assignment requirements.

---

## Live Demo

Coming soon 🚀
