import React, { useEffect, useState, useRef } from 'react';
import {
  ShieldAlert, Plus, Trash2, CheckCircle2, AlertTriangle, Video, Eye,
  RefreshCw, Undo2, X, Play, ToggleLeft, ToggleRight, Layers, Sliders
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useCameras } from '../context/CameraContext';
import { useWebSocket } from '../context/WebSocketContext';

export const ZoneEditor: React.FC = () => {
  const { token, user } = useAuth();
  const { cameras, primaryCamera } = useCameras();
  const { getCameraTelemetry, lastMessage } = useWebSocket();

  const [selectedCameraId, setSelectedCameraId] = useState<string>('');
  const [zones, setZones] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [isDrawing, setIsDrawing] = useState<boolean>(false);
  const [points, setPoints] = useState<Array<[number, number]>>([]);
  const [hoverCoord, setHoverCoord] = useState<{ x: number; y: number } | null>(null);
  const [highlightedZoneId, setHighlightedZoneId] = useState<string | null>(null);
  const [notification, setNotification] = useState<{ type: 'success' | 'error'; message: string } | null>(null);

  // Form State
  const [zoneName, setZoneName] = useState<string>('');
  const [zoneType, setZoneType] = useState<string>('RESTRICTED AREA');
  const [objectType, setObjectType] = useState<string>('all');
  const [severity, setSeverity] = useState<string>('HIGH');
  const [loiteringThreshold, setLoiteringThreshold] = useState<number>(5);
  const [cooldownSec, setCooldownSec] = useState<number>(30);
  const [submitting, setSubmitting] = useState<boolean>(false);

  const containerRef = useRef<HTMLDivElement | null>(null);

  // Initialize selected camera
  useEffect(() => {
    if (!selectedCameraId && cameras.length > 0) {
      setSelectedCameraId(primaryCamera?.camera_id || cameras[0].camera_id);
    }
  }, [cameras, primaryCamera, selectedCameraId]);

  const fetchZones = async () => {
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/zones', { headers });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setZones(data);
        }
      }
    } catch (e) {
      console.error("Failed to fetch zones:", e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchZones();
    const interval = setInterval(fetchZones, 6000);
    return () => clearInterval(interval);
  }, [token]);

  // Real-time WebSocket listener for immediate sync
  useEffect(() => {
    if (lastMessage && (lastMessage.type === 'ZONES_UPDATE' || lastMessage.type === 'ALERT_NEW')) {
      fetchZones();
    }
  }, [lastMessage]);

  const selectedCam = cameras.find(
    (c) => c.camera_id === selectedCameraId || c.id === selectedCameraId
  ) || cameras[0];

  const telemetry = getCameraTelemetry(selectedCam?.camera_id);
  const isCamOnline = selectedCam && (selectedCam.status === 'ONLINE' || (telemetry?.fps || 0) > 0);

  // Canvas click handler to add normalized polygon points [0.0 - 1.0]
  const handleCanvasClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawing) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;

    const rawX = (e.clientX - rect.left) / rect.width;
    const rawY = (e.clientY - rect.top) / rect.height;

    const normX = Math.max(0.0, Math.min(1.0, Math.round(rawX * 10000) / 10000));
    const normY = Math.max(0.0, Math.min(1.0, Math.round(rawY * 10000) / 10000));

    setPoints((prev) => [...prev, [normX, normY]]);
  };

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!isDrawing) return;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    const rawX = (e.clientX - rect.left) / rect.width;
    const rawY = (e.clientY - rect.top) / rect.height;
    setHoverCoord({
      x: Math.max(0.0, Math.min(1.0, Math.round(rawX * 1000) / 1000)),
      y: Math.max(0.0, Math.min(1.0, Math.round(rawY * 1000) / 1000))
    });
  };

  const handleUndoPoint = () => {
    setPoints((prev) => prev.slice(0, -1));
  };

  const handleClearPoints = () => {
    setPoints([]);
  };

  const handleStartDrawing = () => {
    setIsDrawing(true);
    setPoints([]);
    setZoneName(`Restricted Zone - ${selectedCam?.camera_id || 'CAM'}`);
    setNotification(null);
  };

  const handleCancelDrawing = () => {
    setIsDrawing(false);
    setPoints([]);
    setNotification(null);
  };

  const handleSaveZone = async (e: React.FormEvent) => {
    e.preventDefault();
    if (points.length < 3) {
      setNotification({ type: 'error', message: 'A polygon virtual fence requires at least 3 coordinate points.' });
      return;
    }
    if (!selectedCam) {
      setNotification({ type: 'error', message: 'Please select a camera to associate with this virtual fence.' });
      return;
    }

    setSubmitting(true);
    setNotification(null);

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/zones', {
        method: 'POST',
        headers,
        body: JSON.stringify({
          camera_id: selectedCam.camera_id,
          name: zoneName.trim() || `Zone ${Date.now().toString().slice(-4)}`,
          zone_type: zoneType,
          geometry_type: 'polygon',
          coordinates: points,
          object_type: objectType,
          severity: severity,
          loitering_threshold_sec: loiteringThreshold,
          cooldown_sec: cooldownSec
        })
      });

      const data = await res.json();
      if (!res.ok) {
        setNotification({ type: 'error', message: data.detail || 'Failed to save virtual fence zone.' });
      } else {
        setNotification({ type: 'success', message: `Virtual fence zone '${zoneName}' saved to database!` });
        setIsDrawing(false);
        setPoints([]);
        fetchZones();
      }
    } catch (err: any) {
      setNotification({ type: 'error', message: err.message || 'Error saving zone.' });
    } finally {
      setSubmitting(false);
    }
  };

  const handleToggleZone = async (zoneId: string) => {
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch(`/api/zones/${zoneId}/toggle`, {
        method: 'PATCH',
        headers
      });
      if (res.ok) {
        fetchZones();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteZone = async (zoneId: string, zoneTitle: string) => {
    if (!window.confirm(`Permanently delete virtual fence zone '${zoneTitle}'?`)) return;
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch(`/api/zones/${zoneId}`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) {
        setNotification({ type: 'success', message: `Zone '${zoneTitle}' deleted from database.` });
        fetchZones();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const cameraZones = zones.filter(
    (z) => z.camera_number === selectedCam?.camera_id || z.camera_id === selectedCam?.id || z.camera_id === selectedCam?.camera_id
  );

  return (
    <div className="p-6 space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42] shadow-sm">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase font-mono flex items-center gap-2">
            <ShieldAlert className="w-5 h-5 text-blue-400" />
            VIRTUAL FENCES & SECURITY ZONES
          </h2>
          <p className="text-xs text-slate-400 font-mono">
            Interactive Multi-Point Polygon Intrusion & Loitering Boundary Configuration
          </p>
        </div>

        {/* Camera Selector Dropdown */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 bg-[#0a0d14] px-3 py-1.5 rounded-lg border border-[#252d42] text-xs font-mono">
            <span className="text-slate-400 font-semibold">CAMERA:</span>
            <select
              value={selectedCameraId}
              onChange={(e) => {
                setSelectedCameraId(e.target.value);
                setPoints([]);
                setIsDrawing(false);
              }}
              className="bg-transparent text-blue-400 font-bold focus:outline-none cursor-pointer"
            >
              {cameras.map((c) => (
                <option key={c.id || c.camera_id} value={c.camera_id} className="bg-[#111622] text-slate-200">
                  {c.camera_id} — {c.name} ({c.role.toUpperCase()})
                </option>
              ))}
            </select>
          </div>

          {!isDrawing && user?.role === 'Administrator' && (
            <button
              onClick={handleStartDrawing}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 transition-all shadow-md shadow-blue-600/20 font-mono shrink-0 cursor-pointer"
            >
              <Plus className="w-4 h-4" /> DRAW NEW ZONE
            </button>
          )}
        </div>
      </div>

      {/* Notifications */}
      {notification && (
        <div className={`p-4 rounded-xl text-xs font-mono flex items-center justify-between border ${
          notification.type === 'success'
            ? 'bg-emerald-950/50 border-emerald-500/60 text-emerald-200'
            : 'bg-red-950/60 border-red-500/60 text-red-200'
        }`}>
          <div className="flex items-center gap-2">
            {notification.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
            )}
            <span>{notification.message}</span>
          </div>
          <button onClick={() => setNotification(null)} className="text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Main Grid: Visual Zone Canvas & Zone Configuration Panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Visual Zone Interactive Canvas */}
        <div className="lg:col-span-2 bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 flex flex-col justify-between shadow-sm">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-2">
              <div className={`w-2.5 h-2.5 rounded-full ${isCamOnline ? 'bg-emerald-500 animate-ping' : 'bg-slate-600'}`} />
              <h3 className="font-bold text-slate-200 text-sm font-mono uppercase">
                LIVE CAMERA CANVAS — {selectedCam?.camera_id || 'CAM-01'} ({selectedCam?.name || 'PERIMETER FEED'})
              </h3>
            </div>
            <div className="flex items-center gap-2 text-xs font-mono">
              <span className={`px-2 py-0.5 rounded font-bold ${
                isDrawing ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40 animate-pulse' : 'bg-blue-500/10 text-blue-400 border border-blue-500/30'
              }`}>
                {isDrawing ? '● DRAWING ACTIVE' : 'INSPECTION MODE'}
              </span>
            </div>
          </div>

          {/* Interactive Canvas Area */}
          <div
            ref={containerRef}
            onClick={handleCanvasClick}
            onMouseMove={handleMouseMove}
            className={`relative aspect-video bg-slate-950 rounded-lg overflow-hidden border border-[#252d42] select-none ${
              isDrawing ? 'cursor-crosshair' : 'cursor-default'
            }`}
          >
            {/* Live Camera Stream Image */}
            {selectedCam && isCamOnline && (
              <img
                src={`/api/cameras/${selectedCam.camera_id}/stream`}
                alt="Live Video Stream"
                className="absolute inset-0 w-full h-full object-cover pointer-events-none"
              />
            )}

            {/* Offline Fallback */}
            {(!selectedCam || !isCamOnline) && (
              <div className="absolute inset-0 flex flex-col items-center justify-center bg-slate-950/80 text-slate-500 font-mono text-xs space-y-2 pointer-events-none">
                <Video className="w-8 h-8 text-slate-600" />
                <span className="font-bold uppercase tracking-wider text-slate-400">CAMERA OFFLINE / FEED INACTIVE</span>
                <span className="text-[11px] text-slate-500">Polygon boundaries will attach to this camera upon startup.</span>
              </div>
            )}

            {/* SVG Polygon Overlay */}
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
              {/* Render Existing Configured Database Zones */}
              {cameraZones.map((z) => {
                if (!z.coordinates || z.coordinates.length < 3) return null;
                const isHighlight = highlightedZoneId === z.id;
                const ptsStr = z.coordinates
                  .map(([x, y]: [number, number]) => `${x * 100}%,${y * 100}%`)
                  .join(' ');

                return (
                  <g key={z.id}>
                    <polygon
                      points={ptsStr}
                      fill={z.is_active ? (isHighlight ? 'rgba(59, 130, 246, 0.35)' : 'rgba(239, 68, 68, 0.15)') : 'rgba(148, 163, 184, 0.08)'}
                      stroke={z.is_active ? (isHighlight ? '#3b82f6' : '#ef4444') : '#64748b'}
                      strokeWidth={isHighlight ? '3' : '2'}
                      strokeDasharray={z.is_active ? '6 4' : '3 3'}
                    />
                    {z.coordinates.map(([x, y]: [number, number], idx: number) => (
                      <circle
                        key={idx}
                        cx={`${x * 100}%`}
                        cy={`${y * 100}%`}
                        r={isHighlight ? 5 : 4}
                        fill={z.is_active ? (isHighlight ? '#3b82f6' : '#ef4444') : '#64748b'}
                      />
                    ))}
                    {/* Zone Label */}
                    <text
                      x={`${z.coordinates[0][0] * 100}%`}
                      y={`${Math.max(4, z.coordinates[0][1] * 100 - 2)}%`}
                      fill={z.is_active ? (isHighlight ? '#60a5fa' : '#f87171') : '#94a3b8'}
                      fontSize="11"
                      fontFamily="monospace"
                      fontWeight="bold"
                    >
                      {z.name.toUpperCase()} {!z.is_active && '(DISABLED)'}
                    </text>
                  </g>
                );
              })}

              {/* Render Active Drawing Polygon */}
              {isDrawing && points.length > 0 && (
                <g>
                  {/* Drawing Polygon Area */}
                  {points.length >= 3 && (
                    <polygon
                      points={points.map(([x, y]) => `${x * 100}%,${y * 100}%`).join(' ')}
                      fill="rgba(59, 130, 246, 0.25)"
                      stroke="#38bdf8"
                      strokeWidth="2.5"
                      strokeDasharray="4 4"
                    />
                  )}

                  {/* Connected Polyline */}
                  <polyline
                    points={points.map(([x, y]) => `${x * 100}%,${y * 100}%`).join(' ')}
                    fill="none"
                    stroke="#38bdf8"
                    strokeWidth="2.5"
                  />

                  {/* Preview line to cursor position */}
                  {hoverCoord && points.length > 0 && (
                    <line
                      x1={`${points[points.length - 1][0] * 100}%`}
                      y1={`${points[points.length - 1][1] * 100}%`}
                      x2={`${hoverCoord.x * 100}%`}
                      y2={`${hoverCoord.y * 100}%`}
                      stroke="#facc15"
                      strokeWidth="1.5"
                      strokeDasharray="3 3"
                    />
                  )}

                  {/* Vertices Handle Circles */}
                  {points.map(([x, y], idx) => (
                    <g key={idx}>
                      <circle cx={`${x * 100}%`} cy={`${y * 100}%`} r="6" fill="#38bdf8" stroke="#ffffff" strokeWidth="1.5" />
                      <text x={`${x * 100 + 1}%`} y={`${y * 100 - 1.5}%`} fill="#38bdf8" fontSize="10" fontFamily="monospace" fontWeight="bold">
                        P{idx + 1}
                      </text>
                    </g>
                  ))}
                </g>
              )}
            </svg>

            {/* Live Drawing Coordinates HUD */}
            {isDrawing && hoverCoord && (
              <div className="absolute top-3 left-3 bg-slate-950/90 border border-blue-500/40 px-2.5 py-1 rounded text-[11px] font-mono text-blue-300 pointer-events-none shadow-lg">
                CLICK TO ADD POINT • X: {hoverCoord.x.toFixed(3)} Y: {hoverCoord.y.toFixed(3)} • POINTS: {points.length}
              </div>
            )}
          </div>

          {/* Canvas Interactive Controls Bar */}
          {isDrawing ? (
            <div className="flex items-center justify-between bg-[#0a0d14] p-3 rounded-lg border border-blue-500/30 text-xs font-mono">
              <div className="flex items-center gap-2 text-slate-300">
                <span className="text-blue-400 font-bold">DRAWING MODE:</span>
                <span>Click on canvas to place polygon vertices ({points.length} points placed). Minimum 3 required.</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleUndoPoint}
                  disabled={points.length === 0}
                  className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 rounded font-semibold flex items-center gap-1 transition-colors cursor-pointer"
                >
                  <Undo2 className="w-3.5 h-3.5" /> UNDO POINT
                </button>
                <button
                  type="button"
                  onClick={handleClearPoints}
                  disabled={points.length === 0}
                  className="px-2.5 py-1 bg-red-950/40 hover:bg-red-900/60 disabled:opacity-40 text-red-300 border border-red-800/40 rounded font-semibold flex items-center gap-1 transition-colors cursor-pointer"
                >
                  CLEAR
                </button>
                <button
                  type="button"
                  onClick={handleCancelDrawing}
                  className="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white rounded font-semibold transition-colors cursor-pointer"
                >
                  CANCEL
                </button>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-between text-xs font-mono text-slate-400 bg-[#0a0d14] p-3 rounded-lg border border-[#252d42]">
              <div className="flex items-center gap-4">
                <span>CONFIGURED ZONES: <strong className="text-blue-400">{cameraZones.length}</strong></span>
                <span>ACTIVE RULES: <strong className="text-emerald-400">{cameraZones.filter(z => z.is_active).length}</strong></span>
              </div>
              <span className="text-slate-500 text-[11px]">Hover over zones in list to highlight boundaries.</span>
            </div>
          )}
        </div>

        {/* Right Column: Zone Editor / Configured Zones List */}
        <div className="space-y-6">
          {/* Zone Parameter Form (When Drawing) */}
          {isDrawing && (
            <div className="bg-[#111622] p-5 rounded-xl border border-blue-500/40 space-y-4 shadow-xl">
              <div className="flex items-center justify-between border-b border-[#252d42] pb-3">
                <h3 className="text-xs font-bold font-mono text-blue-400 uppercase flex items-center gap-1.5">
                  <Sliders className="w-4 h-4" /> ZONE PARAMETERS
                </h3>
                <span className="text-[10px] font-mono text-slate-400">CAMERA: {selectedCam?.camera_id}</span>
              </div>

              <form onSubmit={handleSaveZone} className="space-y-3 text-xs font-mono">
                <div>
                  <label className="text-slate-400 block mb-1">Zone Name</label>
                  <input
                    type="text"
                    required
                    value={zoneName}
                    onChange={(e) => setZoneName(e.target.value)}
                    placeholder="e.g. North Fence Intrusion Zone"
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                  />
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Zone Type</label>
                    <select
                      value={zoneType}
                      onChange={(e) => setZoneType(e.target.value)}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    >
                      <option value="RESTRICTED AREA">RESTRICTED AREA</option>
                      <option value="NO ENTRY">NO ENTRY</option>
                      <option value="PERIMETER FENCE">PERIMETER FENCE</option>
                      <option value="BORDER FENCE">BORDER FENCE</option>
                      <option value="LOITERING ZONE">LOITERING ZONE</option>
                      <option value="ROAD CROSSING">ROAD CROSSING</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Target Object</label>
                    <select
                      value={objectType}
                      onChange={(e) => setObjectType(e.target.value)}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    >
                      <option value="all">ALL OBJECTS</option>
                      <option value="person">PERSON ONLY</option>
                      <option value="car">CAR ONLY</option>
                      <option value="truck">TRUCK ONLY</option>
                      <option value="drone">DRONE ONLY</option>
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="text-slate-400 block mb-1">Severity</label>
                    <select
                      value={severity}
                      onChange={(e) => setSeverity(e.target.value)}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    >
                      <option value="HIGH">HIGH</option>
                      <option value="CRITICAL">CRITICAL</option>
                      <option value="MEDIUM">MEDIUM</option>
                      <option value="LOW">LOW</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Loiter Threshold (s)</label>
                    <input
                      type="number"
                      min="1"
                      max="120"
                      value={loiteringThreshold}
                      onChange={(e) => setLoiteringThreshold(parseInt(e.target.value) || 5)}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    />
                  </div>
                </div>

                <div>
                  <label className="text-slate-400 block mb-1">Alert Cooldown Window (s)</label>
                  <input
                    type="number"
                    min="5"
                    max="300"
                    value={cooldownSec}
                    onChange={(e) => setCooldownSec(parseInt(e.target.value) || 30)}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                  />
                </div>

                <button
                  type="submit"
                  disabled={submitting || points.length < 3}
                  className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded font-bold uppercase tracking-wider transition-all shadow-md shadow-blue-600/20 flex items-center justify-center gap-1.5 cursor-pointer"
                >
                  {submitting ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" /> SAVING ZONE TO DATABASE...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 className="w-4 h-4" /> SAVE NEW ZONE ({points.length} PTS)
                    </>
                  )}
                </button>
              </form>
            </div>
          )}

          {/* Configured Zones List (from Real DB) */}
          <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 shadow-sm">
            <div className="flex justify-between items-center border-b border-[#252d42] pb-3">
              <h3 className="text-xs font-bold font-mono text-slate-200 uppercase flex items-center gap-1.5">
                <Layers className="w-4 h-4 text-blue-400" /> CONFIGURED SURVEILLANCE ZONES
              </h3>
              <div className="flex items-center gap-2 text-[10px] font-mono">
                <span className="text-blue-400 font-bold">{selectedCam?.camera_id || 'CAM'}: {cameraZones.length}</span>
                <span className="text-slate-500">• SYSTEM TOTAL: {zones.length}</span>
              </div>
            </div>

            {loading ? (
              <div className="p-8 text-center text-slate-500 font-mono text-xs space-y-2">
                <RefreshCw className="w-6 h-6 animate-spin mx-auto text-blue-500" />
                <span>LOADING CONFIGURED ZONES...</span>
              </div>
            ) : cameraZones.length === 0 && zones.length === 0 ? (
              <div className="p-8 text-center text-slate-500 font-mono text-xs space-y-2">
                <ShieldAlert className="w-8 h-8 text-slate-600 mx-auto" />
                <div className="font-bold text-slate-300">NO ZONES CONFIGURED</div>
                <p className="text-[11px] text-slate-500">
                  Click <strong className="text-blue-400">DRAW NEW ZONE</strong> above to create real virtual fences in the database.
                </p>
              </div>
            ) : cameraZones.length === 0 ? (
              <div className="p-8 text-center text-slate-500 font-mono text-xs space-y-2">
                <ShieldAlert className="w-8 h-8 text-slate-600 mx-auto" />
                <div className="font-bold text-slate-300">NO ZONES FOR {selectedCam?.camera_id}</div>
                <p className="text-[11px] text-slate-500">
                  Click <strong className="text-blue-400">DRAW NEW ZONE</strong> to create a boundary for {selectedCam?.camera_id}.
                </p>
              </div>
            ) : (
              <div className="space-y-3 max-h-[480px] overflow-y-auto pr-1">
                {cameraZones.map((z) => {
                  const isForSelectedCam = z.camera_number === selectedCam?.camera_id || z.camera_id === selectedCam?.id;
                  const isHighlighted = highlightedZoneId === z.id;

                  return (
                    <div
                      key={z.id}
                      onMouseEnter={() => setHighlightedZoneId(z.id)}
                      onMouseLeave={() => setHighlightedZoneId(null)}
                      className={`p-3 rounded-lg border text-xs space-y-2 transition-all ${
                        isHighlighted
                          ? 'bg-blue-950/40 border-blue-500/70 shadow-md shadow-blue-950/40'
                          : isForSelectedCam
                          ? 'bg-[#0a0d14] border-[#252d42]'
                          : 'bg-[#0a0d14]/60 border-[#1f2538] opacity-80'
                      }`}
                    >
                      <div className="flex justify-between items-start">
                        <div>
                          <div className="font-bold text-slate-200 flex items-center gap-1.5">
                            <span>{z.name}</span>
                            {isForSelectedCam && (
                              <span className="text-[9px] bg-blue-500/20 text-blue-400 px-1.5 py-0.2 rounded border border-blue-500/30">
                                ACTIVE VIEW
                              </span>
                            )}
                          </div>
                          <div className="text-[10px] text-slate-400 font-mono mt-0.5">
                            Camera: <strong className="text-blue-400">{z.camera_number || z.camera_id}</strong> • {z.zone_type}
                          </div>
                        </div>

                        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          z.is_active
                            ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                            : 'bg-slate-800 text-slate-400 border border-slate-700'
                        }`}>
                          {z.is_active ? 'ACTIVE' : 'DISABLED'}
                        </span>
                      </div>

                      <div className="flex items-center justify-between text-[10px] text-slate-400 font-mono pt-1 border-t border-[#252d42]/60">
                        <span>Vertices: <strong>{z.coordinates?.length || 0} pts</strong></span>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={() => handleToggleZone(z.id)}
                            className={`px-2 py-0.5 rounded font-semibold transition-colors flex items-center gap-1 ${
                              z.is_active
                                ? 'bg-slate-800 hover:bg-slate-700 text-slate-300'
                                : 'bg-emerald-950/40 hover:bg-emerald-900/60 text-emerald-300 border border-emerald-800/40'
                            }`}
                            title={z.is_active ? "Disable Zone" : "Enable Zone"}
                          >
                            {z.is_active ? <ToggleRight className="w-3.5 h-3.5 text-emerald-400" /> : <ToggleLeft className="w-3.5 h-3.5 text-slate-500" />}
                            <span>{z.is_active ? 'DEACTIVATE' : 'ACTIVATE'}</span>
                          </button>

                          {user?.role === 'Administrator' && (
                            <button
                              onClick={() => handleDeleteZone(z.id, z.name)}
                              className="p-1 rounded bg-slate-800 hover:bg-red-900/40 text-slate-400 hover:text-red-400 transition-colors"
                              title="Delete Virtual Fence Zone"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
