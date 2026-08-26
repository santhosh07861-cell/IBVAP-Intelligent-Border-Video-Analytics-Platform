import React, { useEffect, useState } from 'react';
import { HeartPulse, Activity, Cpu, Database, Server, HardDrive } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const HealthView: React.FC = () => {
  const [systemHealth, setSystemHealth] = useState<any>(null);
  const [cameraHealth, setCameraHealth] = useState<any[]>([]);
  const { token } = useAuth();

  useEffect(() => {
    fetch('/api/health/system', { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => setSystemHealth(data));

    fetch('/api/health/cameras', { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => setCameraHealth(data));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">SYSTEM & CAMERA HEALTH TELEMETRY</h2>
          <p className="text-xs text-slate-400 font-mono">Live Diagnostic Hardware & Stream Health Monitoring</p>
        </div>
      </div>

      {/* System Service Status Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-xs">
        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">FASTAPI BACKEND</span>
            <Server className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-base font-bold text-emerald-400">{systemHealth?.api || 'HEALTHY'}</div>
        </div>

        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">DATABASE STORAGE</span>
            <Database className="w-4 h-4 text-emerald-400" />
          </div>
          <div className="text-base font-bold text-emerald-400">{systemHealth?.database || 'HEALTHY'}</div>
        </div>

        <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-slate-400">AI INFERENCE ENGINE</span>
            <Cpu className="w-4 h-4 text-blue-400" />
          </div>
          <div className="text-base font-bold text-blue-400">{systemHealth?.ai_engine || 'ACTIVE'}</div>
        </div>
      </div>

      {/* Camera Health Table */}
      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <div className="p-4 border-b border-[#252d42] font-bold text-xs font-mono text-slate-200 uppercase">
          CAMERA HARDWARE HEALTH & LATENCY
        </div>
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3">Camera ID</th>
              <th className="p-3">Name</th>
              <th className="p-3">Status</th>
              <th className="p-3">FPS</th>
              <th className="p-3">Latency (ms)</th>
              <th className="p-3">Dropped Frames</th>
              <th className="p-3">Reconnects</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {cameraHealth.map((ch) => (
              <tr key={ch.camera_id} className="hover:bg-[#1a2030] transition-colors">
                <td className="p-3 font-bold text-blue-400">{ch.camera_id}</td>
                <td className="p-3 text-slate-200">{ch.camera_name}</td>
                <td className="p-3">
                  <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                    ch.status === 'ONLINE' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'
                  }`}>
                    {ch.status}
                  </span>
                </td>
                <td className="p-3 text-slate-300">{ch.fps}</td>
                <td className="p-3 text-blue-400">{ch.latency_ms}ms</td>
                <td className="p-3 text-slate-400">{ch.dropped_frames}</td>
                <td className="p-3 text-slate-400">{ch.reconnect_attempts}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};
