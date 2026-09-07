import React, { useEffect, useState, useCallback } from 'react';
import { Cpu, CheckCircle2, Clock, XCircle, Activity, Database, Gauge } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';

export const ModelRegistryView: React.FC = () => {
  const [models, setModels] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const { token } = useAuth();
  const { isConnected, lastMessage } = useWebSocket();

  const fetchModels = useCallback(async () => {
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/models', { headers });
      if (res.ok) {
        const data = await res.json();
        setModels(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error('Failed to fetch AI model registry:', err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  useEffect(() => {
    fetchModels();
    const interval = setInterval(fetchModels, 3000);
    return () => clearInterval(interval);
  }, [fetchModels]);

  // Real-time WebSocket triggers for instant UI reactivity
  useEffect(() => {
    if (lastMessage) {
      if (
        lastMessage.type === 'DETECTIONS_UPDATE' ||
        lastMessage.type === 'EVIDENCE_NEW' ||
        lastMessage.type === 'ALERT_NEW'
      ) {
        fetchModels();
      }
    }
  }, [lastMessage, fetchModels]);

  return (
    <div className="p-6 space-y-6">
      {/* Header Banner */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase font-mono flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-400" /> AI MODEL REGISTRY & BENCHMARKS
          </h2>
          <p className="text-xs text-slate-400 font-mono mt-0.5">
            Real Neural Network Deployments, Live Inference Metrics & Verified Evaluations
          </p>
        </div>
        <div className="flex items-center gap-2 font-mono text-xs">
          <span className="flex items-center gap-1.5 px-3 py-1 bg-[#0a0d14] rounded-lg border border-[#252d42] text-slate-300">
            <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-red-500'}`} />
            {isConnected ? 'LIVE ENGINE TELEMETRY' : 'TELEMETRY OFFLINE'}
          </span>
        </div>
      </div>

      {/* Models Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {models.map((m) => {
          const fps = m.metrics?.inference_fps;
          const latency = m.metrics?.latency_ms;
          const map50 = m.metrics?.mAP_50;
          const precision = m.metrics?.precision;
          const recall = m.metrics?.recall;

          const engineState: 'ACTIVE' | 'STANDBY' | 'OFFLINE' = m.engine_state || (m.is_active ? 'ACTIVE' : 'STANDBY');
          const isActive = engineState === 'ACTIVE';
          const isStandby = engineState === 'STANDBY';
          const isOffline = engineState === 'OFFLINE';

          return (
            <div
              key={m.id}
              className={`bg-[#111622] p-5 rounded-xl border space-y-4 font-mono text-xs transition-all shadow-sm ${
                isActive
                  ? 'border-emerald-500/40 shadow-emerald-500/5'
                  : isStandby
                  ? 'border-[#252d42] hover:border-blue-500/40'
                  : 'border-rose-500/40 shadow-rose-500/5'
              }`}
            >
              {/* Card Header */}
              <div className="flex justify-between items-start border-b border-[#252d42] pb-3 gap-2">
                <div>
                  <h3 className="font-bold text-slate-100 text-sm">{m.model_name}</h3>
                  <div className="text-[10px] text-blue-400 mt-0.5">
                    {m.version} • {m.framework}
                  </div>
                </div>
                <span
                  className={`px-2.5 py-1 rounded text-[10px] font-bold shrink-0 flex items-center gap-1.5 ${
                    isActive
                      ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                      : isStandby
                      ? 'bg-amber-500/15 text-amber-400 border border-amber-500/30'
                      : 'bg-rose-500/20 text-rose-400 border border-rose-500/40'
                  }`}
                >
                  {isActive && (
                    <>
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 animate-pulse" />
                      <span>AI ENGINE ACTIVE</span>
                    </>
                  )}
                  {isStandby && (
                    <>
                      <Clock className="w-3.5 h-3.5 text-amber-400" />
                      <span>AI ENGINE STANDBY</span>
                    </>
                  )}
                  {isOffline && (
                    <>
                      <XCircle className="w-3.5 h-3.5 text-rose-400" />
                      <span>AI ENGINE OFFLINE</span>
                    </>
                  )}
                </span>
              </div>

              {/* Live Inference Runtime Status */}
              <div className="space-y-1.5">
                <div className="text-slate-400 text-[11px] font-bold flex items-center justify-between">
                  <span>LIVE INFERENCE RUNTIME:</span>
                  <span
                    className={`text-[10px] font-semibold ${
                      isActive ? 'text-emerald-400' : isStandby ? 'text-amber-400/80' : 'text-rose-400'
                    }`}
                  >
                    {isActive
                      ? '● Live Stream Processing'
                      : isStandby
                      ? '○ Standby • Awaiting Stream'
                      : '✕ Service Unavailable'}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-slate-200">
                  <div className="p-2.5 bg-[#0a0d14] rounded-lg border border-[#252d42] flex items-center justify-between">
                    <span className="text-slate-400 flex items-center gap-1 text-[11px]">
                      <Gauge className={`w-3.5 h-3.5 ${isActive ? 'text-amber-400' : 'text-slate-500'}`} /> Pipeline FPS:
                    </span>
                    <span
                      className={`font-bold text-xs ${
                        isActive
                          ? 'text-amber-400'
                          : isStandby
                          ? 'text-amber-400/90'
                          : 'text-rose-400'
                      }`}
                    >
                      {isActive && fps != null
                        ? `${typeof fps === 'number' ? fps.toFixed(1) : fps} FPS`
                        : isStandby
                        ? 'AI ENGINE STANDBY'
                        : 'OFFLINE'}
                    </span>
                  </div>

                  <div className="p-2.5 bg-[#0a0d14] rounded-lg border border-[#252d42] flex items-center justify-between">
                    <span className="text-slate-400 flex items-center gap-1 text-[11px]">
                      <Activity className={`w-3.5 h-3.5 ${isActive ? 'text-blue-400' : 'text-slate-500'}`} /> Latency:
                    </span>
                    <span
                      className={`font-bold text-xs ${
                        isActive && latency != null
                          ? 'text-blue-400'
                          : 'text-slate-500'
                      }`}
                    >
                      {isActive && latency != null ? `${latency} ms` : isStandby ? 'STANDBY' : 'N/A'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Total Processed in DB (Cumulative Historical Archive) */}
              <div className="p-2.5 bg-[#0a0d14] rounded-lg border border-[#252d42] flex items-center justify-between text-slate-300">
                <span className="text-slate-400 flex items-center gap-1.5 text-[11px]">
                  <Database className="w-3.5 h-3.5 text-emerald-400" />
                  <span>Total Processed in DB (Historical Archive):</span>
                </span>
                <span className="font-bold text-emerald-400 text-sm">
                  {m.total_detections ?? 0}
                </span>
              </div>

              {/* Verified Benchmark Metrics */}
              <div className="space-y-1.5">
                <div className="text-slate-400 text-[11px] font-bold">
                  VERIFIED BENCHMARK DATASET EVALUATION:
                </div>
                <div className="grid grid-cols-3 gap-2 text-slate-200 text-[11px]">
                  <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                    <div className="text-slate-500 text-[10px]">mAP@50</div>
                    <span className="font-bold text-slate-400">
                      {map50 != null ? `${(map50 * 100).toFixed(1)}%` : 'N/A — No benchmark data'}
                    </span>
                  </div>

                  <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                    <div className="text-slate-500 text-[10px]">Precision</div>
                    <span className="font-bold text-slate-400">
                      {precision != null ? `${(precision * 100).toFixed(1)}%` : 'N/A — No benchmark data'}
                    </span>
                  </div>

                  <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                    <div className="text-slate-500 text-[10px]">Recall</div>
                    <span className="font-bold text-slate-400">
                      {recall != null ? `${(recall * 100).toFixed(1)}%` : 'N/A — No benchmark data'}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
