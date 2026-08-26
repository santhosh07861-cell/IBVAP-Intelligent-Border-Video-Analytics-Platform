import React, { useEffect, useState } from 'react';
import { UserCheck, Shield } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const FaceView: React.FC = () => {
  const [faces, setFaces] = useState<any[]>([]);
  const { token } = useAuth();

  useEffect(() => {
    fetch('/api/faces', {
      headers: { 'Authorization': `Bearer ${token}` }
    })
      .then(res => res.json())
      .then(data => setFaces(data))
      .catch(err => console.error(err));
  }, []);

  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">FACE DETECTION LOG</h2>
          <p className="text-xs text-slate-400 font-mono">Face Bounding Box Detection Adapter (Independent of Identity Recognition)</p>
        </div>
      </div>

      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden p-6 text-xs font-mono text-slate-400">
        {faces.length === 0 ? (
          <div className="text-center py-10 space-y-2">
            <UserCheck className="w-8 h-8 text-blue-400 mx-auto" />
            <div>NO UNRECOGNIZED FACES DETECTED IN CURRENT SURVEILLANCE BUFFER</div>
            <div className="text-[11px] text-slate-500">Face detection pipeline active & monitoring.</div>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {faces.map((f) => (
              <div key={f.id} className="bg-[#0a0d14] p-3 rounded-lg border border-[#252d42] space-y-1">
                <div className="text-blue-400 font-bold">Face Detection Confidence: {(f.confidence * 100).toFixed(0)}%</div>
                <div className="text-slate-400 font-mono">Camera: {f.camera_id}</div>
                <div className="text-slate-500 font-mono text-[10px]">{new Date(f.timestamp).toLocaleString()}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
