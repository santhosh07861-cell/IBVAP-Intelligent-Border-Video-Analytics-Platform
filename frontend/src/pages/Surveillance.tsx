import React, { useEffect, useState } from 'react';
import { LayoutGrid, Grid2X2, Grid3X3, Camera } from 'lucide-react';
import { useWebSocket } from '../context/WebSocketContext';
import { useAuth } from '../context/AuthContext';
import { LiveVideoCanvas } from '../components/LiveVideoCanvas';

export const Surveillance: React.FC = () => {
  const [gridSize, setGridSize] = useState<number>(4);
  const [cameras, setCameras] = useState<any[]>([]);
  const { lastMessage } = useWebSocket();
  const { token } = useAuth();

  const loadCameras = () => {
    const headers: any = {};
    const authToken = token || localStorage.getItem('ibvap_token');
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

    fetch('/api/cameras', { headers })
      .then(res => res.json())
      .then(data => {
        if (Array.isArray(data)) {
          setCameras(data);
        }
      })
      .catch(err => console.error(err));
  };

  useEffect(() => {
    loadCameras();
    const interval = setInterval(loadCameras, 3000);
    return () => clearInterval(interval);
  }, [token]);

  const displayCams = cameras.slice(0, gridSize);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">LIVE BORDER SURVEILLANCE GRID</h2>
          <p className="text-xs text-slate-400 font-mono">REAL-TIME MULTI-CAMERA STREAM INGESTION & TACTICAL OVERLAY</p>
        </div>

        {/* Grid Switcher Buttons */}
        <div className="flex items-center gap-2 bg-[#0a0d14] p-1 rounded-lg border border-[#252d42]">
          <button
            onClick={() => setGridSize(1)}
            className={`px-3 py-1.5 rounded text-xs font-mono font-semibold flex items-center gap-1.5 transition-colors ${
              gridSize === 1 ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <LayoutGrid className="w-3.5 h-3.5" /> 1 CAMERA
          </button>
          <button
            onClick={() => setGridSize(4)}
            className={`px-3 py-1.5 rounded text-xs font-mono font-semibold flex items-center gap-1.5 transition-colors ${
              gridSize === 4 ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Grid2X2 className="w-3.5 h-3.5" /> 2x2 GRID
          </button>
          <button
            onClick={() => setGridSize(9)}
            className={`px-3 py-1.5 rounded text-xs font-mono font-semibold flex items-center gap-1.5 transition-colors ${
              gridSize === 9 ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            <Grid3X3 className="w-3.5 h-3.5" /> 3x3 GRID
          </button>
        </div>
      </div>

      {/* Dynamic Camera Cards Grid */}
      {displayCams.length === 0 ? (
        <div className="bg-[#111622] p-12 text-center rounded-xl border border-[#252d42] space-y-3">
          <Camera className="w-10 h-10 text-slate-600 mx-auto" />
          <h3 className="text-slate-200 font-bold font-mono text-sm uppercase">NO ACTIVE SURVEILLANCE CAMERAS</h3>
          <p className="text-slate-400 font-mono text-xs max-w-md mx-auto">
            No cameras are currently connected. Add a new camera in Camera Management or trigger a video stream in Demo Control to display live surveillance.
          </p>
        </div>
      ) : (
        <div className={`grid gap-4 ${
          gridSize === 1 ? 'grid-cols-1' : gridSize === 4 ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1 md:grid-cols-3'
        }`}>
          {displayCams.map((cam, idx) => (
            <div key={cam.id || idx} className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden flex flex-col justify-between">
              <LiveVideoCanvas
                cameraId={cam.camera_id}
                cameraName={cam.name}
                detections={lastMessage?.camera_id === cam.camera_id ? lastMessage?.detections : []}
                fps={lastMessage?.camera_id === cam.camera_id ? (lastMessage?.fps || 0.0) : 0.0}
                latencyMs={lastMessage?.camera_id === cam.camera_id ? (lastMessage?.latency_ms || 0.0) : 0.0}
                inferenceMode={lastMessage?.camera_id === cam.camera_id ? (lastMessage?.inference_mode || 'OFFLINE') : 'OFFLINE'}
              />
            </div>
          ))}
        </div>
      )}
    </div>
  );
};
