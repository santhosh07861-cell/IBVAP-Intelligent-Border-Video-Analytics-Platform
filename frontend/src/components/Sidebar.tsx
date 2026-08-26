import React from 'react';
import { NavLink } from 'react-router-dom';
import { useWebSocket } from '../context/WebSocketContext';
import {
  LayoutDashboard, Video, Camera, Shapes, Bell, AlertOctagon,
  FileText, UserCheck, BarChart3, Activity, HeartPulse, Cpu,
  ShieldCheck, PlaySquare, Scan
} from 'lucide-react';

const navItems = [
  { path: '/dashboard', label: 'Command Center', icon: LayoutDashboard },
  { path: '/surveillance', label: 'Live Surveillance', icon: Video },
  { path: '/cameras', label: 'Camera Management', icon: Camera },
  { path: '/zones', label: 'Virtual Fences', icon: Shapes },
  { path: '/alerts', label: 'Live Alerts', icon: Bell },
  { path: '/incidents', label: 'Incidents', icon: AlertOctagon },
  { path: '/evidence', label: 'AI Detection History', icon: Scan },
  { path: '/anpr', label: 'ANPR License Plates', icon: FileText },
  { path: '/faces', label: 'Face Detections', icon: UserCheck },
  { path: '/analytics', label: 'Border Analytics', icon: BarChart3 },
  { path: '/camera-health', label: 'Camera Health', icon: Activity },
  { path: '/system-health', label: 'System Health', icon: HeartPulse },
  { path: '/models', label: 'AI Model Registry', icon: Cpu },
  { path: '/audit', label: 'Audit Logs', icon: ShieldCheck },
  { path: '/demo', label: 'SIH Demo Center', icon: PlaySquare, highlight: true }
];

export const Sidebar: React.FC = () => {
  const [kpis, setKpis] = React.useState<any>(null);
  const { isConnected, lastMessage } = useWebSocket();

  React.useEffect(() => {
    const fetchKpis = () => {
      fetch('/api/analytics/kpis')
        .then(res => res.json())
        .then(data => setKpis(data))
        .catch(() => setKpis(null));
    };
    fetchKpis();
    const interval = setInterval(fetchKpis, 5000);
    return () => clearInterval(interval);
  }, []);

  const getSystemStatus = () => {
    if (!isConnected) return { text: 'DISCONNECTED', color: 'text-red-400' };
    return { text: 'ONLINE', color: 'text-emerald-400' };
  };

  const sysStatus = getSystemStatus();

  return (
    <aside className="w-64 bg-[#111622] border-r border-[#252d42] flex flex-col justify-between shrink-0 min-h-[calc(100vh-4rem)]">
      <div className="py-4 px-2 space-y-1">
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                  isActive
                    ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30 font-semibold'
                    : item.highlight
                    ? 'bg-red-950/40 text-red-300 border border-red-800/40 hover:bg-red-900/40'
                    : 'text-slate-400 hover:bg-[#1a2030] hover:text-slate-200'
                }`
              }
            >
              <Icon className={`w-4 h-4 ${item.highlight ? 'text-red-400 animate-pulse' : ''}`} />
              <span>{item.label}</span>
            </NavLink>
          );
        })}
      </div>

      {/* Footer system status */}
      <div className="p-3 m-2 rounded-lg bg-[#0a0d14] border border-[#252d42] text-[11px] text-slate-400 font-mono">
        <div className="flex justify-between items-center mb-1">
          <span>BSF SYSTEM STATUS</span>
          <span className={`${sysStatus.color} font-bold`}>{sysStatus.text}</span>
        </div>
        <div className="text-[10px] text-slate-500">v1.0.0 SIH 2026 Build</div>
      </div>
    </aside>
  );
};
