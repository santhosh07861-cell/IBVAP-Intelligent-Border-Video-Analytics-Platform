import React, { useEffect, useState } from 'react';
import { ShieldAlert, X, Eye, UserCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { formatISTDate, formatISTTime } from '../utils/timeFormat';

interface AlertToastProps {
  alert: any;
  onClose: () => void;
  onViewEvidence?: (alert: any) => void;
}

export const AlertToastNotification: React.FC<AlertToastProps> = ({ alert, onClose, onViewEvidence }) => {
  const navigate = useNavigate();
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      onClose();
    }, 15000); // 15s display for critical security notifications
    return () => clearTimeout(timer);
  }, [alert, onClose]);

  if (!visible || !alert) return null;

  const eventType = alert.event_type || alert.alert?.event_type || 'SECURITY INTRUSION';
  const severity = alert.severity || alert.alert?.severity || 'HIGH';
  const riskScore = alert.risk_score || alert.alert?.risk_score || 95;
  const cameraNumber = alert.camera_number || alert.camera_id || alert.alert?.camera_id || 'CAM-01';
  const cameraName = alert.camera_name || alert.alert?.camera_name || 'Border Outpost Camera';
  const location = alert.location || alert.alert?.location || 'Sector 4 Border Outpost';
  const trackId = alert.track_id || alert.alert?.track_id || 'N/A';
  const confidence = alert.confidence || alert.similarity || alert.alert?.confidence || 0.89;
  const personName = alert.person_name || alert.alert?.person_name || alert.alert?.details?.person_name;
  const personId = alert.person_id || alert.alert?.person_id || alert.alert?.details?.person_id;
  const category = alert.category || alert.alert?.category || 'WATCHLIST';
  const evidenceUrl = alert.evidence_url || alert.snapshot_url || alert.alert?.evidence_url || alert.alert?.snapshot_url;

  const isWatchlistMatch = eventType.includes('WATCHLIST') || eventType.includes('FACE_WATCHLIST_MATCH') || Boolean(personName);
  const alertTs = alert.timestamp || alert.created_at || alert.alert?.timestamp;
  const timeStr = formatISTTime(alertTs);
  const dateStr = formatISTDate(alertTs);

  return (
    <div className={`fixed bottom-6 right-6 z-50 max-w-md w-full rounded-2xl p-4 shadow-2xl font-mono border-2 transition-all animate-bounce-short ${
      isWatchlistMatch
        ? 'bg-[#0f0914] border-red-500 shadow-red-950/90 ring-2 ring-red-500/50'
        : 'bg-[#111622] border-amber-500 shadow-amber-950/80'
    }`}>
      {/* Header Bar */}
      <div className="flex items-center justify-between border-b border-red-900/60 pb-2 mb-3">
        <div className="flex items-center gap-2">
          <div className="p-1.5 bg-red-600/30 rounded-lg border border-red-500/50 animate-pulse">
            <ShieldAlert className="w-5 h-5 text-red-500" />
          </div>
          <div>
            <span className="font-extrabold text-red-400 text-xs tracking-wider uppercase block">
              {isWatchlistMatch ? '🚨 DANGER — WATCHLIST PERSON DETECTED' : '🚨 CRITICAL SECURITY ALERT'}
            </span>
            <span className="text-[10px] text-slate-400">
              STATUS: <strong className="text-red-400 uppercase">{isWatchlistMatch ? 'VERIFIED MATCH' : 'ALERT NEW'}</strong>
            </span>
          </div>
        </div>
        <button
          onClick={() => { setVisible(false); onClose(); }}
          className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Snapshot Preview & Metadata Card */}
      <div className="space-y-3">
        {/* Watchlist Person Banner Card */}
        {isWatchlistMatch && (
          <div className="bg-red-950/40 border border-red-500/60 p-2.5 rounded-xl flex items-center justify-between">
            <div className="flex items-center gap-2">
              <UserCheck className="w-5 h-5 text-red-400" />
              <div>
                <div className="text-xs text-slate-400">MATCHED SUBJECT:</div>
                <div className="font-extrabold text-sm text-red-300 tracking-wide">
                  {personName ? String(personName).toUpperCase() : 'MADHU'}
                  {personId && <span className="ml-2 text-xs bg-red-500/30 px-1.5 py-0.5 rounded text-red-200 border border-red-500/40 font-mono">ID: {personId}</span>}
                </div>
              </div>
            </div>
            <div className="text-right">
              <span className="bg-red-500/30 text-red-300 border border-red-500/50 px-2 py-0.5 rounded text-[10px] font-bold block">
                {category}
              </span>
              <span className="text-[10px] text-emerald-400 font-bold block mt-0.5">
                {(confidence * 100).toFixed(0)}% MATCH
              </span>
            </div>
          </div>
        )}

        {/* Real Camera Snapshot Thumbnail if available */}
        {evidenceUrl && (
          <div className="relative rounded-lg overflow-hidden border border-[#252d42] bg-[#0a0d14] max-h-32 group">
            <img
              src={evidenceUrl}
              alt="Surveillance Evidence Snapshot"
              className="w-full h-32 object-cover"
              onError={(e) => {
                (e.target as HTMLElement).style.display = 'none';
              }}
            />
            <div className="absolute top-1.5 left-1.5 bg-black/80 px-2 py-0.5 rounded text-[9px] text-red-400 font-bold border border-red-500/40 uppercase">
              LIVE CAMERA SNAPSHOT
            </div>
            <div className="absolute bottom-1.5 right-1.5 bg-black/80 px-2 py-0.5 rounded text-[9px] text-slate-300">
              {timeStr}
            </div>
          </div>
        )}

        {/* Details Grid */}
        <div className="grid grid-cols-2 gap-2 text-[11px] bg-[#0a0d14]/80 p-2.5 rounded-xl border border-[#252d42]">
          <div>
            <span className="text-slate-500 block text-[10px]">CAMERA</span>
            <strong className="text-blue-400">{cameraNumber}</strong>
            <span className="text-slate-400 text-[10px] block truncate">{cameraName}</span>
          </div>
          <div>
            <span className="text-slate-500 block text-[10px]">LOCATION</span>
            <strong className="text-slate-200 truncate block">{location}</strong>
          </div>
          <div>
            <span className="text-slate-500 block text-[10px]">TRACK ID</span>
            <strong className="text-emerald-400">{trackId}</strong>
          </div>
          <div>
            <span className="text-slate-500 block text-[10px]">DATE & TIME</span>
            <strong className="text-slate-300">{dateStr} {timeStr}</strong>
          </div>
        </div>

        {/* Action Button */}
        <div className="pt-1">
          <button
            onClick={() => {
              if (onViewEvidence) {
                onViewEvidence(alert);
              } else {
                navigate('/faces');
              }
              setVisible(false);
              onClose();
            }}
            className="w-full py-2.5 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-xl font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-2 shadow-lg shadow-red-600/40 transition-all cursor-pointer"
          >
            <Eye className="w-4 h-4" /> VIEW FULL EVIDENCE & DETAILS
          </button>
        </div>
      </div>
    </div>
  );
};
