import React, { useEffect, useState } from 'react';
import { Shapes, Plus, ShieldAlert, Check } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const ZoneEditor: React.FC = () => {
  const [zones, setZones] = useState<any[]>([]);
  const [name, setName] = useState('RESTRICTED BORDER ZONE ALPHA');
  const [zoneType, setZoneType] = useState('RESTRICTED AREA');
  const { token } = useAuth();

  const fetchZones = async () => {
    try {
      const res = await fetch('/api/zones', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setZones(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchZones();
  }, []);

  const handleCreateZone = async () => {
    try {
      const res = await fetch('/api/zones', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          camera_id: 'CAM-01',
          name: name,
          zone_type: zoneType,
          geometry_type: 'polygon',
          coordinates: [[0.15, 0.20], [0.85, 0.20], [0.90, 0.80], [0.10, 0.80]]
        })
      });
      if (res.ok) {
        fetchZones();
      }
    } catch (e) {
      console.error(e);
    }
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">VIRTUAL FENCES & ZONES</h2>
          <p className="text-xs text-slate-400 font-mono">Interactive Polygon & Line-crossing Intrusion Rule Configuration</p>
        </div>
        <button
          onClick={handleCreateZone}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 transition-colors"
        >
          <Plus className="w-4 h-4" /> SAVE NEW ZONE
        </button>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Interactive Zone Visualizer Canvas */}
        <div className="lg:col-span-2 bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-3">
          <h3 className="text-xs font-bold font-mono text-slate-200 uppercase">VISUAL ZONE CANVAS OVERLAY (CAM-01)</h3>
          <div className="relative aspect-video bg-slate-950 rounded-lg overflow-hidden border border-[#252d42]">
            <video
              src="/static/demo_videos/border_patrol.mp4"
              autoPlay
              loop
              muted
              playsInline
              className="w-full h-full object-cover opacity-75"
              onError={(e) => { e.currentTarget.style.display = 'none'; }}
            />
            {/* Draw Polygon Canvas overlay */}
            <svg className="absolute inset-0 w-full h-full">
              <polygon
                points="100,80 900,80 950,480 50,480"
                fill="rgba(239, 68, 68, 0.2)"
                stroke="#ef4444"
                strokeWidth="3"
                strokeDasharray="6 4"
              />
              <circle cx="100" cy="80" r="6" fill="#ef4444" />
              <circle cx="900" cy="80" r="6" fill="#ef4444" />
              <circle cx="950" cy="480" r="6" fill="#ef4444" />
              <circle cx="50" cy="480" r="6" fill="#ef4444" />
            </svg>
          </div>
        </div>

        {/* Existing Zones List */}
        <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4">
          <h3 className="text-xs font-bold font-mono text-slate-200 uppercase">CONFIGURED SURVEILLANCE ZONES</h3>
          <div className="space-y-3">
            {zones.map((z) => (
              <div key={z.id} className="p-3 bg-[#0a0d14] rounded-lg border border-[#252d42] text-xs space-y-1">
                <div className="flex justify-between items-center font-bold text-slate-200">
                  <span>{z.name}</span>
                  <span className="text-[10px] text-blue-400 font-mono bg-blue-500/10 px-1.5 py-0.5 rounded border border-blue-500/30">
                    {z.zone_type}
                  </span>
                </div>
                <div className="text-[10px] text-slate-400 font-mono">
                  Points: {z.coordinates.length} • Rules: {z.rules?.length || 1} Active Rule
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
