import React, { useEffect, useRef, useState } from 'react';
import { Eye, Moon, Bug } from 'lucide-react';

interface LiveVideoCanvasProps {
  cameraId?: string;
  cameraName?: string;
  detections?: Array<{
    track_id: number;
    class_name: string;
    confidence: number;
    bbox: number[];
    dwell_time_sec: number;
    is_fallback: boolean;
  }>;
  faces?: Array<{
    track_id: number;
    bbox: number[];
    landmarks?: number[][];
    confidence: number;
    quality_score?: number;
    recognition_status: string;
    identity_id?: string | null;
    identity_name?: string | null;
    recognition_confidence?: number;
  }>;
  fps?: number;
  latencyMs?: number;
  inferenceMode?: string;
  cameraRole?: 'primary' | 'secondary';
}

export const LiveVideoCanvas: React.FC<LiveVideoCanvasProps> = ({
  cameraId,
  cameraName,
  detections = [],
  faces = [],
  fps = 0.0,
  latencyMs = 0.0,
  inferenceMode,
  cameraRole
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [thermalMode, setThermalMode] = useState<boolean>(false);
  const [nightVision, setNightVision] = useState<boolean>(false);
  const [showDiagnostics, setShowDiagnostics] = useState<boolean>(false);
  const [imageError, setImageError] = useState<boolean>(false);

  const isStreaming = Boolean(cameraId && !imageError);

  useEffect(() => {
    setImageError(false);
  }, [cameraId]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animFrameId: number;
    let tick = 0;

    const render = () => {
      tick++;
      const w = canvas.width;
      const h = canvas.height;

      // 1. Render Background Surveillance Terrain when thermal or night mode active
      if (isStreaming && thermalMode) {
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, '#0a0314');
        grad.addColorStop(0.5, '#19082b');
        grad.addColorStop(1, '#05020a');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);

        ctx.strokeStyle = '#4c1d95';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h * 0.45);
        for (let x = 0; x < w; x += 20) {
          const hillY = h * 0.45 + Math.sin(x * 0.01 + tick * 0.02) * 8;
          ctx.lineTo(x, hillY);
        }
        ctx.lineTo(w, h);
        ctx.lineTo(0, h);
        ctx.fillStyle = '#2e1065';
        ctx.fill();
        ctx.stroke();
      } else if (isStreaming && nightVision) {
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, '#021208');
        grad.addColorStop(0.5, '#04220f');
        grad.addColorStop(1, '#010d05');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);

        ctx.strokeStyle = 'rgba(16, 185, 129, 0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h * 0.45);
        for (let x = 0; x <= w; x += 30) {
          const y = h * 0.45 + Math.sin((x + tick) * 0.015) * 6;
          ctx.lineTo(x, y);
        }
        ctx.stroke();

        for (let x = 40; x < w; x += 100) {
          ctx.beginPath();
          ctx.moveTo(x, h * 0.45);
          ctx.lineTo(x, h * 0.85);
          ctx.strokeStyle = 'rgba(16, 185, 129, 0.3)';
          ctx.stroke();
        }
      } else {
        // Clear canvas overlay to reveal underlying live JPEG stream
        ctx.clearRect(0, 0, w, h);
        if (!isStreaming) {
          const grad = ctx.createLinearGradient(0, 0, 0, h);
          grad.addColorStop(0, '#0f172a');
          grad.addColorStop(1, '#020617');
          ctx.fillStyle = grad;
          ctx.fillRect(0, 0, w, h);
        }
      }

      // 2. Tactical Scan Lines & Crosshairs (Only when streaming)
      if (isStreaming) {
        ctx.strokeStyle = nightVision ? 'rgba(16, 185, 129, 0.15)' : 'rgba(59, 130, 246, 0.15)';
        ctx.lineWidth = 1;
        const scanY = (tick * 2) % h;
        ctx.beginPath();
        ctx.moveTo(0, scanY);
        ctx.lineTo(w, scanY);
        ctx.stroke();

        const cx = w / 2;
        const cy = h / 2;
        ctx.strokeStyle = nightVision ? 'rgba(16, 185, 129, 0.4)' : 'rgba(59, 130, 246, 0.4)';
        ctx.beginPath();
        ctx.arc(cx, cy, 30, 0, Math.PI * 2);
        ctx.moveTo(cx - 40, cy); ctx.lineTo(cx - 10, cy);
        ctx.moveTo(cx + 10, cy); ctx.lineTo(cx + 40, cy);
        ctx.moveTo(cx, cy - 40); ctx.lineTo(cx, cy - 10);
        ctx.moveTo(cx, cy + 10); ctx.lineTo(cx, cy + 40);
        ctx.stroke();
      }

      // 3. Polygon Virtual Fence Zone Overlay
      if (isStreaming) {
        ctx.save();
        ctx.beginPath();
        ctx.moveTo(w * 0.15, h * 0.25);
        ctx.lineTo(w * 0.85, h * 0.25);
        ctx.lineTo(w * 0.92, h * 0.82);
        ctx.lineTo(w * 0.08, h * 0.82);
        ctx.closePath();
        ctx.fillStyle = 'rgba(239, 68, 68, 0.15)';
        ctx.fill();
        ctx.strokeStyle = '#ef4444';
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 4]);
        ctx.stroke();

        ctx.fillStyle = '#ef4444';
        ctx.font = 'bold 11px monospace';
        ctx.fillText('WARNING: RESTRICTED VIRTUAL FENCE ZONE', w * 0.16, h * 0.29);
        ctx.restore();
      }

      // 4. Render Dynamic Bounding Boxes & Inactive Card State
      const activeDets = detections || [];
      const activeFaces = faces || [];

      if (!isStreaming) {
        ctx.save();
        ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
        ctx.fillRect(w * 0.20, h * 0.35, w * 0.60, h * 0.30);
        ctx.strokeStyle = 'rgba(148, 163, 184, 0.3)';
        ctx.strokeRect(w * 0.20, h * 0.35, w * 0.60, h * 0.30);

        ctx.fillStyle = '#94a3b8';
        ctx.font = 'bold 15px monospace';
        ctx.textAlign = 'center';
        ctx.fillText('NO ACTIVE VIDEO SOURCE', w / 2, h * 0.46);
        ctx.font = '11px monospace';
        ctx.fillStyle = '#64748b';
        ctx.fillText('Start this camera stream in Camera Management or Demo Control.', w / 2, h * 0.54);
        ctx.restore();
      }

      if (isStreaming) {
        // A. Person & Vehicle Object Bounding Boxes
        activeDets.forEach((det) => {
          const [nx, ny, nw, nh] = det.bbox;
          const bx = nx * w;
          const by = ny * h;
          const bw = nw * w;
          const bh = nh * h;

          const cls = (det.class_name || '').toLowerCase();
          const isVehicle = ['car', 'truck', 'lorry', 'bus', 'motorcycle', 'bicycle'].includes(cls);
          const trackPrefix = isVehicle ? 'V' : 'P';
          const displayLabel = (cls === 'truck' || cls === 'lorry') ? 'TRUCK / LORRY' : cls.toUpperCase();

          // Class-specific tactical colors
          const boxColor =
            cls === 'person' ? '#38bdf8' :
            (cls === 'bus' || cls === 'truck' || cls === 'lorry') ? '#f59e0b' :
            cls === 'car' ? '#10b981' :
            '#a855f7';

          ctx.strokeStyle = boxColor;
          ctx.lineWidth = 2;
          ctx.strokeRect(bx, by, bw, bh);

          const len = 10;
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = 2;
          ctx.beginPath(); ctx.moveTo(bx, by + len); ctx.lineTo(bx, by); ctx.lineTo(bx + len, by); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(bx + bw - len, by); ctx.lineTo(bx + bw, by); ctx.lineTo(bx + bw, by + len); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(bx, by + bh - len); ctx.lineTo(bx, by + bh); ctx.lineTo(bx + len, by + bh); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(bx + bw - len, by + bh); ctx.lineTo(bx + bw, by + bh); ctx.lineTo(bx + bw, by + bh - len); ctx.stroke();

          const labelText = `${trackPrefix}-${det.track_id} | ${displayLabel} | ${(det.confidence * 100).toFixed(0)}%`;
          ctx.font = 'bold 11px monospace';
          const textWidth = ctx.measureText(labelText).width;

          ctx.fillStyle = boxColor;
          ctx.fillRect(bx, by - 20, textWidth + 8, 20);

          ctx.fillStyle = '#0f172a';
          ctx.font = 'bold 11px monospace';
          ctx.fillText(labelText, bx + 4, by - 6);
        });

        // B. Real Face Bounding Boxes & Recognition Badges
        activeFaces.forEach((face) => {
          const [nx, ny, nw, nh] = face.bbox;
          const fx = nx * w;
          const fy = ny * h;
          const fw = nw * w;
          const fh = nh * h;

          const isKnown = face.recognition_status === 'KNOWN';
          const isUncertain = face.recognition_status === 'UNCERTAIN';
          const faceColor = isKnown ? '#10b981' : isUncertain ? '#f59e0b' : '#38bdf8';

          // Face box
          ctx.strokeStyle = faceColor;
          ctx.lineWidth = 2;
          ctx.strokeRect(fx, fy, fw, fh);

          // Face landmarks (5 dots)
          if (face.landmarks && Array.isArray(face.landmarks)) {
            ctx.fillStyle = '#facc15';
            face.landmarks.forEach((lm) => {
              const lx = lm[0] * w;
              const ly = lm[1] * h;
              ctx.beginPath();
              ctx.arc(lx, ly, 2, 0, Math.PI * 2);
              ctx.fill();
            });
          }

          // Face Label
          let faceLabel = `#F${face.track_id} UNKNOWN ${(face.confidence * 100).toFixed(0)}%`;
          if (isKnown && face.identity_name) {
            faceLabel = `#F${face.track_id} KNOWN: ${face.identity_name.toUpperCase()} (${(face.recognition_confidence * 100).toFixed(0)}%)`;
          } else if (isUncertain) {
            faceLabel = `#F${face.track_id} UNCERTAIN (LOW QUAL)`;
          }

          ctx.font = 'bold 10px monospace';
          const labelWidth = ctx.measureText(faceLabel).width;
          ctx.fillStyle = faceColor;
          ctx.fillRect(fx, fy - 18, labelWidth + 6, 18);
          ctx.fillStyle = isKnown ? '#022c22' : '#0f172a';
          ctx.fillText(faceLabel, fx + 3, fy - 5);
        });
      }

      // 5. Render Camera Status & Telemetry Header
      ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
      ctx.fillRect(10, 10, 380, 36);
      ctx.strokeStyle = 'rgba(59, 130, 246, 0.4)';
      ctx.strokeRect(10, 10, 380, 36);

      ctx.fillStyle = isStreaming ? (nightVision ? '#10b981' : '#38bdf8') : '#64748b';
      ctx.font = 'bold 11px monospace';
      ctx.fillText(
        isStreaming ? `● STREAM | ${cameraId || 'CAM'} ${cameraName ? '- ' + cameraName : ''}` : '● NO ACTIVE STREAM',
        20, 26
      );
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px monospace';
      ctx.fillText(
        isStreaming ? `ROLE: ${(cameraRole || 'CAMERA').toUpperCase()} | TIME: ${new Date().toISOString().substring(11, 19)} UTC` : 'STREAM INACTIVE',
        20, 39
      );

      animFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animFrameId);
    };
  }, [thermalMode, nightVision, detections, isStreaming, cameraId, cameraName, cameraRole]);

  return (
    <div className="relative aspect-video bg-slate-950 rounded-lg overflow-hidden border border-[#252d42] group">
      {cameraId && !imageError && (
        <img
          src={`/api/cameras/${cameraId}/stream`}
          alt="Live Camera Stream"
          className="absolute inset-0 w-full h-full object-cover pointer-events-none"
          onError={() => setImageError(true)}
        />
      )}
      <canvas
        ref={canvasRef}
        width={1280}
        height={720}
        className="relative z-10 w-full h-full object-cover"
      />

      {/* Development Diagnostics Overlay */}
      {showDiagnostics && (
        <div className="absolute top-12 left-3 z-20 bg-slate-950/90 border border-amber-500/40 p-2.5 rounded text-[10px] font-mono text-amber-300 space-y-1 backdrop-blur max-w-xs shadow-xl">
          <div className="font-bold border-b border-amber-500/30 pb-1 flex justify-between">
            <span>DEV DIAGNOSTICS</span>
            <span className="text-slate-400">{cameraId}</span>
          </div>
          <div>Role: <strong>{cameraRole || 'secondary'}</strong></div>
          <div>Status: <strong>{isStreaming ? 'STREAMING' : 'OFFLINE'}</strong></div>
          <div>Video FPS: <strong>{fps}</strong></div>
          <div>AI Latency: <strong>{latencyMs}ms</strong></div>
          <div>Objects Tracked: <strong>{detections.length}</strong></div>
          <div>Inference: <strong>{inferenceMode || 'N/A'}</strong></div>
        </div>
      )}

      {/* Control Overlay Buttons */}
      <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-slate-900/80 backdrop-blur p-1 rounded-lg border border-[#252d42] opacity-90 group-hover:opacity-100 transition-opacity z-20">
        <button
          onClick={() => setShowDiagnostics(!showDiagnostics)}
          className={`p-1 rounded text-[11px] font-mono font-bold flex items-center gap-1 transition-colors ${
            showDiagnostics ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Development Diagnostics"
        >
          <Bug className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => { if (isStreaming) { setNightVision(!nightVision); setThermalMode(false); } }}
          disabled={!isStreaming}
          className={`px-2 py-1 rounded text-[10px] font-mono font-bold flex items-center gap-1 transition-colors ${
            !isStreaming
              ? 'opacity-40 cursor-not-allowed text-slate-500 bg-slate-800'
              : nightVision
              ? 'bg-emerald-600 text-white'
              : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Night Vision Mode"
        >
          <Moon className="w-3 h-3" /> NIGHT
        </button>
        <button
          onClick={() => { if (isStreaming) { setThermalMode(!thermalMode); setNightVision(false); } }}
          disabled={!isStreaming}
          className={`px-2 py-1 rounded text-[10px] font-mono font-bold flex items-center gap-1 transition-colors ${
            !isStreaming
              ? 'opacity-40 cursor-not-allowed text-slate-500 bg-slate-800'
              : thermalMode
              ? 'bg-purple-600 text-white'
              : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Thermal Infrared Mode"
        >
          <Eye className="w-3 h-3" /> THERMAL
        </button>
      </div>

      {/* Footer Telemetry */}
      <div className="absolute bottom-0 left-0 right-0 p-2.5 bg-slate-950/90 border-t border-[#252d42] flex items-center justify-between text-[11px] text-slate-400 font-mono z-20">
        <div className="flex items-center gap-3">
          <span>FPS: <strong className={isStreaming ? 'text-emerald-400' : 'text-slate-500'}>{isStreaming ? fps : 0}</strong></span>
          <span>LATENCY: <strong className={isStreaming ? 'text-blue-400' : 'text-slate-500'}>{isStreaming ? `${latencyMs}ms` : 'N/A'}</strong></span>
          <span>OBJECTS: <strong className={isStreaming ? 'text-amber-400' : 'text-slate-500'}>{isStreaming ? (detections ? detections.length : 0) + ' Active' : 0}</strong></span>
        </div>
        <span className={isStreaming ? 'text-emerald-400 font-bold tracking-wider font-mono' : 'text-slate-500 font-mono'}>
          {isStreaming ? (inferenceMode || 'REAL AI | INFERENCE RUNNING') : 'CAMERA OFFLINE | AI INFERENCE STOPPED'}
        </span>
      </div>
    </div>
  );
};
