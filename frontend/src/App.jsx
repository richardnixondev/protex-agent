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

const MAX_POINTS = 50;

function ensureArrayHistory(prev, deviceId) {
  return prev[deviceId] ? prev : { ...prev, [deviceId]: [] };
}

function normalizePoint(p) {
  // formata timestamp e garante números (0..100) quando possível
  const ts =
    typeof p.timestamp === "number"
      ? p.timestamp * 1000
      : Date.parse(p.timestamp) || Date.now();
  const timeLabel = new Date(ts).toLocaleTimeString();
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
  // histories: { deviceId: Array<point> }
  const [histories, setHistories] = useState({});
  const wsRef = useRef(null);
  const reconnectTimer = useRef(null);

  useEffect(() => {
    const connect = () => {
      const ws = new WebSocket("ws://localhost:6789");
      wsRef.current = ws;

      ws.onopen = () => {
        console.log("✅ WS conectado");
        if (reconnectTimer.current) {
          clearTimeout(reconnectTimer.current);
          reconnectTimer.current = null;
        }
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data);
          // msg pode ser:
          // 1) estado inicial: { dev1: {...}, dev2: {...} }
          // 2) delta: { devX: {...} }
          const entries = Object.entries(msg);
          setHistories((prev) => {
            let next = { ...prev };
            for (const [deviceId, pointRaw] of entries) {
              const point = normalizePoint(pointRaw);
              next = ensureArrayHistory(next, deviceId);
              const arr = next[deviceId].concat(point);
              // limita histórico
              next[deviceId] = arr.slice(-MAX_POINTS);
            }
            return next;
          });
        } catch (e) {
          console.warn("Mensagem WS inválida:", e);
        }
      };

      ws.onclose = () => {
        console.log("❌ WS desconectado — tentando reconectar em 2s…");
        reconnectTimer.current = setTimeout(connect, 2000);
      };

      ws.onerror = (err) => {
        console.error("WS error:", err);
        ws.close();
      };
    };

    connect();
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    };
  }, []);

  const deviceIds = Object.keys(histories);

  return (
    <div className="App">
      <h1>📊 Dashboard de Métricas</h1>
      {deviceIds.length === 0 && <p>Aguardando métricas...</p>}

      {deviceIds.map((deviceId) => {
        const data = histories[deviceId];
        return (
          <div key={deviceId} className="device-card">
            <div className="device-header">
              <h2>{deviceId}</h2>
              {data?.length ? (
                <span className="badge">
                  última: {data[data.length - 1].timestampLabel}
                </span>
              ) : null}
            </div>
            <ResponsiveContainer width="95%" height={260}>
              <LineChart data={data}>
              <XAxis dataKey="timestampLabel" />
              <YAxis domain={[0, 100]} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="cpu_percent" name="CPU %" stroke="#e74c3c" />   {/* vermelho */}
              <Line type="monotone" dataKey="mem_percent" name="RAM %" stroke="#3498db" />   {/* azul */}
              <Line type="monotone" dataKey="disk_percent" name="Disco %" stroke="#2ecc71" /> {/* verde */}
              <Line type="monotone" dataKey="gpu_percent" name="GPU %" stroke="#f39c12" />   {/* laranja */}
            </LineChart>
          </ResponsiveContainer>

          </div>
        );
      })}
    </div>
  );
}
