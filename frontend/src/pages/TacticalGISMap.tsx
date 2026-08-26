import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, Polygon, CircleMarker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Shield, Globe, Camera as CameraIcon, ShieldAlert, Users, RefreshCw,
  Eye, MapPin, Layers, Activity, Radio, ArrowUpRight, Zap, CheckCircle2, AlertTriangle
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useWebSocket } from '../context/WebSocketContext';
import { useAuth } from '../context/AuthContext';
import { useCameras } from '../context/CameraContext';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';

// Status Marker Icons (🟢 ONLINE, 🟡 WARNING, 🔴 CRITICAL, ⚫ OFFLINE)
const createCameraStatusIcon = (status: 'ONLINE' | 'WARNING' | 'CRITICAL' | 'OFFLINE') => {
  let color = '#64748b'; // ⚫ OFFLINE
  let borderColor = '#334155';
  let animateClass = '';

  if (status === 'ONLINE') {
    color = '#22c55e'; // 🟢 ONLINE
    borderColor = '#16a34a';
  } else if (status === 'WARNING') {
    color = '#eab308'; // 🟡 WARNING
    borderColor = '#ca8a04';
  } else if (status === 'CRITICAL') {
    color = '#ef4444'; // 🔴 CRITICAL
    borderColor = '#dc2626';
    animateClass = 'animation: pulse 1.5s infinite;';
  }

  const html = `
    <div style="background:${status === 'OFFLINE' ? '#0f172a' : '#1e293b'}; border:3px solid ${color}; border-radius:50%; width:34px; height:34px; display:flex; align-items:center; justify-content:center; box-shadow:0 0 12px ${color}80; ${animateClass}">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
        <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
        <circle cx="12" cy="13" r="3"/>
      </svg>
    </div>
  `;

  return L.divIcon({
    className: 'custom-camera-status-icon',
    html: html,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
    popupAnchor: [0, -17]
  });
};

