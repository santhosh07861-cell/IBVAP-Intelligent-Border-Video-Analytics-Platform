import React, { useEffect, useState } from 'react';
import { AlertOctagon, ArrowUpRight } from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

export const IncidentList: React.FC = () => {
  const [incidents, setIncidents] = useState<any[]>([]);
  const { token } = useAuth();

  const fetchIncidents = async () => {
    try {
      const res = await fetch('/api/incidents?limit=50', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchIncidents();
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">INCIDENT MANAGEMENT</h2>
          <p className="text-xs text-slate-400 font-mono">Correlated Security Incidents, Investigation & Resolution Workflows</p>
        </div>
      </div>

      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3">Incident #</th>
              <th className="p-3">Title</th>
              <th className="p-3">Camera</th>
              <th className="p-3">Severity</th>
              <th className="p-3">Risk Score</th>
              <th className="p-3">Status</th>
              <th className="p-3">Created</th>
              <th className="p-3">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {incidents.map((inc) => (
              <tr key={inc.id} className="hover:bg-[#1a2030] transition-colors">
                <td className="p-3 font-bold text-blue-400">{inc.incident_number}</td>
                <td className="p-3 text-slate-200">{inc.title}</td>
                <td className="p-3 text-slate-400">{inc.camera_id}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    inc.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'
                  }`}>
                    {inc.severity}
                  </span>
                </td>
                <td className="p-3 font-bold text-red-400">{inc.risk_score}/100</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    inc.status === 'NEW' ? 'bg-red-500/20 text-red-400' :
                    inc.status === 'RESOLVED' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
                  }`}>
                    {inc.status}
                  </span>
                </td>
                <td className="p-3 text-slate-400">{new Date(inc.created_at).toLocaleString()}</td>
                <td className="p-3">
                  <Link
                    to={`/incidents/${inc.id}`}
                    className="px-2.5 py-1 bg-blue-600/20 text-blue-300 border border-blue-500/30 rounded text-[11px] font-semibold hover:bg-blue-600/30 transition-colors flex items-center gap-1 w-fit"
                  >
                    INVESTIGATE <ArrowUpRight className="w-3 h-3" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
