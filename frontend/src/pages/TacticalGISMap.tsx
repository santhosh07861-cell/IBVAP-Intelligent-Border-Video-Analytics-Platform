import React, { useEffect, useState } from 'react';
import { MapContainer, TileLayer, Marker, Popup, Polyline, Polygon, CircleMarker, Tooltip } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  Shield, Globe, Camera as CameraIcon, ShieldAlert, Users, RefreshCw,
  Eye, MapPin, Layers, Activity, Radio, ArrowUpRight, Zap, CheckCircle2
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useWebSocket } from '../context/WebSocketContext';
import { useAuth } from '../context/AuthContext';
import { useCameras } from '../context/CameraContext';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';

// Custom Leaflet Icons using SVG Data URIs for crisp tactical markers
const createTacticalIcon = (color: string, label: string) => {
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24" fill="${color}" stroke="#0a0d14" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>
      <text x="12" y="14" font-size="8" font-weight="bold" fill="#ffffff" text-anchor="middle" font-family="monospace">${label}</text>
    </svg>
  `;
  return L.divIcon({
    className: 'custom-tactical-icon',
    html: svg,
    iconSize: [36, 36],
    iconAnchor: [18, 18],
    popupAnchor: [0, -18]
  });
};

const cameraIcon = L.divIcon({
  className: 'custom-camera-icon',
  html: `
    <div style="background:#1e293b; border:2px solid #3b82f6; border-radius:50%; width:32px; height:32px; display:flex; align-items:center; justify-content:center; box-shadow:0 0 10px rgba(59,130,246,0.5);">
      <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2.5"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>
    </div>
  `,
  iconSize: [32, 32],
  iconAnchor: [16, 16]
});

const alertedCameraIcon = L.divIcon({
  className: 'custom-alert-camera-icon',
  html: `
    <div style="background:#7f1d1d; border:2px solid #ef4444; border-radius:50%; width:36px; height:36px; display:flex; align-items:center; justify-content:center; box-shadow:0 0 15px rgba(239,68,68,0.8); animation: pulse 1.5s infinite;">
      <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fca5a5" stroke-width="2.5"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
    </div>
  `,
  iconSize: [36, 36],
  iconAnchor: [18, 18]
});

const bsfPatrolIcon = L.divIcon({
  className: 'custom-patrol-icon',
  html: `
    <div style="background:#1e3a8a; border:2px solid #60a5fa; border-radius:50%; width:28px; height:28px; display:flex; align-items:center; justify-content:center; box-shadow:0 0 8px rgba(96,165,250,0.6);">
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#93c5fd" stroke-width="2.5"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
    </div>
  `,
  iconSize: [28, 28],
  iconAnchor: [14, 14]
});

// Helper function to generate field-of-view wedge polygon coordinates
function createVisionCone(lat: number, lng: number, headingDeg: number = 45, fovDeg: number = 60, distanceDeg: number = 0.008) {
  const points: [number, number][] = [[lat, lng]];
  const startAngle = headingDeg - fovDeg / 2;
  const endAngle = headingDeg + fovDeg / 2;
  const step = 5;

  for (let a = startAngle; a <= endAngle; a += step) {
    const rad = (a * Math.PI) / 180;
    const dLat = distanceDeg * Math.cos(rad);
    const dLng = distanceDeg * Math.sin(rad) * 1.1; // aspect ratio adjustment
    points.push([lat + dLat, lng + dLng]);
  }
  return points;
}

export const TacticalGISMap: React.FC = () => {
  const { cameras, primaryCamera } = useCameras();
  const { lastMessage, lastAlert, telemetryMap } = useWebSocket();
  const { token } = useAuth();

  const [evidenceList, setEvidenceList] = useState<any[]>([]);
  const [selectedThreat, setSelectedThreat] = useState<any | null>(null);
  const [selectedModalEvidence, setSelectedModalEvidence] = useState<any | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  // International Border (IB / LoC) polyline vector coordinates
  const internationalBorderLine: [number, number][] = [
    [26.9550, 70.8650],
    [26.9380, 70.8820],
    [26.9150, 70.9000],
    [26.8920, 70.9180],
    [26.8680, 70.9380]
  ];

  // Zero-Line Virtual Fence polyline vector coordinates
  const zeroLineFence: [number, number][] = [
    [26.9520, 70.8680],
    [26.9350, 70.8850],
    [26.9124, 70.9025],
    [26.8890, 70.9210],
    [26.8650, 70.9410]
  ];

  // Border Security Outpost (BOP) locations
  const bsfOutposts = [
    { id: 'BOP-01', name: 'BSF Outpost Alpha (Sector HQ)', lat: 26.9124, lng: 70.9025, role: 'Sector HQ' },
    { id: 'BOP-02', name: 'BSF Outpost Bravo (Northern Watch)', lat: 26.9450, lng: 70.8750, role: 'Forward Post' },
    { id: 'BOP-03', name: 'BSF Outpost Charlie (Southern Outpost)', lat: 26.8750, lng: 70.9350, role: 'Forward Post' }
  ];

  // Friendly BSF Patrol Units (Blue Force)
  const bsfPatrolUnits = [
    { id: 'PATROL-1', name: 'BSF Cobra Patrol Alpha', lat: 26.9250, lng: 70.8920, status: 'PATROLLING ZERO-LINE' },
    { id: 'PATROL-2', name: 'BSF Quick Reaction Team (QRT)', lat: 26.8980, lng: 70.9120, status: 'STANDBY ON BORDER ROAD' }
  ];

  const fetchEvidenceHistory = async () => {
    setLoading(true);
    try {
      const headers: any = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/evidence?limit=50', { headers });
      if (res.ok) {
        const data = await res.json();
        setEvidenceList(data.items || []);
      }
    } catch (err) {
      console.error('Failed to fetch GIS evidence history:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvidenceHistory();
  }, [token]);

  // Handle incoming live WebSocket EVIDENCE_NEW or ALERT_NEW
  useEffect(() => {
    if (lastMessage && (lastMessage.type === 'EVIDENCE_NEW' || lastMessage.type === 'ALERT_NEW')) {
      fetchEvidenceHistory();
    }
  }, [lastMessage]);

  // Assign GPS coordinates to cameras
  const mapCameras = cameras.map((cam, idx) => {
    const defaultLat = 26.9124 + (idx === 0 ? 0 : idx % 2 === 0 ? idx * 0.015 : -idx * 0.015);
    const defaultLng = 70.9025 + (idx === 0 ? 0 : idx % 2 === 0 ? idx * 0.012 : -idx * 0.012);
    const lat = cam.latitude || defaultLat;
    const lng = cam.longitude || defaultLng;

    const heading = idx === 0 ? 45 : (idx * 60) % 360;
    const coneWedge = createVisionCone(lat, lng, heading, 60, 0.008);

    const hasAlert = lastAlert && (lastAlert.camera_id === cam.camera_id || lastAlert.camera_id === cam.id);
    const isOnline = cam.status === 'ONLINE' || (telemetryMap[cam.camera_id]?.fps || 0) > 0;

    return {
      ...cam,
      lat,
      lng,
      heading,
      coneWedge,
      hasAlert,
      isOnline
    };
  });

  // Calculate threats (Red Force) mapped on GIS coordinates
  const mapThreats = evidenceList.map((item, idx) => {
    const matchingCam = mapCameras.find(c => c.camera_id === item.camera_number || c.id === item.camera_id);
    const baseLat = matchingCam ? matchingCam.lat : 26.9124;
    const baseLng = matchingCam ? matchingCam.lng : 70.9025;

    // Slight offset per threat item
    const offsetLat = baseLat + ((idx % 5) * 0.002 - 0.004);
    const offsetLng = baseLng + ((idx % 3) * 0.003 - 0.003);

    return {
      ...item,
      lat: offsetLat,
      lng: offsetLng
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
          <p className="text-xs text-slate-400">REAL-TIME GPS THREAT MAPPING, CAMERA VISION CONES & ZERO-LINE DEFENSE</p>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <button
            onClick={fetchEvidenceHistory}
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

      {/* Legend & Stats Overview Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3 text-xs">
        <div className="bg-[#111622] p-3 rounded-lg border border-[#252d42] flex items-center justify-between">
          <span className="text-slate-400">SECTOR HQ</span>
          <strong className="text-blue-400">SECTOR 4 / JAISALMER</strong>
        </div>
        <div className="bg-[#111622] p-3 rounded-lg border border-[#252d42] flex items-center justify-between">
          <span className="text-slate-400">CAMERAS MAPPED</span>
          <strong className="text-emerald-400">{mapCameras.length} STREAMS</strong>
        </div>
        <div className="bg-[#111622] p-3 rounded-lg border border-[#252d42] flex items-center justify-between">
          <span className="text-slate-400">RED THREAT PINS</span>
          <strong className="text-red-400 font-bold">{mapThreats.length} DETECTED</strong>
        </div>
        <div className="bg-[#111622] p-3 rounded-lg border border-[#252d42] flex items-center justify-between">
          <span className="text-slate-400">BLUE FORCE UNITS</span>
          <strong className="text-blue-400">2 PATROLS ACTIVE</strong>
        </div>
        <div className="bg-[#111622] p-3 rounded-lg border border-[#252d42] flex items-center justify-between">
          <span className="text-slate-400">ZERO-LINE FENCE</span>
          <strong className="text-amber-400">VIRTUALIZED</strong>
        </div>
        <div className="bg-[#111622] p-3 rounded-lg border border-[#252d42] flex items-center justify-between">
          <span className="text-slate-400">WEBSOCKET STATUS</span>
          <strong className="text-emerald-400 flex items-center gap-1">
            <Radio className="w-3 h-3 animate-pulse" /> ONLINE
          </strong>
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
            {/* CartoDB Dark Matter Basemap */}
            <TileLayer
              url="https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png"
              attribution='&copy; <a href="https://carto.com/">CARTO</a> | IBVAP Tactical GIS'
              maxZoom={19}
            />

            {/* International Border (IB / LoC) Red Vector Line */}
            <Polyline
              positions={internationalBorderLine}
              pathOptions={{ color: '#ef4444', dashArray: '8, 8', weight: 3, opacity: 0.8 }}
            >
              <Tooltip sticky permanent direction="center" className="tactical-tooltip">
                INTERNATIONAL BORDER (IB) ZERO-LINE
              </Tooltip>
            </Polyline>

            {/* Amber Virtual Fence Line */}
            <Polyline
              positions={zeroLineFence}
              pathOptions={{ color: '#f59e0b', weight: 2, opacity: 0.9 }}
            >
              <Tooltip sticky direction="center">
                BSF SMART VIRTUAL FENCE LINE
              </Tooltip>
            </Polyline>

            {/* BSF Border Outposts (BOP Nodes) */}
            {bsfOutposts.map(bop => (
              <Marker
                key={bop.id}
                position={[bop.lat, bop.lng]}
                icon={createTacticalIcon('#2563eb', 'BSF')}
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

            {/* Friendly BSF Patrol Units (Blue Force) */}
            {bsfPatrolUnits.map(patrol => (
              <Marker
                key={patrol.id}
                position={[patrol.lat, patrol.lng]}
                icon={bsfPatrolIcon}
              >
                <Popup className="tactical-popup">
                  <div className="p-2 space-y-1 font-mono text-xs text-slate-100 bg-[#111622]">
                    <div className="font-bold text-blue-400 flex items-center gap-1">
                      <Users className="w-4 h-4" /> {patrol.name}
                    </div>
                    <div className="text-emerald-400 font-bold">{patrol.status}</div>
                    <div className="text-slate-400 text-[10px]">BLUE FORCE PATROL UNIT</div>
                  </div>
                </Popup>
              </Marker>
            ))}

            {/* Cameras & Directional Vision Cones */}
            {mapCameras.map(cam => (
              <React.Fragment key={cam.id || cam.camera_id}>
                {/* Vision Cone Wedge */}
                <Polygon
                  positions={cam.coneWedge}
                  pathOptions={{
                    color: cam.hasAlert ? '#ef4444' : cam.isOnline ? '#3b82f6' : '#64748b',
                    fillColor: cam.hasAlert ? '#ef4444' : cam.isOnline ? '#3b82f6' : '#64748b',
                    fillOpacity: cam.hasAlert ? 0.35 : 0.15,
                    weight: cam.hasAlert ? 2 : 1
                  }}
                />

                {/* Camera Marker */}
                <Marker
                  position={[cam.lat, cam.lng]}
                  icon={cam.hasAlert ? alertedCameraIcon : cameraIcon}
                >
                  <Popup className="tactical-popup">
                    <div className="p-3 space-y-2 font-mono text-xs bg-[#111622] text-slate-100 min-w-[200px]">
                      <div className="flex justify-between items-center border-b border-[#252d42] pb-1">
                        <strong className="text-blue-400">{cam.name} ({cam.camera_id})</strong>
                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          cam.isOnline ? 'bg-emerald-500/20 text-emerald-400' : 'bg-slate-800 text-slate-400'
                        }`}>
                          {cam.isOnline ? 'ONLINE' : 'STOPPED'}
                        </span>
                      </div>
                      <div className="text-slate-300">Location: {cam.location}</div>
                      <div className="text-slate-400">Protocol: <strong className="text-amber-400">{cam.protocol}</strong></div>
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

            {/* Red Force Threat Pins */}
            {mapThreats.map(threat => (
              <CircleMarker
                key={threat.id}
                center={[threat.lat, threat.lng]}
                radius={9}
                pathOptions={{
                  color: threat.event_type === 'DETECTION' ? '#f59e0b' : '#ef4444',
                  fillColor: threat.event_type === 'DETECTION' ? '#f59e0b' : '#ef4444',
                  fillOpacity: 0.8,
                  weight: 2
                }}
                eventHandlers={{
                  click: () => setSelectedThreat(threat)
                }}
              >
                <Tooltip direction="top" offset={[0, -10]}>
                  <div className="font-mono text-xs font-bold text-red-400">
                    🚨 {threat.event_type}: {threat.object_class?.toUpperCase()} ({threat.track_id})
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
            <div className="text-[11px] text-slate-300">Cones: Camera Field of View</div>
          </div>
        </div>

        {/* Tactical Threat Details Drawer */}
        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] flex flex-col justify-between space-y-4">
          <div>
            <h3 className="font-bold text-slate-100 text-sm border-b border-[#252d42] pb-2 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-red-400" /> TACTICAL THREAT INTELLIGENCE
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
                  <div className="absolute top-2 left-2 bg-red-600 text-white font-bold text-[10px] px-2 py-0.5 rounded uppercase">
                    {selectedThreat.event_type}
                  </div>
                </div>

                <div className="space-y-2 bg-[#0a0d14] p-3 rounded-lg border border-[#252d42]">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Object Class:</span>
                    <strong className="text-blue-400 uppercase">{selectedThreat.object_class}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Track ID:</span>
                    <strong className="text-emerald-400">{selectedThreat.track_id}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Confidence:</span>
                    <strong className="text-emerald-400">{(selectedThreat.confidence * 100).toFixed(0)}%</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Risk Score:</span>
                    <strong className="text-red-400 font-bold">{selectedThreat.risk_score} / 100</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Camera Source:</span>
                    <strong className="text-amber-400">{selectedThreat.camera_number || selectedThreat.camera_id}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Location:</span>
                    <strong className="text-slate-300 truncate">{selectedThreat.location}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Timestamp:</span>
                    <strong className="text-slate-400">{new Date(selectedThreat.captured_at).toLocaleTimeString()}</strong>
                  </div>
                </div>

                <button
                  onClick={() => setSelectedModalEvidence(selectedThreat)}
                  className="w-full py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 shadow-lg shadow-red-600/30 transition-colors"
                >
                  <Eye className="w-4 h-4" /> VIEW FULL EVIDENCE & DETAILS
                </button>
              </div>
            ) : (
              <div className="p-8 text-center text-slate-500 space-y-2 my-8">
                <MapPin className="w-8 h-8 text-slate-600 mx-auto" />
                <p className="font-bold text-slate-400">NO THREAT SELECTED</p>
                <p className="text-[11px] text-slate-500">
                  Click any red threat pin on the 3D GIS Map to inspect live threat evidence & spatial telemetry.
                </p>
              </div>
            )}
          </div>

          <div className="p-3 bg-[#0a0d14] rounded-lg border border-[#252d42] text-[11px] text-slate-400 font-mono">
            <div className="flex justify-between items-center mb-1">
              <span>BSF GIS TELEMETRY ENGINE</span>
              <span className="text-emerald-400 font-bold">READY</span>
            </div>
            <div className="text-[10px] text-slate-500">Lat: 26.9124° N • Lng: 70.9025° E</div>
          </div>
        </div>
      </div>
    </div>
  );
};
