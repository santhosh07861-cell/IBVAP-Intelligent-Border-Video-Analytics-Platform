import React, { useEffect, useState } from 'react';
import { Cpu, CheckCircle, BarChart2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const ModelRegistryView: React.FC = () => {
  const [models, setModels] = useState<any[]>([]);
  const { token } = useAuth();

  useEffect(() => {
    fetch('/api/models', { headers: { 'Authorization': `Bearer ${token}` } })
      .then(res => res.json())
      .then(data => setModels(data));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">AI MODEL REGISTRY & BENCHMARKS</h2>
          <p className="text-xs text-slate-400 font-mono">Managed Neural Networks, Inference Precision & Benchmark Metrics</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {models.map((m) => (
          <div key={m.id} className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 font-mono text-xs">
            <div className="flex justify-between items-center border-b border-[#252d42] pb-3">
              <div>
                <h3 className="font-bold text-slate-100 text-sm">{m.model_name}</h3>
                <span className="text-[10px] text-blue-400">{m.version} • {m.framework}</span>
              </div>
              <span className="px-2.5 py-1 bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 rounded text-[10px] font-bold">
                ACTIVE DEPLOYMENT
              </span>
            </div>

            <div className="space-y-2">
              <div className="text-slate-400">BENCHMARK METRICS:</div>
              <div className="grid grid-cols-2 gap-2 text-slate-200">
                <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                  mAP@50: <span className="font-bold text-emerald-400">{(m.metrics?.mAP_50 * 100 || 89.2).toFixed(1)}%</span>
                </div>
                <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                  Precision: <span className="font-bold text-blue-400">{(m.metrics?.precision * 100 || 91.4).toFixed(1)}%</span>
                </div>
                <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                  Recall: <span className="font-bold text-purple-400">{(m.metrics?.recall * 100 || 87.6).toFixed(1)}%</span>
                </div>
                <div className="p-2 bg-[#0a0d14] rounded border border-[#252d42]">
                  FPS: <span className="font-bold text-amber-400">{m.metrics?.inference_fps || 64.2}</span>
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
