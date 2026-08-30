import React, { useEffect, useState, useCallback } from 'react';
import { BarChart3, TrendingUp, PieChart as PieIcon, Activity, AlertTriangle, ShieldCheck } from 'lucide-react';
import { ResponsiveContainer, AreaChart, Area, XAxis, YAxis, Tooltip, PieChart, Pie, Cell } from 'recharts';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';

export const Analytics: React.FC = () => {
  const [charts, setCharts] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const { token } = useAuth();
  const { isConnected, lastMessage } = useWebSocket();

  const fetchCharts = useCallback(async () => {
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/analytics/charts', { headers });
      if (res.ok) {
        const data = await res.json();
        setCharts(data);
      }
    } catch (err) {
      console.error('Failed to fetch analytics chart data:', err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchCharts();
    const interval = setInterval(fetchCharts, 5000);
    return () => clearInterval(interval);
  }, [fetchCharts]);

  // Real-time WebSocket triggers
  useEffect(() => {
    if (lastMessage) {
      if (
        lastMessage.type === 'ALERT_NEW' ||
        lastMessage.type === 'EVIDENCE_NEW' ||
        lastMessage.type === 'DETECTIONS_UPDATE' ||
        lastMessage.type === 'KPI_UPDATE'
      ) {
        fetchCharts();
      }
    }
  }, [lastMessage, fetchCharts]);

  const totalEvents = charts?.total_events_24h ?? (charts?.event_trends?.reduce((acc: number, cur: any) => acc + (cur.events || 0), 0) ?? 0);
  const totalAlerts = charts?.total_alerts ?? (charts?.severity_distribution?.reduce((acc: number, cur: any) => acc + (cur.value || 0), 0) ?? 0);
  const filteredSeverityData = (charts?.severity_distribution || []).filter((s: any) => s.value > 0);

  return (
    <div className="p-6 space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase font-mono flex items-center gap-2">
            <BarChart3 className="w-5 h-5 text-blue-400" /> BORDER SURVEILLANCE ANALYTICS
          </h2>
          <p className="text-xs text-slate-400 font-mono mt-0.5">
            Real Database Intrusion Trends, Live Event Correlations & Alert Distributions
          </p>
        </div>
        <div className="flex items-center gap-2 font-mono text-xs">
          <span className="flex items-center gap-1.5 px-3 py-1 bg-[#0a0d14] rounded-lg border border-[#252d42] text-slate-300">
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
            {isConnected ? 'LIVE WEBSOCKET STREAM' : 'OFFLINE'}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* 24-Hour Intrusion Event Frequency Chart */}
        <div className="lg:col-span-2 bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 font-mono shadow-sm">
          <div className="flex justify-between items-center border-b border-[#252d42] pb-3">
            <h3 className="text-xs font-bold text-slate-200 uppercase flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-400" />
              24-HOUR INTRUSION EVENT FREQUENCY
            </h3>
            <span className="text-[11px] text-slate-400">
              Total 24h Events: <strong className="text-blue-400 font-bold">{totalEvents}</strong>
            </span>
          </div>

          {totalEvents === 0 ? (
            <div className="h-64 flex flex-col items-center justify-center text-slate-500 font-mono space-y-2 bg-[#0a0d14]/40 rounded-xl border border-[#252d42]/60">
              <ShieldCheck className="w-8 h-8 text-emerald-500/60" />
              <p className="text-slate-300 font-bold text-xs">No events recorded in the last 24 hours</p>
              <p className="text-[11px] text-slate-500">Zero perimeter intrusion triggers detected during this period</p>
            </div>
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={charts?.event_trends || []}>
                  <defs>
                    <linearGradient id="colorEvents" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <XAxis dataKey="time" stroke="#64748b" fontSize={11} fontFamily="monospace" />
                  <YAxis stroke="#64748b" fontSize={11} fontFamily="monospace" allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#0a0d14',
                      borderColor: '#252d42',
                      color: '#f8fafc',
                      fontSize: '12px',
                      fontFamily: 'monospace'
                    }}
                  />
                  <Area
                    type="monotone"
                    dataKey="events"
                    name="Events"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    fillOpacity={1}
                    fill="url(#colorEvents)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>

        {/* Alert Severity Distribution Chart */}
        <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 flex flex-col justify-between font-mono shadow-sm">
          <div className="flex justify-between items-center border-b border-[#252d42] pb-3">
            <h3 className="text-xs font-bold text-slate-200 uppercase flex items-center gap-2">
              <PieIcon className="w-4 h-4 text-amber-400" />
              ALERT SEVERITY DISTRIBUTION
            </h3>
            <span className="text-[11px] text-slate-400">
              Total Alerts: <strong className="text-amber-400 font-bold">{totalAlerts}</strong>
            </span>
          </div>

          {totalAlerts === 0 ? (
            <div className="h-52 flex flex-col items-center justify-center text-slate-500 font-mono space-y-2 bg-[#0a0d14]/40 rounded-xl border border-[#252d42]/60">
              <AlertTriangle className="w-8 h-8 text-slate-600" />
              <p className="text-slate-300 font-bold text-xs">No alert data available</p>
              <p className="text-[11px] text-slate-500">No active or historical alerts logged in system</p>
            </div>
          ) : (
            <>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={filteredSeverityData.length > 0 ? filteredSeverityData : charts?.severity_distribution || []}
                      cx="50%"
                      cy="50%"
                      innerRadius={45}
                      outerRadius={75}
                      paddingAngle={4}
                      dataKey="value"
                    >
                      {(charts?.severity_distribution || []).map((entry: any, index: number) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip
                      contentStyle={{
                        backgroundColor: '#0a0d14',
                        borderColor: '#252d42',
                        color: '#f8fafc',
                        fontSize: '12px',
                        fontFamily: 'monospace'
                      }}
                    />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px] font-mono border-t border-[#252d42] pt-3">
                {(charts?.severity_distribution || []).map((s: any) => (
                  <div key={s.name} className="flex items-center justify-between text-slate-300 bg-[#0a0d14] px-2 py-1 rounded border border-[#252d42]/40">
                    <span className="flex items-center gap-1.5 text-[10px]">
                      <span className="w-2 h-2 rounded-full" style={{ backgroundColor: s.color }} />
                      <span>{s.name}:</span>
                    </span>
                    <strong className="text-slate-100 font-bold">{s.value}</strong>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

