import React, { createContext, useContext, useState, useEffect } from 'react';

interface DetectionMessage {
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
  fps?: number;
  latency_ms?: number;
  alert?: any;
}

interface WebSocketContextType {
  lastMessage: DetectionMessage | null;
  isConnected: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lastMessage, setLastMessage] = useState<DetectionMessage | null>(null);
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
            const data = JSON.parse(event.data);
            setLastMessage(data);
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

  return (
    <WebSocketContext.Provider value={{ lastMessage, isConnected }}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = () => {
  const ctx = useContext(WebSocketContext);
  if (!ctx) throw new Error("useWebSocket must be used within WebSocketProvider");
  return ctx;
};
