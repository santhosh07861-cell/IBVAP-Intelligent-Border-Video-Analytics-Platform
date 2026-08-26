import React, { useEffect, useState } from 'react';
import { ShieldAlert, X, Eye, BellRing } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

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
    }, 10000); // Auto dismiss after 10 seconds
    return () => clearTimeout(timer);
  }, [alert, onClose]);

  if (!visible || !alert) return null;

  const eventType = alert.event_type || alert.alert?.event_type || 'SECURITY INTRUSION';
  const severity = alert.severity || alert.alert?.severity || 'HIGH';
  const riskScore = alert.risk_score || alert.alert?.risk_score || 75;
  const cameraNumber = alert.camera_number || alert.camera_id || alert.alert?.camera_id || 'CAM-01';
  const location = alert.location || alert.alert?.location || 'Sector 4 Border Outpost';
  const objectClass = alert.object_class || alert.alert?.object_class || 'person';
  const trackId = alert.track_id || alert.alert?.track_id || 'P-101';
  const confidence = alert.confidence || alert.alert?.confidence || 0.88;
  const timeStr = alert.timestamp ? new Date(alert.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();

  return (
    <div className="fixed bottom-6 right-6 z-50 max-w-sm w-full bg-[#111622] border-2 border-red-500 rounded-xl p-4 shadow-2xl shadow-red-950/80 animate-bounce-short font-mono">
      <div className="flex items-center justify-between border-b border-red-900/50 pb-2 mb-3">
        <div className="flex items-center gap-2">
          <ShieldAlert className="w-5 h-5 text-red-500 animate-pulse" />
          <span className="font-bold text-red-400 text-xs tracking-wider uppercase">🚨 SECURITY ALERT</span>
        </div>
        <button
          onClick={() => { setVisible(false); onClose(); }}
          className="text-slate-400 hover:text-white p-1 rounded"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="space-y-2 text-xs">
        <div className="flex justify-between items-center">
          <span className="font-bold text-amber-400 text-sm">{eventType}</span>
          <span className="bg-red-500/20 text-red-400 border border-red-500/40 px-2 py-0.5 rounded text-[10px] font-bold">
            {severity} ({riskScore}/100)
          </span>
        </div>

        <div className="grid grid-cols-2 gap-1 text-[11px] text-slate-300">
          <div>Object: <strong className="text-blue-400 uppercase">{objectClass}</strong></div>
          <div>Track ID: <strong className="text-emerald-400">{trackId}</strong></div>
          <div>Confidence: <strong>{(confidence * 100).toFixed(0)}%</strong></div>
          <div>Time: <strong className="text-slate-400">{timeStr}</strong></div>
        </div>

        <div className="text-[11px] text-slate-400 truncate">
          Camera: <strong className="text-blue-400">{cameraNumber}</strong> • {location}
        </div>

        <div className="pt-2 flex justify-end gap-2 border-t border-[#252d42]">
          <button
            onClick={() => {
              if (onViewEvidence) {
                onViewEvidence(alert);
              } else {
                navigate('/evidence');
              }
              setVisible(false);
              onClose();
            }}
            className="w-full py-2 bg-red-600 hover:bg-red-500 text-white rounded font-bold text-xs uppercase tracking-wider flex items-center justify-center gap-1.5 shadow-lg shadow-red-600/30 transition-colors"
          >
            <Eye className="w-4 h-4" /> VIEW EVIDENCE & DETAILS
          </button>
        </div>
      </div>
    </div>
  );
};
