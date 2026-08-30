import React, { useEffect, useState } from 'react';
import { ShieldCheck } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { formatISTDateTime } from '../utils/timeFormat';

export const AuditView: React.FC = () => {
  const [logs, setLogs] = useState<any[]>([]);
  const { token } = useAuth();

  useEffect(() => {
    fetch('/api/audit', { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => setLogs(data));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">SECURITY AUDIT LOGS</h2>
          <p className="text-xs text-slate-400 font-mono">Immutable Security Trail & System Activity Records</p>
        </div>
      </div>

      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3">Timestamp</th>
              <th className="p-3">User</th>
              <th className="p-3">Action</th>
              <th className="p-3">Resource</th>
              <th className="p-3">IP Address</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {logs.map((l) => (
              <tr key={l.id} className="hover:bg-[#1a2030] transition-colors">
                <td className="p-3 text-slate-300 font-mono">{formatISTDateTime(l.timestamp)}</td>
                <td className="p-3 font-bold text-blue-400">{l.username}</td>
                <td className="p-3 text-emerald-400 font-bold">{l.action}</td>
                <td className="p-3 text-slate-300">{l.resource}</td>
                <td className="p-3 text-slate-500">{l.ip_address}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
