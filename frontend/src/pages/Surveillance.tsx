import React, { useState } from 'react';
import { LayoutGrid, Grid2X2, Grid3X3, Camera, Filter } from 'lucide-react';
import { useWebSocket } from '../context/WebSocketContext';
import { useCameras } from '../context/CameraContext';
import { LiveVideoCanvas } from '../components/LiveVideoCanvas';

export const Surveillance: React.FC = () => {
  const [gridSize, setGridSize] = useState<number>(4);
  const [roleFilter, setRoleFilter] = useState<'all' | 'secondary' | 'primary'>('all');

  const { cameras, secondaryCameras, primaryCamera } = useCameras();
  const { getCameraTelemetry } = useWebSocket();

  const filteredCameras = roleFilter === 'secondary'
    ? secondaryCameras
    : roleFilter === 'primary'
    ? (primaryCamera ? [primaryCamera] : [])
    : cameras;

  const displayCams = filteredCameras.slice(0, gridSize);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase font-mono">LIVE MULTI-CAMERA SURVEILLANCE GRID</h2>
          <p className="text-xs text-slate-400 font-mono">REAL-TIME INDEPENDENT CAMERA INGESTION & AI DETECTIONS</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Role Filter Selector */}
          <div className="flex items-center gap-1 bg-[#0a0d14] p-1 rounded-lg border border-[#252d42] text-xs font-mono">
            <span className="px-2 text-slate-400 flex items-center gap-1 text-[11px]">
              <Filter className="w-3 h-3" /> ROLE:
            </span>
            <button
              onClick={() => setRoleFilter('all')}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                roleFilter === 'all' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              ALL ({cameras.length})
            </button>
            <button
              onClick={() => setRoleFilter('secondary')}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                roleFilter === 'secondary' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              SECONDARY ({secondaryCameras.length})
            </button>
            <button
              onClick={() => setRoleFilter('primary')}
              className={`px-2.5 py-1 rounded text-[11px] font-semibold transition-colors ${
                roleFilter === 'primary' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              PRIMARY ({primaryCamera ? 1 : 0})
            </button>
          </div>

          {/* Grid Switcher Buttons */}
          <div className="flex items-center gap-1 bg-[#0a0d14] p-1 rounded-lg border border-[#252d42]">
            <button
              onClick={() => setGridSize(1)}
              className={`px-2.5 py-1 rounded text-xs font-mono font-semibold flex items-center gap-1 transition-colors ${
                gridSize === 1 ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <LayoutGrid className="w-3.5 h-3.5" /> 1 CAM
            </button>
            <button
              onClick={() => setGridSize(4)}
              className={`px-2.5 py-1 rounded text-xs font-mono font-semibold flex items-center gap-1 transition-colors ${
                gridSize === 4 ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Grid2X2 className="w-3.5 h-3.5" /> 2x2 GRID
            </button>
            <button
              onClick={() => setGridSize(9)}
              className={`px-2.5 py-1 rounded text-xs font-mono font-semibold flex items-center gap-1 transition-colors ${
                gridSize === 9 ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Grid3X3 className="w-3.5 h-3.5" /> 3x3 GRID
            </button>
          </div>
        </div>
      </div>

      {/* Dynamic Camera Cards Grid */}
      {displayCams.length === 0 ? (
        <div className="bg-[#111622] p-12 text-center rounded-xl border border-[#252d42] space-y-3">
          <Camera className="w-10 h-10 text-slate-600 mx-auto" />
          <h3 className="text-slate-200 font-bold font-mono text-sm uppercase">NO MATCHING SURVEILLANCE CAMERAS</h3>
          <p className="text-slate-400 font-mono text-xs max-w-md mx-auto">
            No cameras match the selected role filter. Add or configure cameras in Camera Management to view live multi-camera feeds.
          </p>
        </div>
      ) : (
        <div className={`grid gap-4 ${
          gridSize === 1 ? 'grid-cols-1' : gridSize === 4 ? 'grid-cols-1 md:grid-cols-2' : 'grid-cols-1 md:grid-cols-3'
        }`}>
          {displayCams.map((cam) => {
            const telem = getCameraTelemetry(cam.camera_id);
            const isCamOnline = cam.status === 'ONLINE' || (telem?.fps || 0) > 0;
            const camFps = isCamOnline ? (telem?.fps || cam.fps || 25.0) : 0.0;
            const camLatency = isCamOnline ? (telem?.latency_ms || 0.0) : 0.0;
            const camDets = isCamOnline ? (telem?.detections || []) : [];
            const camFaces = isCamOnline ? (telem?.faces || []) : [];
            const camInferenceMode = isCamOnline ? (telem?.inference_mode || 'REAL AI | INFERENCE RUNNING') : 'OFFLINE';

            return (
              <div key={cam.id || cam.camera_id} className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden flex flex-col justify-between">
                <LiveVideoCanvas
                  cameraId={cam.camera_id}
                  cameraName={cam.name}
                  detections={camDets}
                  faces={camFaces}
                  fps={camFps}
                  latencyMs={camLatency}
                  inferenceMode={camInferenceMode}
                  cameraRole={cam.role as 'primary' | 'secondary'}
                />
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
