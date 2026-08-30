import React, { useEffect, useRef, useState } from 'react';
import { Camera, AlertOctagon, Bell, Users, FileText, ArrowUpRight, Plus, Shield, Eye } from 'lucide-react';
import { Link, useNavigate } from 'react-router-dom';
import { useWebSocket } from '../context/WebSocketContext';
import { useAuth } from '../context/AuthContext';
import { useCameras } from '../context/CameraContext';
import { LiveVideoCanvas } from '../components/LiveVideoCanvas';
import { AlertToastNotification } from '../components/AlertToastNotification';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';

import { formatISTDateTime } from '../utils/timeFormat';

export const Dashboard: React.FC = () => {
  const [kpis, setKpis] = useState<any>({
    active_alerts: 0,
    critical_incidents: 0,
    people_detected: 0,
    anpr_events: 0
  });
  const [activeToastAlert, setActiveToastAlert] = useState<any | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<any | null>(null);

  const navigate = useNavigate();
  // ✅ Consume canonical latestAlerts from shared WebSocket context — no competing local state
  const { lastAlert, latestAlerts, getCameraTelemetry } = useWebSocket();
  const { primaryCamera, cameras } = useCameras();
  const { token } = useAuth();
  const lastAlertIdRef = useRef<string | null>(null);

  const fetchKpis = async () => {
    try {
      const headers: any = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/analytics/kpis', { headers });
      if (res.ok) {
        const data = await res.json();
        setKpis(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Only poll KPIs (counters) — alerts come from canonical WebSocket store
  useEffect(() => {
    fetchKpis();
    const interval = setInterval(fetchKpis, 5000);
    return () => clearInterval(interval);
  }, [token]);

  // Show toast notification when a NEW alert arrives via WebSocket
  useEffect(() => {
    if (lastAlert) {
      const alertId = lastAlert.id || lastAlert.alert_id;
      if (alertId && alertId !== lastAlertIdRef.current) {
        lastAlertIdRef.current = alertId;
        setActiveToastAlert(lastAlert);
        // Refresh KPI counters to reflect the new alert
        fetchKpis();
      }
    }
  }, [lastAlert]);

  const primaryTelemetry = getCameraTelemetry(primaryCamera?.camera_id);
  const primaryOnline = primaryCamera && (primaryCamera.status === 'ONLINE' || (primaryTelemetry?.fps && primaryTelemetry.fps > 0));

  const totalCameras = cameras.length;
  const onlineCameras = cameras.filter(c => c.status === 'ONLINE' || (getCameraTelemetry(c.camera_id)?.fps || 0) > 0).length;

  return (
    <div className="p-6 space-y-6">
      {/* Visual Alert Toast */}
      {activeToastAlert && (
        <AlertToastNotification
          alert={activeToastAlert}
          onClose={() => setActiveToastAlert(null)}
          onViewEvidence={(al) => {
            if (al.evidence_url || al.alert?.evidence_url) {
              setSelectedEvidence(al);
            } else {
              navigate('/evidence');
            }
          }}
        />
      )}

      {/* Evidence Detail Modal */}
      {selectedEvidence && (
        <EvidenceDetailModal
          item={selectedEvidence}
          onClose={() => setSelectedEvidence(null)}
        />
      )}

      {/* Top Section Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42] shadow-sm">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-600/15 border border-blue-500/30 flex items-center justify-center text-blue-400 shrink-0">
            <Shield className="w-5 h-5" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2 font-mono leading-tight">
              SURVEILLANCE COMMAND OVERVIEW
            </h2>
            <p className="text-xs text-slate-400 font-mono mt-0.5 leading-tight">
              REAL-TIME DETECTION TELEMETRY & LIVE SECURITY ALERTS
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2.5 flex-wrap sm:flex-nowrap shrink-0">
          <Link
            to="/cameras?add=true"
            className="px-3.5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold uppercase tracking-wider transition-all shadow-md shadow-emerald-950/30 flex items-center gap-1.5 font-mono shrink-0"
          >
            <Plus className="w-3.5 h-3.5" /> CONNECT CAMERA
          </Link>
          <Link
            to="/surveillance"
            className="px-3.5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold uppercase tracking-wider transition-all shadow-md shadow-blue-950/30 flex items-center gap-1.5 font-mono shrink-0"
          >
            OPEN MULTI-CAM GRID
          </Link>
        </div>
      </div>

      {/* KPI Cards Grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] hover:border-blue-500/40 transition-colors">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">CAMERAS ONLINE</span>
            <Camera className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-emerald-400">
            {onlineCameras} <span className="text-xs text-slate-500 font-normal">/ {totalCameras}</span>
          </div>
        </div>

        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] hover:border-amber-500/40 transition-colors">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">ACTIVE ALERTS</span>
            <Bell className={`w-4 h-4 ${(kpis?.active_alerts ?? 0) > 0 ? 'text-amber-400 animate-pulse' : 'text-slate-500'}`} />
          </div>
          <div className="text-2xl font-bold font-mono text-amber-400">
            {kpis?.active_alerts ?? 0}
          </div>
        </div>

        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] hover:border-red-500/40 transition-colors">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">CRITICAL INCIDENTS</span>
            <AlertOctagon className={`w-4 h-4 ${(kpis?.critical_incidents ?? 0) > 0 ? 'text-red-400 animate-pulse' : 'text-slate-500'}`} />
          </div>
          <div className="text-2xl font-bold font-mono text-red-400">
            {kpis?.critical_incidents ?? 0}
          </div>
        </div>

        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] hover:border-blue-500/40 transition-colors">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">PEOPLE DETECTED</span>
            <Users className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-blue-400">
            {kpis?.people_detected ?? 0}
          </div>
        </div>

        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] hover:border-purple-500/40 transition-colors">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-mono text-slate-400">ANPR EVENTS</span>
            <FileText className="w-4 h-4 text-purple-400" />
          </div>
          <div className="text-2xl font-bold font-mono text-purple-400">
            {kpis?.anpr_events ?? 0}
          </div>
        </div>
      </div>

      {/* Main Section: Primary Camera Feed & Live Alerts Feed */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Primary Camera Live Video Canvas */}
        <div className="lg:col-span-2 bg-[#111622] p-5 rounded-xl border border-[#252d42] flex flex-col justify-between space-y-4">
          <div className="flex justify-between items-center">
            <div className="flex items-center gap-2">
              <div className={`w-2.5 h-2.5 rounded-full ${primaryOnline ? 'bg-emerald-500 animate-ping' : 'bg-slate-600'}`} />
              <h3 className="font-bold text-slate-200 text-sm font-mono">
                {primaryCamera ? `PRIMARY FEED - ${primaryCamera.name} (${primaryCamera.camera_id})` : 'PRIMARY CAMERA FEED (UNASSIGNED)'}
              </h3>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono px-2 py-0.5 rounded font-bold text-blue-400 bg-blue-500/10 border border-blue-500/30">
                ROLE: PRIMARY
              </span>
              <span className={`text-xs font-mono px-2 py-0.5 rounded font-bold ${
                primaryOnline ? 'text-emerald-400 bg-emerald-500/10 border border-emerald-500/30' : 'text-slate-400 bg-slate-800 border border-slate-700'
              }`}>
                {primaryOnline ? 'ONLINE' : 'OFFLINE'}
              </span>
            </div>
          </div>

          <LiveVideoCanvas
            cameraId={primaryCamera?.camera_id}
            cameraName={primaryCamera?.name || "PRIMARY BORDER FEED"}
            detections={primaryTelemetry?.detections || []}
            faces={primaryTelemetry?.faces || []}
            fps={primaryOnline ? (primaryTelemetry?.fps || primaryCamera?.fps || 25.0) : 0.0}
            latencyMs={primaryTelemetry?.latency_ms || 0.0}
            inferenceMode={primaryOnline ? (primaryTelemetry?.inference_mode || 'REAL AI | INFERENCE RUNNING') : 'CAMERA OFFLINE'}
            cameraRole="primary"
          />
        </div>

        {/* Live Alerts Feed */}
        <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] flex flex-col justify-between">
          <div className="flex justify-between items-center mb-4">
            <h3 className="font-bold text-slate-200 text-sm flex items-center gap-2 font-mono">
              <Bell className="w-4 h-4 text-amber-400" />
              REAL-TIME SECURITY ALERTS
            </h3>
            <Link to="/alerts" className="text-xs text-blue-400 hover:underline flex items-center gap-1 font-mono">
              VIEW ALL <ArrowUpRight className="w-3 h-3" />
            </Link>
          </div>

          <div className="space-y-3 overflow-y-auto max-h-[420px] pr-1">
            {latestAlerts.length === 0 ? (
              <div className="p-8 text-center text-slate-500 font-mono text-xs">
                No active security alerts recorded. Active cameras are continuously analyzed by real AI detectors.
              </div>
            ) : (
              latestAlerts.slice(0, 8).map((al) => {
                const isWatchlist = (al.event_type || '').includes('WATCHLIST') || (al.event_type || '').includes('THREAT') || Boolean(al.person_name && al.category === 'WATCHLIST');
                const isUnknown = (al.event_type || '').includes('UNKNOWN');
                const isCritical = al.severity === 'CRITICAL' || isWatchlist;
                const isAcknowledged = al.status === 'ACKNOWLEDGED' || al.status === 'RESOLVED';

                return (
                  <div
                    key={al.id || al.alert_id}
                    className={`p-3 rounded-lg border text-xs space-y-1 transition-all ${
                      isAcknowledged
                        ? 'bg-slate-900/60 border-slate-700/40 text-slate-500 opacity-60'
                        : isCritical
                        ? 'bg-red-950/50 border-red-500/70 text-red-200 shadow-md shadow-red-950/50'
                        : isUnknown || al.severity === 'HIGH'
                        ? 'bg-amber-950/40 border-amber-500/50 text-amber-200'
                        : 'bg-[#1a2030] border-[#252d42] text-slate-200'
                    }`}
                  >
                    <div className="flex items-center justify-between font-mono">
                      <span className={`font-bold flex items-center gap-1.5 ${isAcknowledged ? 'text-slate-500' : isCritical ? 'text-red-400 font-extrabold' : 'text-amber-400'}`}>
                        {isWatchlist
                          ? `🚨 WATCHLIST: ${al.person_name || 'THREAT'}`
                          : isUnknown
                          ? '⚠️ UNKNOWN / VERIFICATION REQ'
                          : al.event_type}
                        {isAcknowledged && <span className="text-[9px] text-slate-600 ml-1">[{al.status}]</span>}
                      </span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                        isAcknowledged ? 'bg-slate-800 text-slate-600' : isCritical ? 'bg-red-500/30 text-red-300 border border-red-500/40' : 'bg-amber-500/20 text-amber-400'
                      }`}>
                        {al.severity} ({al.risk_score || 75}/100)
                      </span>
                    </div>

                    <div className="text-slate-400 font-mono text-[11px] flex justify-between items-center">
                      <span>Camera: <strong className="text-blue-400">{al.camera_display || (al.camera_number && al.camera_name ? `${al.camera_number} - ${al.camera_name}` : (al.camera_number || al.camera_id))}</strong> • {al.location || 'Campus Perimeter'}</span>
                      {al.evidence_url && !isAcknowledged && (
                        <button
                          onClick={() => setSelectedEvidence(al)}
                          className="text-[10px] text-red-300 hover:text-white font-bold flex items-center gap-1 bg-red-600/30 px-2 py-0.5 rounded border border-red-500/40 cursor-pointer"
                        >
                          <Eye className="w-3 h-3" /> EVIDENCE
                        </button>
                      )}
                    </div>
                    <div className="text-[10px] text-slate-400 font-mono">
                      {formatISTDateTime(al.timestamp || al.created_at)}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
