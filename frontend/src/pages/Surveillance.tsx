import React, { useState, useEffect } from 'react';
import { LayoutGrid, Grid2X2, Grid3X3, Camera, Filter } from 'lucide-react';
import { useCameraTelemetry } from '../context/WebSocketContext';
import { useCameras } from '../context/CameraContext';
import { LiveVideoCanvas } from '../components/LiveVideoCanvas';
import { browserCameraStreamManager } from '../utils/browserCameraStreamManager';

interface CameraGridCardProps {
  cam: any;
  onRotate: (newRotation: number) => Promise<void>;
}

const CameraGridCard: React.FC<CameraGridCardProps> = React.memo(({ cam, onRotate }) => {
  const telem = useCameraTelemetry(cam.camera_id || cam.id);
  const isCamOnline = (telem?.fps || 0) > 0 || (cam.status === 'ONLINE' && (cam.fps || 0) > 0);
  const camFps = typeof telem?.fps === 'number' ? telem.fps : (cam.fps || 0.0);
  const camLatency = telem?.latency_ms || 0.0;
  const camDets = telem?.detections || [];
  const camFaces = telem?.faces || [];
  const camInferenceMode = telem?.inference_mode || (isCamOnline ? 'REAL AI | INFERENCE RUNNING' : 'OFFLINE');
  const camStatus = telem?.status || cam.status;

  return (
    <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden flex flex-col justify-between">
      <LiveVideoCanvas
        cameraId={cam.camera_id}
        cameraName={cam.name}
        status={camStatus}
        detections={camDets}
        faces={camFaces}
        fps={camFps}
        latencyMs={camLatency}
        inferenceMode={camInferenceMode}
        cameraRole={cam.role as 'primary' | 'secondary'}
        protocol={cam.protocol}
        rotation={cam.rotation || 0}
        onRotate={onRotate}
      />
    </div>
  );
});

export const Surveillance: React.FC = () => {
  const [gridSize, setGridSize] = useState<number>(4);
  const [roleFilter, setRoleFilter] = useState<'all' | 'secondary' | 'primary'>('all');

  const { cameras, secondaryCameras, primaryCamera, setCameraRotation } = useCameras();

  const sortedCameras = React.useMemo(() => {
    return [...cameras].sort((a, b) => {
      // 1. Primary camera always comes first (Tile 1)
      if (a.role === 'primary' && b.role !== 'primary') return -1;
      if (b.role === 'primary' && a.role !== 'primary') return 1;

      // 2. Active/streaming cameras come before stopped/offline cameras
      const aActive = a.status === 'ONLINE' || a.status === 'CONNECTING' || (a.fps || 0) > 0;
      const bActive = b.status === 'ONLINE' || b.status === 'CONNECTING' || (b.fps || 0) > 0;
      if (aActive && !bActive) return -1;
      if (bActive && !aActive) return 1;

      // 3. Keep stable ordering by camera_id
      return (a.camera_id || '').localeCompare(b.camera_id || '');
    });
  }, [cameras]);

  const sortedSecondary = React.useMemo(() => {
    return [...secondaryCameras].sort((a, b) => {
      const aActive = a.status === 'ONLINE' || a.status === 'CONNECTING' || (a.fps || 0) > 0;
      const bActive = b.status === 'ONLINE' || b.status === 'CONNECTING' || (b.fps || 0) > 0;
      if (aActive && !bActive) return -1;
      if (bActive && !aActive) return 1;
      return (a.camera_id || '').localeCompare(b.camera_id || '');
    });
  }, [secondaryCameras]);

  const filteredCameras = roleFilter === 'secondary'
    ? sortedSecondary
    : roleFilter === 'primary'
    ? (primaryCamera ? [primaryCamera] : [])
    : sortedCameras;

  const displayCams = filteredCameras.slice(0, gridSize);

  useEffect(() => {
    // If any displayed camera is an active browser webcam, ensure its independent stream session is running
    displayCams.forEach(cam => {
      const isBrowserCam = cam.protocol === 'WEBCAM' || cam.protocol === 'BROWSER';
      const isActiveStatus = cam.status !== 'STOPPED' && cam.status !== 'OFFLINE';
      if (isBrowserCam && isActiveStatus) {
        if (!browserCameraStreamManager.isStreaming(cam.camera_id)) {
          browserCameraStreamManager.startCameraStream(cam.camera_id, cam.stream_url || '').catch(() => {});
        }
      }
    });
  }, [displayCams]);

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase font-mono">LIVE MULTI-CAMERA SURVEILLANCE GRID</h2>
          <p className="text-xs text-slate-400 font-mono">Real-time tactical video surveillance and automated AI threat detection</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Primary / Secondary Filter Tabs */}
          <div className="flex items-center gap-1 bg-[#0a0d14] p-1 rounded-lg border border-[#252d42]">
            <button
              onClick={() => setRoleFilter('all')}
              className={`px-3 py-1 rounded text-xs font-mono font-semibold transition-colors ${
                roleFilter === 'all' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              ALL ({cameras.length})
            </button>
            <button
              onClick={() => setRoleFilter('secondary')}
              className={`px-3 py-1 rounded text-xs font-mono font-semibold transition-colors ${
                roleFilter === 'secondary' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              SECONDARY ({secondaryCameras.length})
            </button>
            <button
              onClick={() => setRoleFilter('primary')}
              className={`px-3 py-1 rounded text-xs font-mono font-semibold transition-colors ${
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
          {displayCams.map((cam) => (
            <CameraGridCard
              key={cam.id || cam.camera_id}
              cam={cam}
              onRotate={async (r) => {
                await setCameraRotation(cam.camera_id, r);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
};
