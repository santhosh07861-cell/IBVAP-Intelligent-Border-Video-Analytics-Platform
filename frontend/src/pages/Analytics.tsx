import React, { useEffect, useState } from 'react';
import { BarChart3, TrendingUp, PieChart as PieIcon } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, PieChart, Pie, Cell } from 'recharts';
import { useAuth } from '../context/AuthContext';

export const Analytics: React.FC = () => {
  const [charts, setCharts] = useState<any>(null);
  const { token } = useAuth();

  useEffect(() => {
    fetch('/api/analytics/charts', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => res.json())
      .then(data => setCharts(data))
      .catch(err => console.error(err));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">BORDER SURVEILLANCE ANALYTICS</h2>
          <p className="text-xs text-slate-400 font-mono">Historical Intrusion Trends, Event Correlations & AI Performance Metrics</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Hourly Event Trends Chart */}
        <div className="lg:col-span-2 bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4">
          <h3 className="text-xs font-bold font-mono text-slate-200 uppercase flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-blue-400" />
            24-HOUR INTRUSION EVENT FREQUENCY
          </h3>

          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={charts?.event_trends || []}>
                <defs>
                  <linearGradient id="colorEvents" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4}/>
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <XAxis dataKey="time" stroke="#64748b" fontSize={11} fontFamily="monospace" />
                <YAxis stroke="#64748b" fontSize={11} fontFamily="monospace" />
                <Tooltip
                  contentStyle={{ backgroundColor: '#0a0d14', borderColor: '#252d42', color: '#f8fafc', fontSize: '12px' }}
                />
                <Area type="monotone" dataKey="events" stroke="#3b82f6" strokeWidth={2} fillOpacity={1} fill="url(#colorEvents)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Severity Distribution Pie Chart */}
        <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 flex flex-col justify-between">
          <h3 className="text-xs font-bold font-mono text-slate-200 uppercase flex items-center gap-2">
            <PieIcon className="w-4 h-4 text-amber-400" />
            ALERT SEVERITY DISTRIBUTION
          </h3>

          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={charts?.severity_distribution || []}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {(charts?.severity_distribution || []).map((entry: any, index: number) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ backgroundColor: '#0a0d14', borderColor: '#252d42', color: '#f8fafc', fontSize: '12px' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>

          <div className="grid grid-cols-2 gap-2 text-[11px] font-mono">
            {(charts?.severity_distribution || []).map((s: any) => (
              <div key={s.name} className="flex items-center gap-1.5 text-slate-300">
                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: s.color }} />
                <span>{s.name}: {s.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