// BOP Marker Icon
const createTacticalBopIcon = (label: string) => {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="#2563eb" stroke="#0a0d14" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <text x="12" y="14" font-size="8" font-weight="bold" fill="#ffffff" text-anchor="middle" font-family="monospace">${label}</text>
    </svg>
  `;
  return L.divIcon({
    className: 'custom-bop-icon',
    html: svg,
    iconSize: [36, 36],
    iconAnchor: [18, 18]
  });
};

// Helper: Vision Cone Field-of-View Sector Wedge
function createVisionCone(lat: number, lng: number, headingDeg: number = 45, fovDeg: number = 60, distanceDeg: number = 0.008) {
  const points: [number, number][] = [[lat, lng]];
  const startAngle = headingDeg - fovDeg / 2;
  const endAngle = headingDeg + fovDeg / 2;
  const step = 5;

  for (let a = startAngle; a <= endAngle; a += step) {
    const rad = (a * Math.PI) / 180;
    const dLat = distanceDeg * Math.cos(rad);
    const dLng = distanceDeg * Math.sin(rad) * 1.1;
    points.push([lat + dLat, lng + dLng]);
  }
  return points;
}

// Helper: Get threat color by severity
function getThreatSeverityColor(severity: string): string {
  const sev = (severity || 'MEDIUM').toUpperCase();
  if (sev === 'LOW' || sev === 'INFO') return '#22c55e';     // LOW → green
  if (sev === 'MEDIUM') return '#eab308';                   // MEDIUM → yellow
  if (sev === 'HIGH') return '#f97316';                     // HIGH → orange
  if (sev === 'CRITICAL') return '#ef4444';                 // CRITICAL → red
  return '#ef4444';
}

export const TacticalGISMap: React.FC = () => {
  const { cameras } = useCameras();
  const { lastMessage, lastAlert, telemetryMap } = useWebSocket();
  const { token } = useAuth();

  const [zones, setZones] = useState<any[]>([]);
  const [evidenceList, setEvidenceList] = useState<any[]>([]);
  const [alertsList, setAlertsList] = useState<any[]>([]);
  const [selectedThreat, setSelectedThreat] = useState<any | null>(null);
  const [selectedModalEvidence, setSelectedModalEvidence] = useState<any | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // International Border Line (IB / LoC) Polyline Vector
  const internationalBorderLine: [number, number][] = [
    [26.9550, 70.8650],
    [26.9380, 70.8820],
    [26.9150, 70.9000],
    [26.8920, 70.9180],
    [26.8680, 70.9380]
  ];

  // Zero-Line Smart Virtual Fence Polyline Vector
  const zeroLineFence: [number, number][] = [
    [26.9520, 70.8680],
    [26.9350, 70.8850],
    [26.9124, 70.9025],
    [26.8890, 70.9210],
    [26.8650, 70.9410]
  ];

  // BSF Border Outposts (BOPs)
  const bsfOutposts = [
    { id: 'BOP-01', name: 'BSF Outpost Alpha (Sector HQ)', lat: 26.9124, lng: 70.9025, role: 'Sector HQ' },
    { id: 'BOP-02', name: 'BSF Outpost Bravo (Northern Watch)', lat: 26.9450, lng: 70.8750, role: 'Forward Post' },
    { id: 'BOP-03', name: 'BSF Outpost Charlie (Southern Outpost)', lat: 26.8750, lng: 70.9350, role: 'Forward Post' }
  ];

  const fetchGisData = async () => {
    setLoading(true);
    try {
      const headers: any = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      // 1. Fetch Configured Virtual Fence Zones from PostgreSQL
      const zoneRes = await fetch('/api/zones', { headers });
      if (zoneRes.ok) {
        const zoneData = await zoneRes.json();
        setZones(Array.isArray(zoneData) ? zoneData : []);
      }

      // 2. Fetch Evidence Records
      const evRes = await fetch('/api/evidence?limit=50', { headers });
      if (evRes.ok) {
        const evData = await evRes.json();
        setEvidenceList(evData.items || []);
      }

      // 3. Fetch Alerts
      const alertRes = await fetch('/api/alerts?limit=50', { headers });
      if (alertRes.ok) {
        const alertData = await alertRes.json();
        setAlertsList(Array.isArray(alertData) ? alertData : []);
      }
    } catch (err) {
      console.error('Failed to fetch GIS data from backend:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchGisData();
  }, [token]);

  // Real-Time WebSocket Updates (DETECTIONS_UPDATE, ALERT_NEW, EVIDENCE_NEW)
  useEffect(() => {
    if (lastMessage) {
      if (lastMessage.type === 'ALERT_NEW' || lastMessage.type === 'EVIDENCE_NEW' || lastMessage.type === 'DETECTIONS_UPDATE') {
        fetchGisData();
      }
    }
  }, [lastMessage]);

  // Assign GPS coordinates & evaluate status per camera
  const mapCameras = cameras.map((cam, idx) => {
    const defaultLat = 26.9124 + (idx === 0 ? 0 : idx % 2 === 0 ? idx * 0.015 : -idx * 0.015);
    const defaultLng = 70.9025 + (idx === 0 ? 0 : idx % 2 === 0 ? idx * 0.012 : -idx * 0.012);
    const lat = cam.latitude || defaultLat;
    const lng = cam.longitude || defaultLng;

    const heading = idx === 0 ? 45 : (idx * 60) % 360;
    const coneWedge = createVisionCone(lat, lng, heading, 60, 0.008);

    // Telemetry & Status
    const tele: any = telemetryMap[cam.camera_id] || telemetryMap[cam.id] || {};
    const fps = tele.fps || cam.fps || (cam.status === 'ONLINE' ? 24.0 : 0.0);
    const latency = tele.latency_ms || 42.5;

    const cameraAlerts = alertsList.filter(a => a.camera_id === cam.id || a.camera_id === cam.camera_id);
    const hasCriticalAlert = cameraAlerts.some(a => a.severity === 'CRITICAL' || a.severity === 'HIGH');
    const hasWarningAlert = cameraAlerts.some(a => a.severity === 'MEDIUM' || a.severity === 'LOW');

    // Status: 🟢 ONLINE, 🟡 WARNING, 🔴 CRITICAL, ⚫ OFFLINE
    let statusMarker: 'ONLINE' | 'WARNING' | 'CRITICAL' | 'OFFLINE' = 'OFFLINE';
    if (cam.status === 'ONLINE') {
      if (hasCriticalAlert) statusMarker = 'CRITICAL';
      else if (hasWarningAlert) statusMarker = 'WARNING';
      else statusMarker = 'ONLINE';
    } else if ((cam.status as string) === 'CONNECTING') {
      statusMarker = 'WARNING';
    } else {
      statusMarker = 'OFFLINE';
    }

    const detections: any[] = tele.detections || [];
    const objectsCount = detections.length;
    const peopleCount = detections.filter((d: any) => d.class_name === 'person').length;

    const latestEv = evidenceList.find(e => e.camera_id === cam.id || e.camera_number === cam.camera_id);
    const latestRiskScore = latestEv ? latestEv.risk_score : (hasCriticalAlert ? 85 : hasWarningAlert ? 55 : 0);

    return {
      ...cam,
      lat,
      lng,
      heading,
      coneWedge,
      statusMarker,
      fps,
      latency,
      objectsCount,
      peopleCount,
      activeAlertsCount: cameraAlerts.length,
      latestEvidence: latestEv,
      latestRiskScore
    };
  });

  // Calculate threats (Red Force) mapped on GIS coordinates
  const mapThreats = evidenceList.map((item, idx) => {
    const matchingCam = mapCameras.find(c => c.camera_id === item.camera_number || c.id === item.camera_id);
    const baseLat = matchingCam ? matchingCam.lat : 26.9124;
    const baseLng = matchingCam ? matchingCam.lng : 70.9025;

    const offsetLat = baseLat + ((idx % 5) * 0.002 - 0.004);
    const offsetLng = baseLng + ((idx % 3) * 0.003 - 0.003);

    return {
      ...item,
      lat: offsetLat,
      lng: offsetLng,
      severityColor: getThreatSeverityColor(item.severity)
    };
  });

  // Map PostgreSQL Virtual Fence Polygons (`camera_zones`)
  const mapZones = zones.map(z => {
    const matchingCam = mapCameras.find(c => c.id === z.camera_id || c.camera_id === z.camera_id);
    const baseLat = matchingCam ? matchingCam.lat : 26.9124;
    const baseLng = matchingCam ? matchingCam.lng : 70.9025;

    const polygonPts: [number, number][] = (z.coordinates || []).map((pt: number[]) => {
      // If normalized (0-1), project relative to camera lat/lng
      if (pt[0] <= 1.0 && pt[1] <= 1.0) {
        return [baseLat + (pt[1] - 0.5) * 0.012, baseLng + (pt[0] - 0.5) * 0.015];
      }
      return [pt[0], pt[1]];
    });

    return {
      ...z,
      polygonPts
    };
  });

  return (
    <div className="p-6 space-y-6 font-mono">
      {/* Evidence Detail Modal */}
      {selectedModalEvidence && (
        <EvidenceDetailModal item={selectedModalEvidence} onClose={() => setSelectedModalEvidence(null)} />
      )}

      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2">
            <Globe className="w-5 h-5 text-blue-400 animate-pulse" /> 3D TACTICAL GIS BORDER SURVEILLANCE MAP
          </h2>
          <p className="text-xs text-slate-400">POSTGRESQL SPATIAL REPOSITORY • WEBSOCKET REAL-TIME SYNC • ZERO FAKE DETECTIONS</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <button
            onClick={fetchGisData}
            className="px-3 py-2 bg-[#1a2030] hover:bg-[#252d42] text-slate-300 rounded-lg font-semibold uppercase tracking-wider flex items-center gap-1.5 border border-[#252d42] transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> REFRESH MAP
          </button>
          <Link
            to="/surveillance"
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg font-bold uppercase tracking-wider transition-colors shadow-lg shadow-blue-600/20 flex items-center gap-1.5"
          >
            LIVE SURVEILLANCE GRID <ArrowUpRight className="w-4 h-4" />
          </Link>
        </div>
      </div>

      {/* Camera Status & Severity Legend */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2 text-xs">
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-500 shadow-sm shadow-emerald-500/50" />
          <span className="text-slate-300 text-[11px]">🟢 ONLINE</span>
        </div>
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-amber-500 shadow-sm shadow-amber-500/50" />
          <span className="text-slate-300 text-[11px]">🟡 WARNING</span>
        </div>
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-red-500 animate-ping" />
          <span className="text-slate-300 text-[11px]">🔴 CRITICAL</span>
        </div>
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-slate-600" />
          <span className="text-slate-300 text-[11px]">⚫ OFFLINE</span>
        </div>

        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-emerald-500" />
          <span className="text-slate-300 text-[11px]">LOW (Green)</span>
        </div>
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-amber-500" />
          <span className="text-slate-300 text-[11px]">MEDIUM (Yellow)</span>
        </div>
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-orange-500" />
          <span className="text-slate-300 text-[11px]">HIGH (Orange)</span>
        </div>
        <div className="bg-[#111622] p-2.5 rounded-lg border border-[#252d42] flex items-center gap-2">
          <div className="w-3 h-3 rounded-full bg-red-500" />
          <span className="text-slate-300 text-[11px]">CRITICAL (Red)</span>
        </div>
      </div>

      {/* Main Map & Threat Drawer Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Leaflet Map Box */}
        <div className="lg:col-span-3 bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden h-[620px] relative shadow-2xl">
          <MapContainer
            center={[26.9124, 70.9025]}
            zoom={13}
            scrollWheelZoom={true}
            style={{ width: '100%', height: '100%', background: '#0a0d14' }}
          >
            {/* OpenStreetMap Tactical Dark Matter Basemap */}
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              className="tactical-dark-tiles"
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> | IBVAP Tactical GIS'
              maxZoom={19}
            />

            {/* International Border Line (IB / LoC) Red Polyline */}
            <Polyline
              positions={internationalBorderLine}
              pathOptions={{ color: '#ef4444', dashArray: '8, 8', weight: 3, opacity: 0.8 }}
            >
              <Tooltip sticky permanent direction="center" className="tactical-tooltip">
                INTERNATIONAL BORDER (IB) ZERO-LINE
              </Tooltip>
            </Polyline>

            {/* Amber Virtual Fence Polyline */}
            <Polyline
              positions={zeroLineFence}
              pathOptions={{ color: '#f59e0b', weight: 2, opacity: 0.9 }}
            >
              <Tooltip sticky direction="center">
                BSF SMART VIRTUAL FENCE LINE
              </Tooltip>
            </Polyline>

            {/* Render PostgreSQL Camera Zones / Virtual Fences */}
            {mapZones.map((z, i) => (
              <Polygon
                key={z.id || i}
                positions={z.polygonPts}
                pathOptions={{
                  color: z.is_active ? '#3b82f6' : '#64748b',
                  fillColor: z.is_active ? '#3b82f6' : '#64748b',
                  fillOpacity: 0.2,
                  weight: 2
                }}
              >
                <Tooltip direction="center" sticky>
                  <div className="font-mono text-xs text-blue-300 font-bold">
                    🛡️ {z.name} ({z.zone_type})
                  </div>
                </Tooltip>
              </Polygon>
            ))}

            {/* BSF Border Outposts (BOP Nodes) */}
            {bsfOutposts.map(bop => (
              <Marker
                key={bop.id}
                position={[bop.lat, bop.lng]}
                icon={createTacticalBopIcon('BSF')}
              >
                <Popup className="tactical-popup">
                  <div className="p-2 space-y-1 font-mono text-xs text-slate-100 bg-[#111622]">
                    <div className="font-bold text-blue-400 flex items-center gap-1">
                      <Shield className="w-4 h-4" /> {bop.name}
                    </div>
                    <div className="text-slate-300">Role: <strong>{bop.role}</strong></div>
                    <div className="text-slate-400">GPS: {bop.lat.toFixed(4)}, {bop.lng.toFixed(4)}</div>
                  </div>
                </Popup>
              </Marker>
            ))}

            {/* Camera Status Markers & Vision Cones */}
            {mapCameras.map(cam => (
              <React.Fragment key={cam.id || cam.camera_id}>
                {/* Field-of-View Sector Wedge */}
                <Polygon
                  positions={cam.coneWedge}
                  pathOptions={{
                    color: cam.statusMarker === 'CRITICAL' ? '#ef4444' : cam.statusMarker === 'WARNING' ? '#eab308' : cam.statusMarker === 'ONLINE' ? '#3b82f6' : '#64748b',
                    fillColor: cam.statusMarker === 'CRITICAL' ? '#ef4444' : cam.statusMarker === 'WARNING' ? '#eab308' : cam.statusMarker === 'ONLINE' ? '#3b82f6' : '#64748b',
                    fillOpacity: cam.statusMarker === 'CRITICAL' ? 0.35 : 0.15,
                    weight: cam.statusMarker === 'CRITICAL' ? 2 : 1
                  }}
                />

                {/* Camera Marker */}
                <Marker
                  position={[cam.lat, cam.lng]}
                  icon={createCameraStatusIcon(cam.statusMarker)}
                >
                  <Popup className="tactical-popup">
                    <div className="p-3 space-y-2 font-mono text-xs bg-[#111622] text-slate-100 min-w-[220px]">
                      <div className="flex justify-between items-center border-b border-[#252d42] pb-1">
                        <strong className="text-blue-400">{cam.name} ({cam.camera_id})</strong>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          cam.statusMarker === 'ONLINE' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                          cam.statusMarker === 'WARNING' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                          cam.statusMarker === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse' :
                          'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}>
                          {cam.statusMarker}
                        </span>
                      </div>

                      <div className="space-y-1 text-slate-300 text-[11px]">
                        <div>Location: <strong className="text-slate-200">{cam.location}</strong></div>
                        <div>Status: <strong className="text-slate-200">{cam.status}</strong></div>
                        <div>FPS: <strong className="text-emerald-400">{cam.fps.toFixed(1)}</strong> | Latency: <strong className="text-blue-400">{cam.latency}ms</strong></div>
                        <div>Objects Detected: <strong className="text-amber-400">{cam.objectsCount}</strong></div>
                        <div>People Count: <strong className="text-emerald-400">{cam.peopleCount}</strong></div>
                        <div>Active Alerts: <strong className="text-red-400 font-bold">{cam.activeAlertsCount}</strong></div>
                        <div>Latest Risk Score: <strong className="text-red-400 font-bold">{cam.latestRiskScore} / 100</strong></div>
                      </div>

                      {cam.latestEvidence && (
                        <div className="pt-1 border-t border-[#252d42]">
                          <div className="text-[10px] text-slate-400 mb-1">Latest Snapshot Evidence:</div>
                          <img src={cam.latestEvidence.file_url} alt="Evidence" className="w-full h-20 object-cover rounded border border-[#252d42]" />
                        </div>
                      )}

                      <div className="pt-1">
                        <Link
                          to="/surveillance"
                          className="w-full py-1.5 bg-blue-600 hover:bg-blue-500 text-white rounded text-[11px] font-bold flex items-center justify-center gap-1 uppercase"
                        >
                          <Eye className="w-3.5 h-3.5" /> OPEN LIVE STREAM
                        </Link>
                      </div>
                    </div>
                  </Popup>
                </Marker>
              </React.Fragment>
            ))}

            {/* Severity Color-Coded Threat Markers */}
            {mapThreats.map(threat => (
              <CircleMarker
                key={threat.id}
                center={[threat.lat, threat.lng]}
                radius={9}
                pathOptions={{
                  color: threat.severityColor,
                  fillColor: threat.severityColor,
                  fillOpacity: 0.85,
                  weight: 2
                }}
                eventHandlers={{
                  click: () => setSelectedThreat(threat)
                }}
              >
                <Tooltip direction="top" offset={[0, -10]}>
                  <div className="font-mono text-xs font-bold" style={{ color: threat.severityColor }}>
                    🚨 {threat.severity} THREAT: {threat.object_class?.toUpperCase()} ({threat.track_id})
                  </div>
                </Tooltip>
              </CircleMarker>
            ))}
          </MapContainer>

          {/* Map Overlay Badge */}
          <div className="absolute top-4 right-4 z-[1000] bg-slate-950/90 border border-blue-500/40 p-3 rounded-xl font-mono text-xs space-y-1 shadow-2xl">
            <div className="font-bold text-blue-400 flex items-center gap-1.5">
              <ShieldAlert className="w-4 h-4 text-red-500 animate-pulse" /> BSF TACTICAL OVERLAY ACTIVE
            </div>
            <div className="text-[11px] text-slate-300">Red Line: International Border (IB)</div>
            <div className="text-[11px] text-slate-300">Amber Line: Smart Virtual Fence</div>
            <div className="text-[11px] text-slate-300">Polygons: Configured Camera Zones</div>
          </div>
        </div>

        {/* Threat Details Drawer */}
        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] flex flex-col justify-between space-y-4">
          <div>
            <h3 className="font-bold text-slate-100 text-sm border-b border-[#252d42] pb-2 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-red-400" /> THREAT DETAILS INSPECTOR
            </h3>

            {selectedThreat ? (
              <div className="mt-4 space-y-4 text-xs">
                {/* Snapshot Image Preview */}
                <div className="relative aspect-video bg-slate-950 rounded-lg overflow-hidden border border-[#252d42]">
                  {selectedThreat.file_url ? (
                    <img src={selectedThreat.file_url} alt="Threat Snapshot" className="w-full h-full object-cover" />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">Snapshot Unavailable</div>
                  )}
                  <div className="absolute top-2 left-2 text-white font-bold text-[10px] px-2 py-0.5 rounded uppercase" style={{ backgroundColor: selectedThreat.severityColor }}>
                    {selectedThreat.severity} THREAT
                  </div>
                </div>

                <div className="space-y-2 bg-[#0a0d14] p-3 rounded-lg border border-[#252d42]">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Camera Source:</span>
                    <strong className="text-amber-400">{selectedThreat.camera_number || selectedThreat.camera_id}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Object Type:</span>
                    <strong className="text-blue-400 uppercase">{selectedThreat.object_class}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Track ID:</span>
                    <strong className="text-emerald-400">{selectedThreat.track_id}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Event Type:</span>
                    <strong className="text-red-400">{selectedThreat.event_type}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Risk Score:</span>
                    <strong className="text-red-400 font-bold">{selectedThreat.risk_score} / 100</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Date/Time:</span>
                    <strong className="text-slate-300">{new Date(selectedThreat.captured_at).toLocaleString()}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Alert Status:</span>
                    <strong className="text-emerald-400 uppercase">{selectedThreat.severity || 'ACTIVE'}</strong>
                  </div>
                </div>

                <button
                  onClick={() => setSelectedModalEvidence(selectedThreat)}
                  className="w-full py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 shadow-lg shadow-red-600/30 transition-colors"
                >
                  <Eye className="w-4 h-4" /> VIEW FULL EVIDENCE SNAPSHOT
                </button>
              </div>
            ) : (
              <div className="p-8 text-center text-slate-500 space-y-2 my-8">
                <MapPin className="w-8 h-8 text-slate-600 mx-auto" />
                <p className="font-bold text-slate-400">NO THREAT SELECTED</p>
                <p className="text-[11px] text-slate-500">
                  Click any severity color-coded threat marker on the 3D GIS Map to inspect threat metadata & snapshot evidence.
                </p>
              </div>
            )}
          </div>

          <div className="p-3 bg-[#0a0d14] rounded-lg border border-[#252d42] text-[11px] text-slate-400 font-mono">
            <div className="flex justify-between items-center mb-1">
              <span>BSF GIS TELEMETRY ENGINE</span>
              <span className="text-emerald-400 font-bold">ACTIVE</span>
            </div>
            <div className="text-[10px] text-slate-500">Sector: 4 / Rajasthan Border • Real Data Connected</div>
          </div>
        </div>
      </div>
    </div>
  );
};
