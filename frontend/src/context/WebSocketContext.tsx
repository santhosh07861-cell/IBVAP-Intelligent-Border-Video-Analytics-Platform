import React, { createContext, useContext, useState, useEffect, useRef, useCallback } from 'react';
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
    person_id?: string | null;
    category?: string | null;
    recognition_confidence: number;
  }>;
  fps?: number;
  latency_ms?: number;
  alert?: any;
  evidence_id?: string;
  face_id?: string;
  identity_id?: string | null;
  identity_name?: string | null;
  person_name?: string | null;
  person_id?: string | null;
  category?: string | null;
  similarity?: number;
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
  track_id?: any;
  confidence?: number;
  event_type?: string;
  risk_score?: number;
  severity?: string;
  file_url?: string;
  evidence?: any;
}

/**
 * Normalize any ALERT_NEW or FACE_WATCHLIST_MATCH / ANPR_WATCHLIST_MATCH WS payload
 * into ONE canonical alert object with a guaranteed `id` field.
 *
 * The backend broadcasts ALERT_NEW with both root-level fields AND a nested `alert: {}`.
 * Different consumers were reading different levels, causing deduplication to fail.
 * This function always returns a flat object where `id === alert_id` (the database Alert ID).
 */
function normalizeAlertPayload(data: any): any {
  const nested = data.alert || {};
  const alertId = data.alert_id || nested.id || nested.alert_id || data.id;
  const eventId  = data.event_id  || nested.event_id;
  const incidentId = data.incident_id || nested.incident_id;

  return {
    // Canonical ID — must match Alert.id in the database
    id: alertId,
    alert_id: alertId,
    event_id: eventId,
    incident_id: incidentId,
    incident_number: data.incident_number || nested.incident_number,

    camera_id: data.camera_id || nested.camera_id,
    camera_number: data.camera_number || nested.camera_number,
    camera_name: data.camera_name || nested.camera_name,
    camera_display: data.camera_display || nested.camera_display
      || (data.camera_number && data.camera_name
          ? `${data.camera_number} - ${data.camera_name}`
          : (data.camera_number || data.camera_id)),

    zone_id: data.zone_id || nested.zone_id,
    zone_name: data.zone_name || nested.zone_name,
    location: data.location || nested.location || 'Campus Perimeter',

    event_type: data.event_type || nested.event_type,
    alert_title: data.alert_title || nested.alert_title,
    severity: data.severity || nested.severity,
    risk_score: data.risk_score ?? nested.risk_score ?? 75,
    confidence: data.confidence ?? nested.confidence,
    status: data.status || nested.status || 'NEW',

    evidence_url: data.evidence_url || nested.evidence_url,
    person_name: data.person_name || nested.person_name,
    person_id: data.person_id || nested.person_id,
    category: data.category || nested.category,
    track_id: data.track_id || nested.track_id,
    object_class: data.object_class || nested.object_class,

    // Always use backend-generated UTC timestamp
    timestamp: data.timestamp || nested.timestamp,
    created_at: data.timestamp || nested.timestamp,
  };
}

interface WebSocketContextType {
  lastMessage: DetectionMessage | null;
  lastAlert: any | null;
  lastIncident: any | null;
  lastAnprDetection: any | null;
  latestAlerts: any[];             // ← Canonical shared alert store (all pages consume this)
  telemetryMap: Record<string, DetectionMessage>;
  getCameraTelemetry: (cameraId?: string) => DetectionMessage | null;
  isConnected: boolean;
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined);

const MAX_ALERTS_IN_STORE = 100;

