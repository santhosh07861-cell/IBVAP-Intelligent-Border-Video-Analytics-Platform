import React, { useEffect, useRef, useState } from 'react';
import { Eye, Moon, Bug, RotateCw } from 'lucide-react';

interface LiveVideoCanvasProps {
  cameraId?: string;
  cameraName?: string;
  status?: string;
  detections?: Array<{
    track_id: number;
    class_name: string;
    confidence: number;
    bbox: number[];
    dwell_time_sec: number;
    is_fallback: boolean;
    movement_state?: string;
    direction?: string;
    movement_delta?: number;
    velocity?: number;
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
    person_id?: string | null;
    category?: string | null;
    recognition_confidence?: number;
  }>;
  fps?: number;
  latencyMs?: number;
  inferenceMode?: string;
  cameraRole?: 'primary' | 'secondary';
  protocol?: string;
  hideObjectDetections?: boolean;
  rotation?: number;
  onRotate?: (newRotation: number) => void;
}

export const LiveVideoCanvas: React.FC<LiveVideoCanvasProps> = ({
  cameraId,
  cameraName,
  status,
  detections = [],
  faces = [],
  fps = 0.0,
  latencyMs = 0.0,
  inferenceMode,
  cameraRole,
  protocol,
  hideObjectDetections = false,
  rotation = 0,
  onRotate
}) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [thermalMode, setThermalMode] = useState<boolean>(false);
  const [nightVision, setNightVision] = useState<boolean>(false);
  const [showDiagnostics, setShowDiagnostics] = useState<boolean>(false);
  const [imageError, setImageError] = useState<boolean>(false);
  const [currentRotation, setCurrentRotation] = useState<number>(rotation || 0);

  useEffect(() => {
    setCurrentRotation(rotation || 0);
  }, [rotation]);

  const [activeZones, setActiveZones] = useState<Array<{ id: string; name: string; zone_type: string; coordinates: number[][] }>>([]);

  // Normalize and determine genuine camera status
  const normalizedStatus = (status || '').toUpperCase().trim();
  const isMp4 = (protocol || '').toUpperCase() === 'MP4' || ['READY', 'PLAYING', 'PROCESSING', 'COMPLETED', 'FILE ERROR', 'FILE_ERROR'].includes(normalizedStatus);
  let effectiveStatus: 'ONLINE' | 'CONNECTING' | 'UNREACHABLE' | 'NO_FRAMES' | 'STOPPED' | 'OFFLINE' | 'READY' | 'PLAYING' | 'PROCESSING' | 'COMPLETED' | 'FILE ERROR';

  if (!cameraId) {
    effectiveStatus = 'OFFLINE';
  } else if (normalizedStatus === 'STOPPED' || normalizedStatus === 'DISCONNECTED') {
    effectiveStatus = 'STOPPED';
  } else if (normalizedStatus === 'COMPLETED') {
    effectiveStatus = 'COMPLETED';
  } else if (normalizedStatus === 'FILE ERROR' || normalizedStatus === 'FILE_ERROR') {
    effectiveStatus = 'FILE ERROR';
  } else if (normalizedStatus === 'READY') {
    effectiveStatus = fps > 0 ? 'PLAYING' : 'READY';
  } else if (normalizedStatus === 'PLAYING' || normalizedStatus === 'PROCESSING') {
    effectiveStatus = fps > 0 ? normalizedStatus as any : 'PROCESSING';
  } else if (isMp4) {
    // For MP4 sources, NEVER show network states (UNREACHABLE / NETWORK ERROR)
    if (imageError || normalizedStatus === 'UNREACHABLE') {
      effectiveStatus = 'FILE ERROR';
    } else {
      effectiveStatus = fps > 0 ? 'PLAYING' : 'READY';
    }
  } else if (normalizedStatus === 'UNREACHABLE' || imageError) {
    effectiveStatus = 'UNREACHABLE';
  } else if (normalizedStatus === 'NO_FRAMES') {
    effectiveStatus = 'NO_FRAMES';
  } else if (normalizedStatus === 'CONNECTING' || normalizedStatus === 'RECONNECTING') {
    effectiveStatus = fps > 0 ? 'ONLINE' : 'CONNECTING';
  } else if (normalizedStatus === 'ONLINE') {
    effectiveStatus = fps > 0 ? 'ONLINE' : 'CONNECTING';
  } else {
    effectiveStatus = fps > 0 ? 'ONLINE' : (cameraId ? 'CONNECTING' : 'OFFLINE');
  }

  const isLive = (effectiveStatus === 'ONLINE' || effectiveStatus === 'PLAYING' || effectiveStatus === 'PROCESSING') && fps > 0;
  const isFeedActive = Boolean(
    cameraId &&
    !imageError &&
    effectiveStatus !== 'STOPPED' &&
    effectiveStatus !== 'OFFLINE' &&
    effectiveStatus !== 'COMPLETED' &&
    effectiveStatus !== 'FILE ERROR'
  );

  const [retryKey, setRetryKey] = useState<number>(0);

  useEffect(() => {
    setImageError(false);
  }, [cameraId, status]);

  useEffect(() => {
    if (imageError && effectiveStatus !== 'STOPPED' && effectiveStatus !== 'OFFLINE') {
      const timer = setTimeout(() => {
        setImageError(false);
        setRetryKey(k => k + 1);
      }, 3000);
      return () => clearTimeout(timer);
    }
  }, [imageError, effectiveStatus]);

  useEffect(() => {
    if (!cameraId) {
      setActiveZones([]);
      return;
    }
    const fetchZonesForCam = async () => {
      try {
        const token = localStorage.getItem('ibvap_token');
        const headers: Record<string, string> = {};
        if (token) headers['Authorization'] = `Bearer ${token}`;
        const res = await fetch(`/api/zones?camera_id=${encodeURIComponent(cameraId)}`, { headers });
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data)) {
            setActiveZones(data.filter((z: any) => z.is_active && Array.isArray(z.coordinates) && z.coordinates.length >= 3));
          }
        }
      } catch (e) {
        // silent
      }
    };
    fetchZonesForCam();
    // Refresh zones periodically (every 60s) without aggressive 5s HTTP polling
    const interval = setInterval(fetchZonesForCam, 60000);
    return () => clearInterval(interval);
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

      // 1. Thermal or Night Vision background overlay
      if (isLive && thermalMode) {
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, '#0a0314');
        grad.addColorStop(0.5, '#19082b');
        grad.addColorStop(1, '#05020a');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      } else if (isLive && nightVision) {
        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, '#021208');
        grad.addColorStop(0.5, '#04220f');
        grad.addColorStop(1, '#010d05');
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      } else {
        ctx.clearRect(0, 0, w, h);
        if (!isLive) {
          const grad = ctx.createLinearGradient(0, 0, 0, h);
          grad.addColorStop(0, '#0f172a');
          grad.addColorStop(1, '#020617');
          ctx.fillStyle = grad;
          ctx.fillRect(0, 0, w, h);
        }
      }

      // 2. Tactical Crosshairs
      if (isLive) {
        const cx = w / 2;
        const cy = h / 2;
        ctx.strokeStyle = nightVision ? 'rgba(16, 185, 129, 0.3)' : 'rgba(59, 130, 246, 0.3)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(cx, cy, 25, 0, Math.PI * 2);
        ctx.moveTo(cx - 35, cy); ctx.lineTo(cx - 10, cy);
        ctx.moveTo(cx + 10, cy); ctx.lineTo(cx + 35, cy);
        ctx.moveTo(cx, cy - 35); ctx.lineTo(cx, cy - 10);
        ctx.moveTo(cx, cy + 10); ctx.lineTo(cx, cy + 35);
        ctx.stroke();
      }

      // 3. Dynamic Real Database Virtual Fence Zones Overlay for this Camera
      if (isLive && activeZones.length > 0) {
        activeZones.forEach((zone) => {
          if (!zone.coordinates || zone.coordinates.length < 3) return;
          ctx.save();
          ctx.beginPath();
          zone.coordinates.forEach((pt: number[], idx: number) => {
            const px = pt[0] * w;
            const py = pt[1] * h;
            if (idx === 0) ctx.moveTo(px, py);
            else ctx.lineTo(px, py);
          });
          ctx.closePath();
          ctx.fillStyle = 'rgba(239, 68, 68, 0.12)';
          ctx.fill();
          ctx.strokeStyle = '#ef4444';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([6, 4]);
          ctx.stroke();

          const firstPt = zone.coordinates[0];
          ctx.fillStyle = '#ef4444';
          ctx.font = 'bold 11px monospace';
          ctx.fillText(`🚨 ${zone.name.toUpperCase()}`, firstPt[0] * w + 6, Math.max(20, firstPt[1] * h - 6));
          ctx.restore();
        });
      }

      // 4. Inactive Card State Overlay
      if (!isLive) {
        ctx.save();
        ctx.fillStyle = 'rgba(15, 23, 42, 0.88)';
        ctx.fillRect(w * 0.15, h * 0.32, w * 0.70, h * 0.36);
        ctx.strokeStyle =
          effectiveStatus === 'COMPLETED' ? 'rgba(168, 85, 247, 0.4)' :
          effectiveStatus === 'FILE ERROR' ? 'rgba(239, 68, 68, 0.4)' :
          effectiveStatus === 'READY' ? 'rgba(56, 189, 248, 0.4)' :
          effectiveStatus === 'UNREACHABLE' ? 'rgba(239, 68, 68, 0.4)' :
          effectiveStatus === 'NO_FRAMES' ? 'rgba(245, 158, 11, 0.4)' :
          effectiveStatus === 'CONNECTING' ? 'rgba(56, 189, 248, 0.4)' :
          'rgba(148, 163, 184, 0.25)';
        ctx.strokeRect(w * 0.15, h * 0.32, w * 0.70, h * 0.36);

        ctx.textAlign = 'center';
        if (effectiveStatus === 'COMPLETED') {
          ctx.fillStyle = '#c084fc';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('VIDEO COMPLETED', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#cbd5e1';
          ctx.fillText('Video reached the end. AI processing completed.', w / 2, h * 0.55);
        } else if (effectiveStatus === 'FILE ERROR') {
          ctx.fillStyle = '#f87171';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('FILE ERROR', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#fca5a5';
          ctx.fillText('Video file cannot be opened or read. Check file path.', w / 2, h * 0.55);
        } else if (effectiveStatus === 'READY') {
          ctx.fillStyle = '#38bdf8';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('VIDEO READY', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#94a3b8';
          ctx.fillText('MP4 source verified. Click START CAMERA to stream & process.', w / 2, h * 0.55);
        } else if (effectiveStatus === 'STOPPED') {
          ctx.fillStyle = '#94a3b8';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('CAMERA FEED STOPPED', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#64748b';
          ctx.fillText('Click START CAMERA in Camera Management to stream.', w / 2, h * 0.55);
        } else if (effectiveStatus === 'CONNECTING' || effectiveStatus === 'PROCESSING') {
          ctx.fillStyle = '#38bdf8';
          ctx.font = 'bold 15px monospace';
          ctx.fillText(effectiveStatus === 'PROCESSING' ? 'PROCESSING VIDEO FEED' : 'CONNECTING / WAITING FOR FIRST FRAME', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#94a3b8';
          ctx.fillText('Establishing video ingestion pipeline...', w / 2, h * 0.55);
        } else if (effectiveStatus === 'UNREACHABLE') {
          ctx.fillStyle = '#f87171';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('CAMERA UNREACHABLE', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#94a3b8';
          ctx.fillText('No route to camera host. Check IP and network connection.', w / 2, h * 0.55);
        } else if (effectiveStatus === 'NO_FRAMES') {
          ctx.fillStyle = '#fbbf24';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('NO LIVE FRAME RECEIVED', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#94a3b8';
          ctx.fillText('Stream connected but source has delivered 0 FPS.', w / 2, h * 0.55);
        } else {
          ctx.fillStyle = '#94a3b8';
          ctx.font = 'bold 15px monospace';
          ctx.fillText('CAMERA FEED OFFLINE', w / 2, h * 0.47);
          ctx.font = '11px monospace';
          ctx.fillStyle = '#64748b';
          ctx.fillText('Start this camera stream in Camera Management.', w / 2, h * 0.55);
        }
        ctx.restore();
      }

      if (isLive) {
        // A. General Object Bounding Boxes (suppressed on dedicated Face Intelligence page)
        if (!hideObjectDetections) {
          (detections || []).forEach((det) => {
            const [nx, ny, nw, nh] = det.bbox;
            const bx = nx * w;
            const by = ny * h;
            const bw = nw * w;
            const bh = nh * h;

            const cls = (det.class_name || '').toLowerCase().trim();
            const isPerson = cls === 'person';
            const isVehicle = ['car', 'truck', 'lorry', 'bus', 'motorcycle', 'bicycle', 'van'].includes(cls);
            const isDrone = cls === 'drone';

            const trackPrefix = isPerson ? 'P' : isVehicle ? 'V' : isDrone ? 'D' : 'O';
            const displayLabel = (cls === 'truck' || cls === 'lorry')
              ? 'TRUCK'
              : cls === 'cell phone'
              ? 'PHONE'
              : cls ? cls.toUpperCase() : 'OBJECT';

            const boxColor =
              isPerson ? '#38bdf8' :
              (cls === 'bus' || cls === 'truck') ? '#f59e0b' :
              cls === 'car' ? '#10b981' :
              isVehicle ? '#3b82f6' :
              isDrone ? '#ec4899' :
              '#94a3b8';

            ctx.strokeStyle = boxColor;
            ctx.lineWidth = 2;
            ctx.strokeRect(bx, by, bw, bh);

            const len = 8;
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 2;
            ctx.beginPath(); ctx.moveTo(bx, by + len); ctx.lineTo(bx, by); ctx.lineTo(bx + len, by); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(bx + bw - len, by); ctx.lineTo(bx + bw, by); ctx.lineTo(bx + bw, by + len); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(bx, by + bh - len); ctx.lineTo(bx, by + bh); ctx.lineTo(bx + len, by + bh); ctx.stroke();
            ctx.beginPath(); ctx.moveTo(bx + bw - len, by + bh); ctx.lineTo(bx + bw, by + bh); ctx.lineTo(bx + bw, by + bh - len); ctx.stroke();

            const movementSuffix = det.movement_state && det.movement_state !== 'STATIONARY'
              ? ` • ${det.movement_state}${det.direction && det.direction !== 'STATIONARY' ? ' ' + det.direction : ''}`
              : '';
            const labelText = `${trackPrefix}-${det.track_id} | ${displayLabel} | ${(det.confidence * 100).toFixed(0)}%${movementSuffix}`;
            ctx.font = 'bold 11px monospace';
            const textWidth = ctx.measureText(labelText).width;

            ctx.fillStyle = boxColor;
            ctx.fillRect(bx, by - 20, textWidth + 8, 20);

            ctx.fillStyle = '#0f172a';
            ctx.fillText(labelText, bx + 4, by - 6);
          });
        }

        // B. Face Bounding Boxes with College Security Badges
        (faces || []).forEach((face: any) => {
          const [nx, ny, nw, nh] = face.bbox;
          const fx = nx * w;
          const fy = ny * h;
          const fw = nw * w;
          const fh = nh * h;

          const isVerified = face.recognition_status === 'VERIFIED';
          const isThreat = face.recognition_status === 'KNOWN' && !isVerified;
          const faceColor = isThreat ? '#ef4444' : isVerified ? '#10b981' : '#f59e0b';

          ctx.strokeStyle = faceColor;
          ctx.lineWidth = isThreat ? 3 : 2;
          ctx.strokeRect(fx, fy, fw, fh);

          // Face landmarks (5 tactical dots)
          if (face.landmarks && Array.isArray(face.landmarks)) {
            ctx.fillStyle = '#facc15';
            face.landmarks.forEach((lm: number[]) => {
              const lx = lm[0] * w;
              const ly = lm[1] * h;
              ctx.beginPath();
              ctx.arc(lx, ly, 2.5, 0, Math.PI * 2);
              ctx.fill();
            });
          }

          // Tactical badge label
          let faceLabel = `#F${face.track_id} UNKNOWN (${(face.confidence * 100).toFixed(0)}%)`;
          if (isVerified && face.identity_name) {
            const badge = face.person_id ? ` | ${face.person_id}` : '';
            faceLabel = `🎓 VERIFIED: ${face.identity_name.toUpperCase()}${badge}`;
          } else if (isThreat && face.identity_name) {
            const badge = face.person_id ? ` | ${face.person_id}` : '';
            faceLabel = `🚨 WATCHLIST: ${face.identity_name.toUpperCase()}${badge}`;
          } else if (face.recognition_status === 'UNCERTAIN') {
            faceLabel = `❓ UNCERTAIN / LOW QUAL (#F${face.track_id})`;
          }

          ctx.font = 'bold 10px monospace';
          const labelWidth = ctx.measureText(faceLabel).width;
          ctx.fillStyle = faceColor;
          ctx.fillRect(fx, fy - 18, labelWidth + 8, 18);
          ctx.fillStyle = isThreat || isVerified ? '#ffffff' : '#0f172a';
          ctx.fillText(faceLabel, fx + 4, fy - 5);
        });
      }

      // 5. Header Status Bar
      ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
      ctx.fillRect(10, 10, 380, 36);
      ctx.strokeStyle =
        isLive ? 'rgba(59, 130, 246, 0.4)' :
        effectiveStatus === 'CONNECTING' ? 'rgba(56, 189, 248, 0.4)' :
        effectiveStatus === 'UNREACHABLE' ? 'rgba(239, 68, 68, 0.4)' :
        effectiveStatus === 'NO_FRAMES' ? 'rgba(245, 158, 11, 0.4)' :
        'rgba(148, 163, 184, 0.2)';
      ctx.strokeRect(10, 10, 380, 36);

      const headerColor =
        isLive ? (nightVision ? '#10b981' : '#38bdf8') :
        effectiveStatus === 'CONNECTING' ? '#38bdf8' :
        effectiveStatus === 'UNREACHABLE' ? '#f87171' :
        effectiveStatus === 'NO_FRAMES' ? '#fbbf24' : '#64748b';

      const statusTag =
        isLive ? 'LIVE STREAM' :
        effectiveStatus === 'CONNECTING' ? 'CONNECTING' :
        effectiveStatus === 'UNREACHABLE' ? 'UNREACHABLE' :
        effectiveStatus === 'NO_FRAMES' ? 'NO FRAMES' :
        effectiveStatus === 'STOPPED' ? 'STOPPED' : 'OFFLINE';

      ctx.fillStyle = headerColor;
      ctx.font = 'bold 11px monospace';
      ctx.fillText(
        `● ${statusTag} | ${cameraId || 'CAM'} ${cameraName ? '- ' + cameraName : ''}`,
        20, 26
      );
      ctx.fillStyle = '#94a3b8';
      ctx.font = '10px monospace';
      ctx.fillText(
        `ROLE: ${(cameraRole || 'CAMERA').toUpperCase()} | TIME: ${new Date().toISOString().substring(11, 19)} UTC`,
        20, 39
      );
    };

    // Render once whenever detection props, streaming state, or display modes change
    render();

    // 1 Hz interval to update tactical clock without burning 60 FPS GPU/CPU
    const clockInterval = setInterval(() => {
      render();
    }, 1000);

    return () => {
      clearInterval(clockInterval);
    };
  }, [thermalMode, nightVision, detections, faces, isLive, effectiveStatus, cameraId, cameraName, cameraRole, fps, activeZones, currentRotation]);

  return (
    <div className="relative aspect-video bg-slate-950 rounded-lg overflow-hidden border border-[#252d42] group">
      {isFeedActive && (
        <img
          key={`${cameraId}_${retryKey}`}
          src={`/api/cameras/${cameraId}/stream?r=${retryKey}`}
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

      {/* Diagnostics Overlay */}
      {showDiagnostics && (
        <div className="absolute top-12 left-3 z-20 bg-slate-950/90 border border-amber-500/40 p-2.5 rounded text-[10px] font-mono text-amber-300 space-y-1 backdrop-blur max-w-xs shadow-xl">
          <div className="font-bold border-b border-amber-500/30 pb-1 flex justify-between">
            <span>DIAGNOSTICS</span>
            <span className="text-slate-400">{cameraId}</span>
          </div>
          <div>Role: <strong>{cameraRole || 'secondary'}</strong></div>
          <div>Status: <strong>{effectiveStatus}</strong></div>
          <div>Rotation: <strong>{currentRotation}°</strong></div>
          <div>Video FPS: <strong>{isLive ? fps : 0}</strong></div>
          <div>AI Latency: <strong>{isLive ? `${latencyMs}ms` : 'N/A'}</strong></div>
          <div>{hideObjectDetections ? 'Faces Tracked' : 'Objects Tracked'}: <strong>{isLive ? (hideObjectDetections ? (faces?.length || 0) : detections.length) : 0}</strong></div>
          <div>Inference: <strong>{isLive ? (inferenceMode || 'REAL AI | RUNNING') : effectiveStatus}</strong></div>
        </div>
      )}

      {/* Controls */}
      <div className="absolute top-3 right-3 flex items-center gap-1.5 bg-slate-900/80 backdrop-blur p-1 rounded-lg border border-[#252d42] opacity-90 group-hover:opacity-100 transition-opacity z-20">
        <button
          onClick={() => {
            const nextRot = (currentRotation + 90) % 360;
            setCurrentRotation(nextRot);
            if (onRotate) {
              onRotate(nextRot);
            } else if (cameraId) {
              const token = localStorage.getItem('ibvap_token');
              const headers: Record<string, string> = { 'Content-Type': 'application/json' };
              if (token) headers['Authorization'] = `Bearer ${token}`;
              fetch(`/api/cameras/${cameraId}/rotation`, {
                method: 'PUT',
                headers,
                body: JSON.stringify({ rotation: nextRot })
              }).catch(() => {});
            }
          }}
          disabled={!isFeedActive}
          className={`px-2 py-1 rounded text-[10px] font-mono font-bold flex items-center gap-1 transition-colors ${
            !isFeedActive
              ? 'opacity-40 cursor-not-allowed text-slate-500 bg-slate-800'
              : currentRotation > 0
              ? 'bg-blue-600 text-white'
              : 'text-slate-400 hover:text-white'
          }`}
          title={`Rotate Video (${currentRotation}°)`}
        >
          <RotateCw className="w-3 h-3" /> {currentRotation > 0 ? `${currentRotation}°` : 'ROTATE'}
        </button>
        <button
          onClick={() => setShowDiagnostics(!showDiagnostics)}
          className={`p-1 rounded text-[11px] font-mono font-bold flex items-center gap-1 transition-colors ${
            showDiagnostics ? 'bg-amber-600 text-white' : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Diagnostics"
        >
          <Bug className="w-3.5 h-3.5" />
        </button>
        <button
          onClick={() => { if (isFeedActive) { setNightVision(!nightVision); setThermalMode(false); } }}
          disabled={!isFeedActive}
          className={`px-2 py-1 rounded text-[10px] font-mono font-bold flex items-center gap-1 transition-colors ${
            !isFeedActive
              ? 'opacity-40 cursor-not-allowed text-slate-500 bg-slate-800'
              : nightVision
              ? 'bg-emerald-600 text-white'
              : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Night Vision"
        >
          <Moon className="w-3 h-3" /> NIGHT
        </button>
        <button
          onClick={() => { if (isFeedActive) { setThermalMode(!thermalMode); setNightVision(false); } }}
          disabled={!isFeedActive}
          className={`px-2 py-1 rounded text-[10px] font-mono font-bold flex items-center gap-1 transition-colors ${
            !isFeedActive
              ? 'opacity-40 cursor-not-allowed text-slate-500 bg-slate-800'
              : thermalMode
              ? 'bg-purple-600 text-white'
              : 'text-slate-400 hover:text-white'
          }`}
          title="Toggle Thermal Mode"
        >
          <Eye className="w-3 h-3" /> THERMAL
        </button>
      </div>

      {/* Footer Telemetry */}
      <div className="absolute bottom-0 left-0 right-0 p-2.5 bg-slate-950/90 border-t border-[#252d42] flex items-center justify-between text-[11px] text-slate-400 font-mono z-20">
        <div className="flex items-center gap-3">
          <span>FPS: <strong className={isLive ? 'text-emerald-400' : 'text-slate-500'}>{isLive ? fps : 0}</strong></span>
          <span>LATENCY: <strong className={isLive ? 'text-blue-400' : 'text-slate-500'}>{isLive ? `${latencyMs}ms` : 'N/A'}</strong></span>
          {hideObjectDetections ? (
            <span>FACES: <strong className={isLive && faces.length > 0 ? 'text-blue-400 font-bold' : 'text-slate-400'}>{isLive ? faces.length : 0}</strong></span>
          ) : (
            <span>OBJECTS: <strong className={isLive && detections.length > 0 ? 'text-amber-400' : 'text-slate-500'}>{isLive ? detections.length : 0}</strong></span>
          )}
        </div>
        {effectiveStatus === 'STOPPED' ? (
          <span className="text-slate-400 font-mono font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-slate-500" />
            CAMERA STOPPED
          </span>
        ) : effectiveStatus === 'COMPLETED' ? (
          <span className="text-purple-400 font-mono font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-purple-500" />
            COMPLETED
          </span>
        ) : effectiveStatus === 'FILE ERROR' ? (
          <span className="text-rose-400 font-mono font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-rose-500" />
            FILE ERROR
          </span>
        ) : effectiveStatus === 'READY' ? (
          <span className="text-sky-400 font-mono font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-sky-400" />
            READY
          </span>
        ) : effectiveStatus === 'UNREACHABLE' ? (
          <span className="text-rose-400 font-mono font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-rose-500" />
            UNREACHABLE / NETWORK ERROR
          </span>
        ) : effectiveStatus === 'CONNECTING' ? (
          <span className="text-cyan-400 font-mono font-bold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-cyan-400 animate-ping" />
            CONNECTING / WAITING FOR FIRST FRAME
          </span>
        ) : isLive ? (
          <span className="text-emerald-400 font-bold tracking-wider font-mono flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            {inferenceMode || (effectiveStatus === 'PLAYING' ? 'PLAYING | REAL AI INFERENCE' : 'ONLINE | REAL AI INFERENCE RUNNING')}
          </span>
        ) : effectiveStatus === 'NO_FRAMES' || (effectiveStatus === 'ONLINE' && fps === 0) ? (
          <span className="text-amber-400 font-bold tracking-wider font-mono flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-500 animate-ping" />
            NO LIVE FRAME RECEIVED
          </span>
        ) : (
          <span className="text-slate-500 font-mono">CAMERA OFFLINE</span>
        )}
      </div>
    </div>
  );
};
