import React, { useEffect, useState } from 'react';
import { Bell, CheckCircle2, ShieldAlert } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const AlertList: React.FC = () => {
  const [alerts, setAlerts] = useState<any[]>([]);
  const { token } = useAuth();

  const fetchAlerts = async () => {
    try {
      const res = await fetch('/api/alerts?limit=50', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setAlerts(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchAlerts();
  }, []);

  const handleAcknowledge = async (alertId: string) => {
    try {
      const res = await fetch(`/api/alerts/${alertId}/acknowledge`, {
        method: 'PUT',
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        fetchAlerts();
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">LIVE ALERTS STREAM</h2>
          <p className="text-xs text-slate-400 font-mono">Real-Time Threat Notifications & Operator Acknowledgement Queue</p>
        </div>
      </div>

      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3">Timestamp</th>
              <th className="p-3">Event Type</th>
              <th className="p-3">Camera</th>
              <th className="p-3">Severity</th>
              <th className="p-3">Risk Score</th>
              <th className="p-3">Status</th>
              <th className="p-3">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {alerts.map((al) => (
              <tr key={al.id} className="hover:bg-[#1a2030] transition-colors">
                <td className="p-3 text-slate-400">{new Date(al.timestamp).toLocaleString()}</td>
                <td className="p-3 font-bold text-amber-400">{al.event_type}</td>
                <td className="p-3 text-blue-400">{al.camera_id}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    al.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'
                  }`}>
                    {al.severity}
                  </span>
                </td>
                <td className="p-3 font-bold text-red-400">{al.risk_score}/100</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    al.status === 'NEW' ? 'bg-red-500/20 text-red-400' : 'bg-emerald-500/20 text-emerald-400'
                  }`}>
                    {al.status}
                  </span>
                </td>
                <td className="p-3">
                  {al.status === 'NEW' ? (
                    <button
                      onClick={() => handleAcknowledge(al.id)}
                      className="px-2.5 py-1 bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30 rounded text-[11px] font-semibold transition-colors flex items-center gap-1"
                    >
                      <CheckCircle2 className="w-3 h-3" /> Acknowledge
                    </button>
                  ) : (
                    <span className="text-slate-500 text-[10px]">ACKNOWLEDGED</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
