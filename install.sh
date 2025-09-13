#!/bin/bash
set -e

AGENT_USER=protex
AGENT_DIR=/opt/protex-agent
ENV_SAMPLE=$AGENT_DIR/env_sample
ENV_FILE=$AGENT_DIR/.env
SERVICE_FILE=/etc/systemd/system/protex-agent.service
CERT_DIR=/etc/protex-agent/certs

# 1. Create system user
if ! id -u $AGENT_USER >/dev/null 2>&1; then
    echo "[INFO] Creating user $AGENT_USER..."
    sudo useradd -r -s /usr/sbin/nologin $AGENT_USER
fi

# 2. Clone agent repository
if [ ! -d "$AGENT_DIR" ]; then
    echo "[INFO] Cloning repository..."
    sudo git clone https://github.com/richardnixondev/protex-agent.git $AGENT_DIR
    sudo chown -R $AGENT_USER:$AGENT_USER $AGENT_DIR
else
    echo "[INFO] Repository already exists, updating..."
    cd $AGENT_DIR && sudo -u $AGENT_USER git pull
fi

# 3. Create virtualenv and install dependencies
echo "[INFO] Installing dependencies into virtualenv..."
sudo -u $AGENT_USER python3 -m venv $AGENT_DIR/venv
sudo -u $AGENT_USER $AGENT_DIR/venv/bin/pip install --upgrade pip
sudo -u $AGENT_USER $AGENT_DIR/venv/bin/pip install -r $AGENT_DIR/requirements.txt

# 4. Setup environment file
if [ -f "$ENV_FILE" ]; then
    echo "[INFO] .env file already exists at $ENV_FILE, skipping creation."
else
    if [ -f "$ENV_SAMPLE" ]; then
        echo "[INFO] Copying env_sample to .env..."
        sudo cp $ENV_SAMPLE $ENV_FILE
        sudo chown $AGENT_USER:$AGENT_USER $ENV_FILE
        sudo chmod 600 $ENV_FILE
    else
        echo "[WARN] env_sample not found in repository, creating minimal .env file..."
        cat <<EOF | sudo tee $ENV_FILE
DEVICE_ID=device-iot-001
MQTT_BROKER=<BROKER_VM_IP>
MQTT_PORT=8883
TOPIC=devices/\${DEVICE_ID}/metrics
INTERVAL=10
SLACK_WEBHOOK_URL=

CA_CERT=$CERT_DIR/ca.crt
CLIENT_CERT=$CERT_DIR/device.crt
CLIENT_KEY=$CERT_DIR/device.key
EOF
        sudo chown $AGENT_USER:$AGENT_USER $ENV_FILE
        sudo chmod 600 $ENV_FILE
    fi
fi

# 5. Create cert directory
sudo mkdir -p $CERT_DIR
sudo chown -R $AGENT_USER:$AGENT_USER $CERT_DIR
sudo chmod 700 $CERT_DIR

# 6. Copy certs if found in current directory
FOUND_CERTS=false
for f in ca.crt device.crt device.key; do
    if [ -f "./$f" ]; then
        sudo cp "./$f" $CERT_DIR/
        FOUND_CERTS=true
    fi
done

if [ "$FOUND_CERTS" = true ]; then
    echo "[INFO] Certificates copied from current directory into $CERT_DIR"
    sudo chown -R $AGENT_USER:$AGENT_USER $CERT_DIR
    sudo chmod 600 $CERT_DIR/device.key
else
    echo "[WARN] No certificates found in current directory. Please copy ca.crt, device.crt and device.key manually into $CERT_DIR"
fi

# 7. Create systemd service
cat <<EOF | sudo tee $SERVICE_FILE
[Unit]
Description=Protex Edge Metrics Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$AGENT_DIR
EnvironmentFile=$ENV_FILE
ExecStart=$AGENT_DIR/venv/bin/python $AGENT_DIR/collect_metrics.py
Restart=always
RestartSec=5

User=$AGENT_USER
Group=$AGENT_USER
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

[Install]
WantedBy=multi-user.target
EOF

# 8. Enable and start service
echo "[INFO] Enabling protex-agent service..."
sudo systemctl daemon-reload
sudo systemctl enable protex-agent
sudo systemctl restart protex-agent

echo "[INFO] Installation completed ✅"
echo "Check logs with: sudo journalctl -u protex-agent -f"
