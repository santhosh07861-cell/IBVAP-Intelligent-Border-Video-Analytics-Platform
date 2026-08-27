import React, { createContext, useContext, useState, useEffect } from 'react';
import { playDangerAlarmSound } from '../utils/alertSound';

export interface DetectionMessage {
  type: string;
  camera_id?: string;
  timestamp?: string;
  inference_mode?: string;
  detections?: Array<{
    track_id: number;
    class_name: string;
    confidence: number;
    bbox: number[];
    dwell_time_sec: number;
    is_fallback: boolean;
  }>;
  faces?: Array<{
    track_id: number;
    bbox: number[];
    landmarks: number[][];
    confidence: number;
    quality_score: number;
    recognition_status: string;
    identity_id: string | null;
    identity_name: string | null;
    recognition_confidence: number;
  }>;
  fps?: number;
  latency_ms?: number;
  alert?: any;
  evidence_id?: string;
  face_id?: string;
  identity_id?: string | null;
  identity_name?: string | null;
  recognition_status?: string;
  detection_confidence?: number;
  recognition_confidence?: number;
  bbox?: number[];
  landmarks?: number[][];
  crop_url?: string | null;
  snapshot_url?: string | null;
  quality_score?: number;
  camera_number?: string;
  camera_name?: string;
  location?: string;
  object_class?: string;
  display_label?: string;
  track_id?: string;
  confidence?: number;
  event_type?: string;
  risk_score?: number;
  severity?: string;
  file_url?: string;
  evidence?: any;
}

interface WebSocketContextType {
  lastMessage: DetectionMessage | null;
  lastAlert: any | null;
  telemetryMap: Record<string, DetectionMessage>;
  getCameraTelemetry: (cameraId?: string) => DetectionMessage | null;
  isConnected: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lastMessage, setLastMessage] = useState<DetectionMessage | null>(null);
  const [lastAlert, setLastAlert] = useState<any | null>(null);
  const [telemetryMap, setTelemetryMap] = useState<Record<string, DetectionMessage>>({});
  const [isConnected, setIsConnected] = useState<boolean>(false);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    let ws: WebSocket;
    let pingInterval: any;

    const connect = () => {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, 5000);
      };

      ws.onmessage = (event) => {
        try {
          if (event.data !== 'pong') {
            const data: DetectionMessage = JSON.parse(event.data);
            if (data.type === 'ALERT_NEW') {
              const alertObj = data.alert || data;
              setLastAlert(alertObj);
              setLastMessage(data);
              // Pass alert_id for sound deduplication — same alert won't trigger multiple sounds
              const alertId = (data as any).alert_id || alertObj?.id;
              playDangerAlarmSound(alertId);
            } else if (data.type === 'FACE_WATCHLIST_MATCH') {
              setLastMessage(data);
              const alertId = (data as any).alert_id || `wl_${Date.now()}`;
              playDangerAlarmSound(alertId);
            } else if (data.type === 'EVIDENCE_NEW' || data.type === 'FACE_DETECTION_UPDATE') {
              setLastMessage(data);
            }

            if (data.type === 'DETECTIONS_UPDATE' && data.camera_id) {
              const cid = data.camera_id;
              setTelemetryMap((prev) => ({
                ...prev,
                [cid]: data
              }));
            }
          }
        } catch (e) {
          // JSON parse skip non-JSON
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        clearInterval(pingInterval);
        setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      if (ws) ws.close();
      if (pingInterval) clearInterval(pingInterval);
    };
  }, []);

  const getCameraTelemetry = (cameraId?: string): DetectionMessage | null => {
    if (!cameraId) return null;
    return telemetryMap[cameraId] || null;
  };

  return (
    <WebSocketContext.Provider
      value={{
        lastMessage,
        lastAlert,
        telemetryMap,
        getCameraTelemetry,
        isConnected
      }}
    >
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error("useWebSocket must be used within WebSocketProvider");
  return ctx;
};