export const WebSocketProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [lastMessage, setLastMessage] = useState<DetectionMessage | null>(null);
  const [lastAlert, setLastAlert] = useState<any | null>(null);
  const [lastIncident, setLastIncident] = useState<any | null>(null);
  const [lastAnprDetection, setLastAnprDetection] = useState<any | null>(null);
  const [latestAlerts, setLatestAlerts] = useState<any[]>([]);
  const [telemetryMap, setTelemetryMap] = useState<Record<string, DetectionMessage>>({});
  const [isConnected, setIsConnected] = useState<boolean>(false);

  // Deduplication set — tracks alert IDs already in the store to prevent duplicates
  const seenAlertIds = useRef<Set<string>>(new Set());
  // Track last received timestamp for reconnect recovery
  const lastReceivedTimestamp = useRef<string | null>(null);
  const tokenRef = useRef<string | null>(null);

  /**
   * Fetch alerts from backend and merge any missed events into the canonical store.
   * Called after reconnect or page navigation.
   */
  const fetchAndMergeAlerts = useCallback(async (since?: string) => {
    try {
      const authToken = tokenRef.current || localStorage.getItem('ibvap_token');
      const headers: Record<string, string> = {};
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const url = since
        ? `/api/alerts?limit=50&since=${encodeURIComponent(since)}`
        : '/api/alerts?limit=50';

      const res = await fetch(url, { headers });
      if (!res.ok) return;
      const data = await res.json();
      if (!Array.isArray(data)) return;

      setLatestAlerts(prev => {
        const combined = [...prev];
        for (const a of data) {
          const aid = a.id || a.alert_id;
          if (aid && !seenAlertIds.current.has(aid)) {
            seenAlertIds.current.add(aid);
            combined.push(a);
          }
        }
        // Sort by timestamp desc — backend timestamps, not frontend time
        combined.sort((a, b) => {
          const ta = a.timestamp || a.created_at || '';
          const tb = b.timestamp || b.created_at || '';
          return tb.localeCompare(ta);
        });
        return combined.slice(0, MAX_ALERTS_IN_STORE);
      });
    } catch (e) {
      // Network error — will retry on next reconnect
    }
  }, []);

  useEffect(() => {
    // Store token in ref for use in callbacks
    const storedToken = localStorage.getItem('ibvap_token');
    tokenRef.current = storedToken;

    // Initial load of alerts into canonical store
    fetchAndMergeAlerts();
  }, [fetchAndMergeAlerts]);

  useEffect(() => {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;

    let ws: WebSocket;
    let pingInterval: any;

    const connect = () => {
      ws = new WebSocket(wsUrl);

      ws.onopen = () => {
        setIsConnected(true);
        // After reconnect: fetch any missed alerts since last known event
        if (lastReceivedTimestamp.current) {
          fetchAndMergeAlerts(lastReceivedTimestamp.current);
        }
        pingInterval = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping');
          }
        }, 5000);
      };

      ws.onmessage = (event) => {
        try {
          if (event.data === 'pong') return;
          const data: DetectionMessage = JSON.parse(event.data);
          setLastMessage(data);

          if (data.type === 'ALERT_NEW' || data.type === 'FACE_WATCHLIST_MATCH') {
            const alertObj = normalizeAlertPayload(data);
            const alertId = alertObj.id;

            // Record timestamp for reconnect recovery
            if (alertObj.timestamp) {
              lastReceivedTimestamp.current = alertObj.timestamp;
            }

            // Deduplicate by alert_id — never add same alert twice
            if (alertId && !seenAlertIds.current.has(alertId)) {
              seenAlertIds.current.add(alertId);
              setLatestAlerts(prev => [alertObj, ...prev].slice(0, MAX_ALERTS_IN_STORE));
            }

            // Always update lastAlert reference (for backward compatibility with pages
            // that still consume lastAlert directly for toast/sound)
            setLastAlert(alertObj);

            // Trigger alarm sound for high-severity events
            const sev = (alertObj.severity || '').toUpperCase();
            const evType = (alertObj.event_type || '').toUpperCase();
            const risk = Number(alertObj.risk_score) || 0;

            const shouldTriggerAlarm =
              sev === 'CRITICAL' ||
              sev === 'HIGH' ||
              risk >= 70 ||
              evType.includes('WATCHLIST') ||
              evType.includes('UNKNOWN_PERSON') ||
              evType.includes('INTRUSION');

            if (shouldTriggerAlarm && alertId) {
              playDangerAlarmSound(alertId);
            }

          } else if (data.type === 'ALERT_UPDATED') {
            // Sync acknowledge/resolve status across all pages without full re-fetch
            const updatedId = (data as any).alert_id;
            const updatedStatus = (data as any).status;
            if (updatedId && updatedStatus) {
              setLatestAlerts(prev =>
                prev.map(a =>
                  (a.id || a.alert_id) === updatedId
                    ? { ...a, status: updatedStatus }
                    : a
                )
              );
            }

          } else if (data.type === 'INCIDENT_NEW') {
            const incidentObj = (data as any).incident || data;
            setLastIncident(incidentObj);

          } else if (data.type === 'ANPR_WATCHLIST_MATCH') {
            const alertObj = normalizeAlertPayload(data);
            const alertId = alertObj.id;
            if (alertId && !seenAlertIds.current.has(alertId)) {
              seenAlertIds.current.add(alertId);
              setLatestAlerts(prev => [alertObj, ...prev].slice(0, MAX_ALERTS_IN_STORE));
            }
            setLastAlert(alertObj);
            setLastAnprDetection(data);
            if (alertId) playDangerAlarmSound(alertId);

          } else if (data.type === 'ANPR_DETECTION') {
            setLastAnprDetection(data);
          }

          if (data.type === 'DETECTIONS_UPDATE' && data.camera_id) {
            const cid = data.camera_id;
            setTelemetryMap((prev) => ({
              ...prev,
              [cid]: data
            }));
          }
        } catch (e) {
          // Skip non-JSON (pong, etc.)
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
  }, [fetchAndMergeAlerts]);

  const getCameraTelemetry = (cameraId?: string): DetectionMessage | null => {
    if (!cameraId) return null;
    return telemetryMap[cameraId] || null;
  };

  return (
    <WebSocketContext.Provider
      value={{
        lastMessage,
        lastAlert,
        lastIncident,
        lastAnprDetection,
        latestAlerts,
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
  const context = useContext(WebSocketContext);
  if (!context) throw new Error('useWebSocket must be used within WebSocketProvider');
  return context;
};
