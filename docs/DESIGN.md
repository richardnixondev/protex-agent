## Design Explanation

#### Now:
Hybrid strategy: Edge Devices connects to AWS IoT Core to send metrics using the MQTT protocol. The backend also connects to AWS IoT Core, makes the data available through a WebSocket, and sends alerts to Slack. The frontend consumes the exposed WebSocket.

#### Production: 
Edge Devices connects to AWS IoT Core, rules for AWS IoT replace backend, routing to Slack, storage services(if needs) and Dashboards.

```mermaid
flowchart TD
  subgraph Edge["**Edge Devices**"]
    D1["**Device 1**<br/>Python Agent <br/>Cert + Key (mTLS)<br/>+ Backend + Frontend"]:::now
    D2["**Device 2**<br/>Python Agent <br/>Cert + Key (mTLS)"]:::now
    DN["**Device N**<br/>Python Agent <br/>Cert + Key (mTLS)"]:::now
  end

  subgraph Cloud["**AWS Cloud**"]
    IOT["**AWS IoT Core**<br/>(MQTT/TLS/ Thing Groups /<br/> Policies)"]:::now
    RULES["**Rules for AWS IoT**"]:::future
    STORE["**Storage**<br/>(S3 / DynamoDB /<br/> Timestream)"]:::future
    DASH["**Dashboards**<br/>(Grafana / QuickSight)"]:::future
    NOT["**Notifications**<br/>(SNS / Lambda)"]:::future
  end

  SLACK["Slack (external)"]

  %% Agents publicam para AWS IoT
  D1 --> IOT
  D2 --> IOT
  DN --> IOT

  %% HOJE: backend no Device 1 envia alertas para Slack
  D1 --backend alerts--> SLACK:::slack

  %% FUTURO: IoT Core -> Rules -> Consumers
  IOT -. future evolution .-> RULES
  RULES -.-> STORE
  RULES -.-> DASH
  RULES -.-> NOT
  NOT -. alerts .-> SLACK:::slack


  %% Classes
  classDef note fill:#fff8dc,stroke:#d4a017;
  classDef now fill:#eaffea,stroke:#2e8b57,stroke-width:1px; 
  classDef future fill:#e6f0ff,stroke:#1e3a8a,stroke-width:1px;
  classDef slack fill:#4A154B,color:#ffffff,stroke:#4A154B,stroke-width:2px;

```



## Security Considerations

* **mTLS:** Both the broker and the device authenticate each other using X.509 certificates.  
* **Encryption in transit:** All MQTT traffic is encrypted with TLS 1.2/1.3 on port 8883.  
* **Device certificates rotation:** Periodic certificate renewal or short-lived credentials to reduce the impact of key compromise.  
* **Least privilege policies:** IoT Core policies grant publish/subscribe only to allowed topics for each device.  
* **Per-device identities:** Each device has a unique certificate/identity to prevent spoofing or unauthorized access.  
* **Secure storage of keys:** Private keys are stored only on the device, with filesystem permissions locked to the agent user.  
* **Audit and logging:** Connection attempts, failures, and abnormal traffic are logged and monitored.  
* **Network segmentation:** Edge devices publish only via secure outbound traffic, no inbound ports exposed.  


