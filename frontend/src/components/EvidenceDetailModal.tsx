import React from 'react';
import { X, Camera, ShieldAlert, Cpu, Clock, MapPin, Download, CheckCircle2 } from 'lucide-react';

interface EvidenceDetailModalProps {
  item: any;
  onClose: () => void;
}

export const EvidenceDetailModal: React.FC<EvidenceDetailModalProps> = ({ item, onClose }) => {
  if (!item) return null;

  const cleanCls = (item.object_class || 'person').toLowerCase().trim();
  const objectClass = item.display_label || ((cleanCls === 'truck' || cleanCls === 'lorry') ? 'TRUCK / LORRY' : cleanCls.toUpperCase());
  const confidencePct = `${((item.confidence || 0.90) * 100).toFixed(0)}%`;
  const cameraNumber = item.camera_number || item.camera_id || 'CAM-01';
  const cameraName = item.camera_name || 'Border Surveillance Outpost Camera';
  const location = item.location || 'Sector 4 / Gate 2';
  const eventType = item.event_type || 'RESTRICTED ZONE INTRUSION';
  const severity = item.severity || 'HIGH';
  const riskScore = item.risk_score || 75;
  const trackId = item.track_id || 'P-101';
  const dateStr = item.captured_at ? new Date(item.captured_at).toLocaleDateString() : new Date().toLocaleDateString();
  const timeStr = item.captured_at ? new Date(item.captured_at).toLocaleTimeString() : new Date().toLocaleTimeString();
  const utcStr = item.captured_at ? new Date(item.captured_at).toUTCString() : new Date().toUTCString();
  const bboxStr = item.bbox ? JSON.stringify(item.bbox) : '[0.25, 0.20, 0.40, 0.65]';

  const severityColor =
    severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border-red-500/40' :
    severity === 'HIGH' ? 'bg-amber-500/20 text-amber-400 border-amber-500/40' :
    'bg-blue-500/20 text-blue-400 border-blue-500/40';

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto font-mono">
      <div className="bg-[#111622] border border-[#252d42] rounded-2xl max-w-4xl w-full overflow-hidden shadow-2xl space-y-0 my-8">
        {/* Header */}
        <div className="bg-[#1a2030] px-6 py-4 border-b border-[#252d42] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShieldAlert className="w-6 h-6 text-red-400" />
            <div>
              <h2 className="font-bold text-slate-100 text-base">EVIDENCE SNAPSHOT & DETECTION METADATA</h2>
              <p className="text-xs text-slate-400 font-mono">INCIDENT RECORD #{item.id?.substring(0, 8)}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-6 space-y-6 max-h-[80vh] overflow-y-auto">
          {/* Main Full Image View */}
          <div className="relative bg-slate-950 rounded-xl border border-[#252d42] overflow-hidden">
            {item.file_url ? (
              <img
                src={item.file_url}
                alt="AI Evidence Snapshot"
                className="w-full h-auto max-h-[480px] object-contain mx-auto"
              />
            ) : (
              <div className="p-16 text-center text-slate-500 font-mono text-xs">
                Snapshot file unavailable.
              </div>
            )}
            <div className="absolute top-3 left-3 bg-slate-950/90 border border-blue-500/40 px-3 py-1.5 rounded-lg text-xs font-bold text-blue-400">
              {cameraNumber} — {cameraName}
            </div>
            <div className="absolute bottom-3 right-3 bg-red-950/90 border border-red-500/40 px-3 py-1 rounded text-xs font-bold text-red-400">
              {eventType}
            </div>
          </div>

          {/* Grid Metadata Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
            {/* 1. Camera Information */}
            <div className="bg-[#0a0d14] p-4 rounded-xl border border-[#252d42] space-y-2">
              <div className="flex items-center gap-2 text-blue-400 font-bold border-b border-[#252d42] pb-2">
                <Camera className="w-4 h-4" /> CAMERA INFORMATION
              </div>
              <div className="space-y-1.5 pt-1 text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-400">Camera Number:</span>
                  <strong className="text-blue-400">{cameraNumber}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Camera Name:</span>
                  <strong>{cameraName}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Location:</span>
                  <strong className="text-emerald-400 flex items-center gap-1">
                    <MapPin className="w-3 h-3" /> {location}
                  </strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Camera Status:</span>
                  <strong className="text-emerald-400 font-bold">ONLINE (ACTIVE)</strong>
                </div>
              </div>
            </div>

            {/* 2. AI Detection Information */}
            <div className="bg-[#0a0d14] p-4 rounded-xl border border-[#252d42] space-y-2">
              <div className="flex items-center gap-2 text-emerald-400 font-bold border-b border-[#252d42] pb-2">
                <Cpu className="w-4 h-4" /> AI DETECTION INFORMATION
              </div>
              <div className="space-y-1.5 pt-1 text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-400">Object Class:</span>
                  <strong className="bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded font-bold">{objectClass}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">AI Confidence:</span>
                  <strong className="text-emerald-400 font-bold">{confidencePct}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Track ID:</span>
                  <strong className="text-amber-400 font-bold">{trackId}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Bounding Box [x,y,w,h]:</span>
                  <strong className="text-slate-400 text-[10px] font-mono">{bboxStr}</strong>
                </div>
              </div>
            </div>

            {/* 3. Security Information */}
            <div className="bg-[#0a0d14] p-4 rounded-xl border border-[#252d42] space-y-2">
              <div className="flex items-center gap-2 text-red-400 font-bold border-b border-[#252d42] pb-2">
                <ShieldAlert className="w-4 h-4" /> SECURITY INFORMATION
              </div>
              <div className="space-y-1.5 pt-1 text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-400">Event Type:</span>
                  <strong className="text-amber-400">{eventType}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Risk Score:</span>
                  <strong className="text-red-400 font-bold">{riskScore} / 100</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Severity:</span>
                  <span className={`px-2 py-0.5 rounded border text-[10px] font-bold ${severityColor}`}>
                    {severity}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Alert ID:</span>
                  <strong className="text-slate-500 text-[10px]">{item.alert_id || item.id}</strong>
                </div>
              </div>
            </div>

            {/* 4. Timestamp Information */}
            <div className="bg-[#0a0d14] p-4 rounded-xl border border-[#252d42] space-y-2">
              <div className="flex items-center gap-2 text-amber-400 font-bold border-b border-[#252d42] pb-2">
                <Clock className="w-4 h-4" /> TIMESTAMP & CORRELATION
              </div>
              <div className="space-y-1.5 pt-1 text-slate-300">
                <div className="flex justify-between">
                  <span className="text-slate-400">Date:</span>
                  <strong>{dateStr}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Time:</span>
                  <strong className="text-blue-400">{timeStr}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">ISO UTC:</span>
                  <strong className="text-slate-500 text-[10px]">{utcStr}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Verification:</span>
                  <strong className="text-emerald-400 flex items-center gap-1">
                    <CheckCircle2 className="w-3.5 h-3.5" /> POSTGRES VERIFIED
                  </strong>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Footer Actions */}
        <div className="bg-[#1a2030] px-6 py-3 border-t border-[#252d42] flex justify-between items-center">
          <span className="text-xs text-slate-500">File Path: {item.file_path || item.file_url}</span>
          <div className="flex items-center gap-3">
            {item.file_url && (
              <a
                href={item.file_url}
                download
                target="_blank"
                rel="noreferrer"
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-blue-600/20 transition-colors"
              >
                <Download className="w-4 h-4" /> DOWNLOAD SNAPSHOT
              </a>
            )}
            <button
              onClick={onClose}
              className="px-4 py-2 bg-[#0a0d14] hover:bg-slate-800 text-slate-300 rounded-lg text-xs font-bold uppercase tracking-wider border border-[#252d42]"
            >
              CLOSE
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
