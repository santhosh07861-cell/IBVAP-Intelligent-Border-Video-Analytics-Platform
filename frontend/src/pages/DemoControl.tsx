import React, { useState } from 'react';
import { PlaySquare, Upload, Zap, CheckCircle2, AlertOctagon, ShieldAlert, Cpu } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const DemoControl: React.FC = () => {
  const [triggering, setTriggering] = useState(false);
  const [startingStream, setStartingStream] = useState(false);
  const [streamActive, setStreamActive] = useState(false);
  const [lastIncident, setLastIncident] = useState<any>(null);
  const { token } = useAuth();
  const navigate = useNavigate();

  const handleStartStream = async (sourceType: string = 'MP4', sourcePath: string = 'storage/demo_videos/border_patrol.mp4') => {
    setStartingStream(true);
    try {
      const res = await fetch('/api/demo/start-stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          camera_id: 'CAM-01',
          source_type: sourceType,
          source_path: sourcePath,
          fallback_mode: true
        })
      });
      if (res.ok) {
        setStreamActive(true);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setStartingStream(false);
    }
  };

  const handleStopStream = async () => {
    try {
      await fetch('/api/demo/stop-stream?camera_id=CAM-01', {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      setStreamActive(false);
    } catch (e) {
      console.error(e);
    }
  };

  const handleTriggerIntrusion = async () => {
    setTriggering(true);
    try {
      const res = await fetch('/api/demo/trigger-intrusion', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          camera_id: 'CAM-01',
          is_night: true,
          in_restricted_zone: true,
          fence_crossed: true,
          loitering: true
        })
      });
      if (res.ok) {
        const data = await res.json();
        setLastIncident(data);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setTriggering(false);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-red-500/40">
        <div className="flex items-center gap-3">
          <div className="p-2.5 bg-red-500/20 text-red-400 rounded-lg border border-red-500/40">
            <PlaySquare className="w-6 h-6 animate-pulse" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">SIH 2026 DEMO CONTROL CENTER</h2>
              <span className="bg-red-500/20 text-red-400 text-xs font-mono font-bold px-2 py-0.5 rounded border border-red-500/40">
                EVALUATION WORKFLOW
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono">Execute End-to-End Border Intrusion & AI Analytics Demonstration</p>
          </div>
        </div>
      </div>

      {/* Main Trigger Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="bg-[#111622] p-6 rounded-xl border border-[#252d42] space-y-4">
          <h3 className="text-xs font-bold font-mono text-slate-200 uppercase flex items-center gap-2">
            <Zap className="w-4 h-4 text-amber-400" />
            1-CLICK SIH DEMO WORKFLOW TRIGGER
          </h3>
          <p className="text-xs text-slate-400 font-mono leading-relaxed">
            Simulates the complete SIH evaluation pipeline: MP4 Feed Ingestion → YOLO Person Detection → Track #104 Assigned → Virtual Fence Intrusion → Night Condition → Correlated Risk Score (90/100) → High Alert → Snapshot Evidence → Real-Time WebSockets Broadcast.
          </p>

          <button
            onClick={handleTriggerIntrusion}
            disabled={triggering}
            className="w-full py-3 bg-red-600 hover:bg-red-500 text-white font-bold rounded-lg text-xs font-mono tracking-wider uppercase transition-colors shadow-lg shadow-red-600/20 flex items-center justify-center gap-2 disabled:opacity-50"
          >
            <Zap className="w-4 h-4" />
            {triggering ? 'EXECUTING SIH WORKFLOW...' : 'TRIGGER SIH INTRUSION WORKFLOW'}
          </button>

          {lastIncident && (
            <div className="p-4 bg-emerald-950/40 border border-emerald-500/40 rounded-lg text-xs font-mono space-y-2">
              <div className="flex items-center gap-2 text-emerald-400 font-bold">
                <CheckCircle2 className="w-4 h-4" />
                <span>WORKFLOW EXECUTED SUCCESSFULLY!</span>
              </div>
              <div className="text-slate-300">Incident: {lastIncident.incident_number}</div>
              <div className="text-amber-400">Risk Score: {lastIncident.risk_score}/100 ({lastIncident.severity})</div>
              <button
                onClick={() => navigate(`/incidents/${lastIncident.incident_id}`)}
                className="mt-2 px-3 py-1.5 bg-blue-600 text-white rounded text-[11px] font-bold uppercase tracking-wider hover:bg-blue-500 transition-colors"
              >
                OPEN INCIDENT EVIDENCE PAGE &rarr;
              </button>
            </div>
          )}
        </div>

        {/* Video Source Controls */}
        <div className="bg-[#111622] p-6 rounded-xl border border-[#252d42] space-y-4">
          <h3 className="text-xs font-bold font-mono text-slate-200 uppercase flex items-center gap-2">
            <Upload className="w-4 h-4 text-blue-400" />
            START / STOP VIDEO STREAM INGESTION
          </h3>
          <p className="text-xs text-slate-400 font-mono leading-relaxed">
            Start real-time stream ingestion on demand. When stopped, the system returns to an empty 0-activity state.
          </p>

          <div className="grid grid-cols-2 gap-3">
            <button
              onClick={() => handleStartStream('MP4', 'storage/demo_videos/border_patrol.mp4')}
              disabled={startingStream}
              className="py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-bold rounded-lg text-xs font-mono uppercase transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50"
            >
              <PlaySquare className="w-4 h-4" />
              START MP4 STREAM
            </button>
            <button
              onClick={() => handleStartStream('WEBCAM', '0')}
              disabled={startingStream}
              className="py-2.5 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded-lg text-xs font-mono uppercase transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50"
            >
              <Cpu className="w-4 h-4" />
              START WEBCAM
            </button>
          </div>

          <button
            onClick={handleStopStream}
            className="w-full py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 font-bold rounded-lg text-xs font-mono uppercase transition-colors border border-slate-700"
          >
            STOP ALL STREAMS (RETURN TO 0 STATE)
          </button>
        </div>
      </div>
    </div>
  );
};
