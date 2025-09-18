import { useEffect, useRef, useState } from "react";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import "./App.css";

// Maximum number of points kept in memory for each device history
const MAX_POINTS = 50;

/**
 * Ensure the history object always contains an array for the given deviceId.
 * If it doesn't exist yet, create an empty array.
 */
function ensureArrayHistory(prev, deviceId) {
  return prev[deviceId] ? prev : { ...prev, [deviceId]: [] };
}

/**
 * Normalize a metric point received from the backend:
 * - Convert timestamp into a human-readable time label.
 * - Ensure numeric fields are coerced into numbers or null if invalid.
 */
function normalizePoint(p) {
  const ts =
    typeof p.timestamp === "number"
      ? p.timestamp * 1000 // if it's epoch seconds, convert to milliseconds
      : Date.parse(p.timestamp) || Date.now(); // fallback: parse ISO string or use "now"
  const timeLabel = new Date(ts).toLocaleTimeString();

  // Helper: safely convert to number or null
  const toNum = (v) =>
    v === null || v === undefined || Number.isNaN(Number(v))
      ? null
      : Number(v);

  return {
    ...p,
    timestampLabel: timeLabel,
    cpu_percent: toNum(p.cpu_percent),
    mem_percent: toNum(p.mem_percent),
    disk_percent: toNum(p.disk_percent),
    gpu_percent: toNum(p.gpu_percent),
  };
}

export default function App() {
  // State to hold metrics history per device: { deviceId: Array<point> }
  const [histories, setHistories] = useState({});
  const wsRef = useRef(null); // Reference to the WebSocket object
  const reconnectTimer = useRef(null); // Timer to manage auto-reconnect

  useEffect(() => {
    // Function to establish WebSocket connection
    const connect = () => {
      const ws = new WebSocket("ws://localhost:6789");
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("✅ WS connected");
        // Clear any existing reconnect timer
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      // Handle incoming WebSocket messages
      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data); // expected: { deviceId: metrics }
          const entries = Object.entries(msg);

          // Update histories state with new points
          setHistories((prev) => {
            let next = { ...prev };
            for (const [deviceId, pointRaw] of entries) {
              const point = normalizePoint(pointRaw);
              next = ensureArrayHistory(next, deviceId);

              // Append new point, enforce history length limit
              const arr = next[deviceId].concat(point);
              next[deviceId] = arr.slice(-MAX_POINTS);
            }
            return next;
          });
        } catch (e) {
          console.warn("Invalid WS message:", e);
        }
      };

      // Handle WebSocket close (lost connection) → auto-reconnect
      ws.onclose = () => {
        console.log("❌ WS disconnected — trying to reconnect in 2s…");
        reconnectTimer.current = setTimeout(connect, 2000);
      };

      // Handle WebSocket errors
      ws.onerror = (err) => {
        console.error("WS error:", err);
        ws.close();
      };
    };

    connect();

    // Cleanup on unmount: close WS and clear timers
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, []);

  const deviceIds = Object.keys(histories); // list of connected device IDs

  return (
    <div className="App">
      <h1>📊 Metrics Dashboard</h1>
      {deviceIds.length === 0 && <p>Waiting for metrics...</p>}

      {deviceIds.map((deviceId) => {
        const data = histories[deviceId];
        return (
          <div key={deviceId} className="device-card">
            {/* Header with device name and last update timestamp */}
            <div className="device-header">
              <h2>{deviceId}</h2>
              {data?.length ? (
                <span className="badge">
                  last: {data[data.length - 1].timestampLabel}
                </span>
              ) : null}
            </div>

            {/* Line chart showing metrics */}
            <ResponsiveContainer width="95%" height={260}>
              <LineChart data={data}>
                <XAxis dataKey="timestampLabel" />
                <YAxis domain={[0, 100]} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="cpu_percent" name="CPU %" stroke="#e74c3c" />   {/* red */}
                <Line type="monotone" dataKey="mem_percent" name="RAM %" stroke="#3498db" />   {/* blue */}
                <Line type="monotone" dataKey="disk_percent" name="Disk %" stroke="#2ecc71" />  {/* green */}
                <Line type="monotone" dataKey="gpu_percent" name="GPU %" stroke="#f39c12" />   {/* orange */}
              </LineChart>
            </ResponsiveContainer>
          </div>
        );
      })}
    </div>
  );
}
