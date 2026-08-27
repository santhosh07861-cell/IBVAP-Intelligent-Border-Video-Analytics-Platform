import React, { useEffect, useState, useRef } from 'react';
import {
  UserCheck, Shield, Users, AlertTriangle, Search, Filter,
  RefreshCw, Plus, Trash2, Camera as CameraIcon, Upload, CheckCircle2,
  X, Eye, Maximize2, Sparkles, UserX, HelpCircle, ShieldAlert, Cpu
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { useCameras } from '../context/CameraContext';
import { LiveVideoCanvas } from '../components/LiveVideoCanvas';

export const FaceView: React.FC = () => {
  const { token, user } = useAuth();
  const { lastMessage, telemetryMap } = useWebSocket();
  const { cameras, primaryCamera } = useCameras();
  const [selectedCamId, setSelectedCamId] = useState<string>('');

  const activeCamera = cameras.find((c) => c.id === selectedCamId) || primaryCamera || cameras[0] || null;

  // Navigation State
  const [activeTab, setActiveTab] = useState<'detections' | 'watchlist'>('detections');

  // KPI Metrics
  const [kpis, setKpis] = useState<any>({
    active_faces: 0,
    total_detections_24h: 0,
    known_faces: 0,
    unknown_faces: 0,
    uncertain_faces: 0,
    watchlist_matches: 0,
    total_watchlist_enrolled: 0,
    monitored_cameras: 0
  });

  // Detection History State
  const [detections, setDetections] = useState<any[]>([]);
  const [loadingDets, setLoadingDets] = useState<boolean>(true);
  const [selectedDetection, setSelectedDetection] = useState<any | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [cameraFilter, setCameraFilter] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Watchlist State
  const [watchlist, setWatchlist] = useState<any[]>([]);
  const [loadingWatchlist, setLoadingWatchlist] = useState<boolean>(false);
  const [isEnrollModalOpen, setIsEnrollModalOpen] = useState<boolean>(false);

  // Enrollment Form State
  const [enrollName, setEnrollName] = useState<string>('');
  const [enrollPersonId, setEnrollPersonId] = useState<string>('');
  const [enrollCategory, setEnrollCategory] = useState<string>('WATCHLIST');
  const [enrollNotes, setEnrollNotes] = useState<string>('');
  const [enrollImageFile, setEnrollImageFile] = useState<File | null>(null);
  const [enrollImagePreview, setEnrollImagePreview] = useState<string | null>(null);
  const [isCapturingWebcam, setIsCapturingWebcam] = useState<boolean>(false);
  const [enrolling, setEnrolling] = useState<boolean>(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);
  const [enrollSuccess, setEnrollSuccess] = useState<string | null>(null);

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Auth Header
  const getHeaders = () => {
    const headers: Record<string, string> = {};
    const authToken = token || localStorage.getItem('ibvap_token');
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
  };

  // Fetch KPIs
  const fetchKpis = async () => {
    try {
      const res = await fetch('/api/faces/kpis', { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setKpis(data);
      }
    } catch (e) {
      console.error('Failed to fetch face KPIs:', e);
    }
  };

  // Fetch Detections History
  const fetchDetections = async () => {
    setLoadingDets(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.append('recognition_status', statusFilter);
      if (cameraFilter !== 'all') params.append('camera_id', cameraFilter);
      if (searchQuery) params.append('search', searchQuery);
      params.append('limit', '60');

      const res = await fetch(`/api/faces?${params.toString()}`, { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setDetections(data.items || []);
      }
    } catch (e) {
      console.error('Failed to fetch face detections:', e);
    } finally {
      setLoadingDets(false);
    }
  };

  // Fetch Watchlist
  const fetchWatchlist = async () => {
    setLoadingWatchlist(true);
    try {
      const res = await fetch('/api/faces/watchlist', { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        setWatchlist(data || []);
      }
    } catch (e) {
      console.error('Failed to fetch watchlist:', e);
    } finally {
      setLoadingWatchlist(false);
    }
  };

  useEffect(() => {
    fetchKpis();
    fetchDetections();
    fetchWatchlist();
  }, [statusFilter, cameraFilter, searchQuery]);

  // Real-time WebSocket Listeners
  useEffect(() => {
    if (lastMessage) {
      if (lastMessage.type === 'FACE_DETECTION_UPDATE') {
        const newFace = {
          id: lastMessage.face_id || `f_${Date.now()}`,
          camera_id: lastMessage.camera_id,
          camera_number: lastMessage.camera_number,
          camera_name: lastMessage.camera_name,
          location: lastMessage.location,
          track_id: lastMessage.track_id,
          identity_id: lastMessage.identity_id,
          identity_name: lastMessage.identity_name || 'UNKNOWN',
          recognition_status: lastMessage.recognition_status || 'UNKNOWN',
          detection_confidence: lastMessage.detection_confidence || 0.90,
          recognition_confidence: lastMessage.recognition_confidence || 0.0,
          bbox: lastMessage.bbox,
          crop_url: lastMessage.crop_url,
          snapshot_url: lastMessage.snapshot_url,
          quality_score: lastMessage.quality_score || 0.85,
          timestamp: lastMessage.timestamp || new Date().toISOString()
        };

        setDetections((prev) => [newFace, ...prev.filter((d) => d.id !== newFace.id)]);
        fetchKpis();
      } else if (lastMessage.type === 'FACE_WATCHLIST_MATCH') {
        fetchKpis();
        fetchDetections();
      }
    }
  }, [lastMessage]);

  // Webcam Capture for Enrollment
  const startWebcamCapture = async () => {
    setIsCapturingWebcam(true);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play();
      }
    } catch (err) {
      console.error('Webcam access error:', err);
      setEnrollError('Unable to access webcam. Please ensure camera permissions are granted.');
      setIsCapturingWebcam(false);
    }
  };

  const stopWebcamCapture = () => {
    if (videoRef.current && videoRef.current.srcObject) {
      const stream = videoRef.current.srcObject as MediaStream;
      stream.getTracks().forEach((track) => track.stop());
      videoRef.current.srcObject = null;
    }
    setIsCapturingWebcam(false);
  };

  const capturePhotoFromWebcam = () => {
    if (videoRef.current && canvasRef.current) {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const dataUrl = canvas.toDataURL('image/jpeg', 0.92);
        setEnrollImagePreview(dataUrl);
        stopWebcamCapture();
      }
    }
  };

  // Handle Enrollment Submit
  const handleEnrollSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!enrollName.trim() || !enrollPersonId.trim()) {
      setEnrollError('Subject Name and Person ID are required.');
      return;
    }

    if (!enrollImageFile && !enrollImagePreview) {
      setEnrollError('Please upload a face photo or capture one using the webcam.');
      return;
    }

    setEnrolling(true);
    setEnrollError(null);
    setEnrollSuccess(null);

    try {
      const formData = new FormData();
      formData.append('name', enrollName.trim());
      formData.append('person_id', enrollPersonId.trim());
      formData.append('category', enrollCategory);
      if (enrollNotes) formData.append('notes', enrollNotes.trim());

      if (enrollImageFile) {
        formData.append('file', enrollImageFile);
      } else if (enrollImagePreview) {
        formData.append('image_base64', enrollImagePreview);
      }

      const res = await fetch('/api/faces/watchlist', {
        method: 'POST',
        headers: getHeaders(),
        body: formData
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || 'Enrollment failed.');
      }

      setEnrollSuccess(`Successfully enrolled ${enrollName} into Face Watchlist!`);
      fetchWatchlist();
      fetchKpis();

      setTimeout(() => {
        setIsEnrollModalOpen(false);
        setEnrollName('');
        setEnrollPersonId('');
        setEnrollNotes('');
        setEnrollImageFile(null);
        setEnrollImagePreview(null);
        setEnrollSuccess(null);
      }, 1500);
    } catch (err: any) {
      setEnrollError(err.message || 'Face enrollment failed. Ensure a single clear face is provided.');
    } finally {
      setEnrolling(false);
    }
  };

  // Delete Watchlist Entry
  const handleDeleteWatchlist = async (id: string, name: string) => {
    if (!window.confirm(`Are you sure you want to delete ${name} from the Watchlist?`)) return;
    try {
      const res = await fetch(`/api/faces/watchlist/${id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (res.ok) {
        fetchWatchlist();
        fetchKpis();
      }
    } catch (err) {
      console.error('Failed to delete watchlist entry:', err);
    }
  };

  // Toggle Watchlist Active Status
  const handleToggleWatchlistActive = async (id: string, currentActive: boolean) => {
    try {
      const formData = new FormData();
      formData.append('is_active', (!currentActive).toString());
      await fetch(`/api/faces/watchlist/${id}`, {
        method: 'PUT',
        headers: getHeaders(),
        body: formData
      });
      fetchWatchlist();
      fetchKpis();
    } catch (err) {
      console.error('Failed to toggle status:', err);
    }
  };

  // Current camera telemetry
  const activeCameraTelemetry = activeCamera ? telemetryMap[activeCamera.camera_id] : null;

  return (
    <div className="p-6 space-y-6 font-mono">
      {/* ── Top Header Bar ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-400" />
            Face Intelligence &amp; Recognition Center
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Deep Learning YuNet Face Detection · SFace Facial Embeddings · Watchlist Verification
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Tab Switcher */}
          <div className="flex items-center bg-[#0a0d14] rounded-lg border border-[#252d42] p-1">
            <button
              onClick={() => setActiveTab('detections')}
              className={`px-3 py-1.5 rounded text-xs font-bold uppercase transition-colors flex items-center gap-1.5 ${
                activeTab === 'detections' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Eye className="w-3.5 h-3.5" /> Detections Feed
            </button>
            <button
              onClick={() => setActiveTab('watchlist')}
              className={`px-3 py-1.5 rounded text-xs font-bold uppercase transition-colors flex items-center gap-1.5 ${
                activeTab === 'watchlist' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              <Users className="w-3.5 h-3.5" /> Watchlist ({watchlist.length})
            </button>
          </div>

          {activeTab === 'watchlist' && (
            <button
              onClick={() => {
                setIsEnrollModalOpen(true);
                setEnrollError(null);
                setEnrollSuccess(null);
              }}
              className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-emerald-950/40 transition-colors"
            >
              <Plus className="w-3.5 h-3.5" /> Enroll Person
            </button>
          )}

          <button
            onClick={() => {
              fetchKpis();
              fetchDetections();
              fetchWatchlist();
            }}
            className="px-3 py-2 bg-[#1a2030] hover:bg-[#252d42] text-slate-300 rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 border border-[#252d42] transition-colors"
          >
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </button>
        </div>
      </div>

      {/* ── Top KPI Cards Bar ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <div className="bg-[#111622] p-3.5 rounded-xl border border-[#252d42] space-y-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <Eye className="w-3 h-3 text-blue-400" /> Active Faces
          </div>
          <div className="text-xl font-bold text-blue-400 font-mono">{kpis.active_faces}</div>
          <div className="text-[9px] text-slate-500">Live In Frame</div>
        </div>

        <div className="bg-[#111622] p-3.5 rounded-xl border border-[#252d42] space-y-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <UserCheck className="w-3 h-3 text-emerald-400" /> Known Subjects
          </div>
          <div className="text-xl font-bold text-emerald-400 font-mono">{kpis.known_faces}</div>
          <div className="text-[9px] text-slate-500">Watchlist Matched</div>
        </div>

        <div className="bg-[#111622] p-3.5 rounded-xl border border-[#252d42] space-y-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <UserX className="w-3 h-3 text-slate-400" /> Unknown Faces
          </div>
          <div className="text-xl font-bold text-slate-200 font-mono">{kpis.unknown_faces}</div>
          <div className="text-[9px] text-slate-500">Unrecognized Logs</div>
        </div>

        <div className="bg-[#111622] p-3.5 rounded-xl border border-[#252d42] space-y-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <HelpCircle className="w-3 h-3 text-amber-400" /> Uncertain / Low Qual
          </div>
          <div className="text-xl font-bold text-amber-400 font-mono">{kpis.uncertain_faces}</div>
          <div className="text-[9px] text-slate-500">Low Light / Angle</div>
        </div>

        <div className="bg-[#111622] p-3.5 rounded-xl border border-[#252d42] space-y-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <ShieldAlert className="w-3 h-3 text-red-400" /> Watchlist Matches
          </div>
          <div className="text-xl font-bold text-red-400 font-mono">{kpis.watchlist_matches}</div>
          <div className="text-[9px] text-slate-500">High-Risk Alerts</div>
        </div>

        <div className="bg-[#111622] p-3.5 rounded-xl border border-[#252d42] space-y-1">
          <div className="text-[10px] text-slate-400 uppercase tracking-wider flex items-center gap-1">
            <Shield className="w-3 h-3 text-purple-400" /> Enrolled Database
          </div>
          <div className="text-xl font-bold text-purple-400 font-mono">{kpis.total_watchlist_enrolled}</div>
          <div className="text-[9px] text-slate-500">Total Enrolled Profiles</div>
        </div>
      </div>

      {/* ── TAB 1: DETECTIONS & LIVE INTELLIGENCE ── */}
      {activeTab === 'detections' && (
        <div className="space-y-6">
          {/* Live Stream Panel */}
          <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 text-xs font-bold text-slate-300 uppercase">
                <CameraIcon className="w-4 h-4 text-blue-400" />
                Live Video Face Tracking ({activeCamera?.camera_id || 'Select Camera'})
              </div>

              {/* Camera Selector */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-slate-400">Stream:</span>
                <select
                  value={activeCamera?.id || ''}
                  onChange={(e) => setSelectedCamId(e.target.value)}
                  className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-2.5 py-1 text-xs text-slate-200 font-mono focus:outline-none focus:border-blue-500"
                >
                  {cameras.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.camera_id} — {c.name} ({c.status})
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Canvas Video Component */}
            <div className="max-w-4xl mx-auto rounded-lg overflow-hidden border border-[#252d42]">
              <LiveVideoCanvas
                cameraId={activeCamera?.camera_id}
                cameraName={activeCamera?.name}
                detections={activeCameraTelemetry?.detections}
                faces={activeCameraTelemetry?.faces}
                fps={activeCameraTelemetry?.fps}
                latencyMs={activeCameraTelemetry?.latency_ms}
                inferenceMode={activeCameraTelemetry?.inference_mode}
                cameraRole={activeCamera?.role as any}
              />
            </div>
          </div>

          {/* Filter Bar */}
          <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42]">
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 text-xs">
              {/* Search */}
              <div className="relative col-span-1 sm:col-span-2">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="Search subject name, camera, status..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg pl-9 pr-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
                />
              </div>

              {/* Status Filter */}
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
              >
                <option value="all">All Recognition Statuses</option>
                <option value="KNOWN">Known / Watchlist Matched</option>
                <option value="UNKNOWN">Unknown Individuals</option>
                <option value="UNCERTAIN">Uncertain / Low Quality</option>
              </select>

              {/* Camera Filter */}
              <select
                value={cameraFilter}
                onChange={(e) => setCameraFilter(e.target.value)}
                className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
              >
                <option value="all">All Cameras</option>
                {cameras.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.camera_id}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Detections Gallery Grid */}
          {loadingDets ? (
            <div className="p-16 text-center text-slate-400 font-mono text-xs">
              <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              Loading real face detections from database...
            </div>
          ) : detections.length === 0 ? (
            <div className="bg-[#111622] p-16 rounded-xl border border-[#252d42] text-center space-y-3">
              <UserCheck className="w-10 h-10 text-slate-600 mx-auto" />
              <p className="font-bold text-slate-300 text-sm uppercase tracking-wider">
                NO REAL FACE DETECTIONS
              </p>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                WAITING FOR REAL CAMERA DATA — Connect an active camera stream. YuNet & SFace will automatically detect, track, and compare real faces from incoming video frames.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
              {detections.map((det) => {
                const isKnown = det.recognition_status === 'KNOWN';
                const isUncertain = det.recognition_status === 'UNCERTAIN';
                const statusBadgeCls = isKnown
                  ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/40'
                  : isUncertain
                  ? 'bg-amber-500/20 text-amber-400 border-amber-500/40'
                  : 'bg-blue-500/20 text-blue-400 border-blue-500/40';

                return (
                  <div
                    key={det.id}
                    className="bg-[#111622] rounded-xl border border-[#252d42] hover:border-blue-500/50 transition-all overflow-hidden flex flex-col group shadow-xl"
                  >
                    {/* Face Image Preview */}
                    <div
                      className="relative aspect-video bg-slate-950 overflow-hidden cursor-pointer flex items-center justify-center"
                      onClick={() => setSelectedDetection(det)}
                    >
                      {det.crop_url || det.snapshot_url ? (
                        <img
                          src={det.snapshot_url || det.crop_url}
                          alt="Face Evidence"
                          className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                        />
                      ) : (
                        <div className="text-slate-600 text-xs flex flex-col items-center gap-1">
                          <UserCheck className="w-8 h-8" />
                          No Image
                        </div>
                      )}

                      {/* Status Overlay Badge */}
                      <div className="absolute top-2 left-2 flex items-center gap-1">
                        <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase shadow ${statusBadgeCls}`}>
                          {det.recognition_status}
                        </span>
                        <span className="px-1.5 py-0.5 rounded bg-slate-900/90 text-blue-400 border border-blue-500/40 text-[9px] font-bold uppercase">
                          REAL SNAPSHOT
                        </span>
                      </div>

                      {/* Track ID Badge */}
                      <div className="absolute top-2 right-2 bg-slate-950/90 text-amber-400 font-bold text-[10px] px-2 py-0.5 rounded border border-amber-500/40">
                        #F{det.track_id || '101'}
                      </div>
                    </div>

                    {/* Card Content Body */}
                    <div className="p-4 space-y-2.5 flex-1 flex flex-col justify-between text-xs">
                      <div>
                        {/* Name / Identity */}
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-bold text-slate-100 text-sm truncate">
                            {isKnown ? det.identity_name : 'UNKNOWN INDIVIDUAL'}
                          </span>
                          <span className="text-emerald-400 font-bold text-[11px]">
                            {isKnown && det.recognition_confidence
                              ? `${(det.recognition_confidence * 100).toFixed(0)}% MATCH`
                              : `${(det.detection_confidence * 100).toFixed(0)}% CONF`}
                          </span>
                        </div>

                        {/* Metadata Rows */}
                        <div className="space-y-1 text-[11px] text-slate-400 font-mono pt-1">
                          <div>Camera: <strong className="text-blue-400">{det.camera_number || det.camera_id}</strong></div>
                          <div className="truncate">Location: <strong className="text-slate-300">{det.location || 'Unspecified Location'}</strong></div>
                          <div>
                            Event: <strong className="text-purple-400">{isKnown ? 'FACE WATCHLIST MATCH' : 'FACE DETECTION'}</strong>
                          </div>
                          <div>
                            Date: <strong className="text-slate-400">{new Date(det.timestamp).toLocaleDateString()}</strong>
                          </div>
                          <div>
                            Time: <strong className="text-slate-400">{new Date(det.timestamp).toLocaleTimeString()}</strong>
                          </div>
                          <div className="flex items-center justify-between pt-1">
                            <span>Quality: <strong className={det.quality_score >= 0.6 ? 'text-emerald-400' : 'text-amber-400'}>
                              {(det.quality_score * 100).toFixed(0)}/100
                            </strong></span>
                            {isKnown && (
                              <span>Sim: <strong className="text-emerald-400">
                                {(det.recognition_confidence * 100).toFixed(1)}%
                              </strong></span>
                            )}
                          </div>
                        </div>
                      </div>

                      {/* Action Buttons */}
                      <div className="grid grid-cols-2 gap-1.5 pt-2">
                        <button
                          onClick={() => setSelectedDetection(det)}
                          className="py-1.5 bg-[#1a2030] hover:bg-blue-600 text-slate-300 hover:text-white rounded text-[10px] font-bold uppercase tracking-wider flex items-center justify-center gap-1 border border-[#252d42] hover:border-blue-500 transition-colors"
                        >
                          <Maximize2 className="w-3 h-3" /> Evidence
                        </button>
                        <button
                          onClick={() => {
                            const found = cameras.find(c => c.id === det.camera_id || c.camera_id === det.camera_id || c.camera_id === det.camera_number);
                            if (found) setSelectedCamId(found.id);
                          }}
                          className="py-1.5 bg-[#1a2030] hover:bg-emerald-600 text-slate-300 hover:text-white rounded text-[10px] font-bold uppercase tracking-wider flex items-center justify-center gap-1 border border-[#252d42] hover:border-emerald-500 transition-colors"
                        >
                          <CameraIcon className="w-3 h-3" /> Camera
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── TAB 2: WATCHLIST & ENROLLMENT ── */}
      {activeTab === 'watchlist' && (
        <div className="space-y-6">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
            <div>
              <h3 className="text-sm font-bold text-slate-200 uppercase flex items-center gap-2">
                <Shield className="w-4 h-4 text-emerald-400" />
                Enrolled Face Watchlist Database
              </h3>
              <p className="text-xs text-slate-400">
                128-dimensional facial feature vectors for automated security recognition
              </p>
            </div>

            <button
              onClick={() => {
                setIsEnrollModalOpen(true);
                setEnrollError(null);
                setEnrollSuccess(null);
              }}
              className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-2 shadow-lg shadow-emerald-950/40 transition-colors"
            >
              <Plus className="w-4 h-4" /> Enroll New Individual
            </button>
          </div>

          {loadingWatchlist ? (
            <div className="p-16 text-center text-slate-400 font-mono text-xs">
              <div className="w-8 h-8 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              Loading enrolled watchlist...
            </div>
          ) : watchlist.length === 0 ? (
            <div className="bg-[#111622] p-16 rounded-xl border border-[#252d42] text-center space-y-3">
              <Users className="w-10 h-10 text-slate-600 mx-auto" />
              <p className="font-bold text-slate-400 text-sm uppercase tracking-wider">
                Watchlist is Currently Empty
              </p>
              <p className="text-xs text-slate-500 max-w-md mx-auto">
                Enroll key personnel, VIPs, or persons of interest using photo upload or webcam capture to enable automatic AI identity recognition.
              </p>
              <button
                onClick={() => setIsEnrollModalOpen(true)}
                className="mt-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-bold uppercase"
              >
                Enroll First Subject
              </button>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-5">
              {watchlist.map((person) => {
                const categoryColor =
                  person.category === 'VIP' ? 'bg-purple-500/20 text-purple-400 border-purple-500/40' :
                  person.category === 'SECURITY' ? 'bg-blue-500/20 text-blue-400 border-blue-500/40' :
                  person.category === 'BANNED' ? 'bg-red-500/20 text-red-400 border-red-500/40' :
                  'bg-amber-500/20 text-amber-400 border-amber-500/40';

                return (
                  <div
                    key={person.id}
                    className="bg-[#111622] rounded-xl border border-[#252d42] hover:border-emerald-500/50 transition-all overflow-hidden flex flex-col justify-between shadow-xl"
                  >
                    {/* Photo Box */}
                    <div className="relative aspect-square bg-slate-950 overflow-hidden flex items-center justify-center">
                      {person.photo_url ? (
                        <img
                          src={person.photo_url}
                          alt={person.name}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <UserCheck className="w-16 h-16 text-slate-600" />
                      )}

                      {/* Category Badge */}
                      <div className="absolute top-2 left-2">
                        <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase shadow ${categoryColor}`}>
                          {person.category}
                        </span>
                      </div>

                      {/* Active Status Badge */}
                      <div className="absolute top-2 right-2">
                        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                          person.is_active ? 'bg-emerald-950/90 text-emerald-400 border border-emerald-500/40' : 'bg-slate-900 text-slate-400 border border-slate-700'
                        }`}>
                          {person.is_active ? 'ACTIVE' : 'DISABLED'}
                        </span>
                      </div>
                    </div>

                    {/* Content Details */}
                    <div className="p-4 space-y-3 text-xs flex-1 flex flex-col justify-between">
                      <div className="space-y-1">
                        <h4 className="font-bold text-slate-100 text-sm truncate">{person.name}</h4>
                        <div className="text-[11px] text-slate-400 font-mono">
                          ID: <strong className="text-blue-400">{person.person_id}</strong>
                        </div>
                        {person.notes && (
                          <p className="text-[11px] text-slate-500 line-clamp-2">{person.notes}</p>
                        )}
                        <div className="text-[10px] text-slate-600 pt-1">
                          Enrolled: {new Date(person.created_at).toLocaleDateString()}
                        </div>
                      </div>

                      {/* Actions */}
                      <div className="flex items-center gap-2 pt-2 border-t border-[#252d42]">
                        <button
                          onClick={() => handleToggleWatchlistActive(person.id, person.is_active)}
                          className={`flex-1 py-1.5 rounded text-[11px] font-bold uppercase transition-colors ${
                            person.is_active
                              ? 'bg-slate-800 hover:bg-slate-700 text-slate-300'
                              : 'bg-emerald-600/20 hover:bg-emerald-600 text-emerald-400 hover:text-white'
                          }`}
                        >
                          {person.is_active ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          onClick={() => handleDeleteWatchlist(person.id, person.name)}
                          className="p-1.5 bg-red-950/40 hover:bg-red-600 text-red-400 hover:text-white rounded border border-red-900/50 transition-colors"
                          title="Delete Watchlist Profile"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ── DETAIL MODAL ── */}
      {selectedDetection && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-[#111622] border border-[#252d42] rounded-2xl max-w-3xl w-full overflow-hidden shadow-2xl space-y-0 my-8">
            <div className="bg-[#1a2030] px-6 py-4 border-b border-[#252d42] flex items-center justify-between">
              <div className="flex items-center gap-3">
                <UserCheck className="w-6 h-6 text-blue-400" />
                <div>
                  <h3 className="font-bold text-slate-100 text-base">FACE DETECTION &amp; RECOGNITION EVIDENCE</h3>
                  <p className="text-xs text-slate-400 font-mono">RECORD #{selectedDetection.id?.substring(0, 8)}</p>
                </div>
              </div>
              <button
                onClick={() => setSelectedDetection(null)}
                className="p-2 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="p-6 space-y-6 max-h-[80vh] overflow-y-auto text-xs">
              {/* Image View */}
              <div className="bg-slate-950 rounded-xl border border-[#252d42] overflow-hidden flex items-center justify-center">
                {selectedDetection.snapshot_url || selectedDetection.crop_url ? (
                  <img
                    src={selectedDetection.snapshot_url || selectedDetection.crop_url}
                    alt="Face Evidence"
                    className="w-full h-auto max-h-[420px] object-contain"
                  />
                ) : (
                  <div className="p-16 text-slate-500">Image unavailable</div>
                )}
              </div>

              {/* Metadata Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="bg-[#0a0d14] p-4 rounded-xl border border-[#252d42] space-y-2">
                  <div className="font-bold text-blue-400 border-b border-[#252d42] pb-1">RECOGNITION STATUS</div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Status:</span>
                    <strong className="text-emerald-400 uppercase">{selectedDetection.recognition_status}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Identified Name:</span>
                    <strong className="text-slate-100">{selectedDetection.identity_name || 'UNKNOWN'}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Recognition Match:</span>
                    <strong className="text-emerald-400 font-mono">
                      {(selectedDetection.recognition_confidence * 100).toFixed(1)}%
                    </strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Detection Confidence:</span>
                    <strong className="text-blue-400 font-mono">
                      {(selectedDetection.detection_confidence * 100).toFixed(1)}%
                    </strong>
                  </div>
                </div>

                <div className="bg-[#0a0d14] p-4 rounded-xl border border-[#252d42] space-y-2">
                  <div className="font-bold text-amber-400 border-b border-[#252d42] pb-1">CAMERA &amp; TELEMETRY</div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Camera:</span>
                    <strong className="text-blue-400">{selectedDetection.camera_number || selectedDetection.camera_id}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Location:</span>
                    <strong className="text-slate-200">{selectedDetection.location}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Track ID:</span>
                    <strong className="text-amber-400 font-mono">#F{selectedDetection.track_id || '101'}</strong>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Timestamp:</span>
                    <strong className="text-slate-400 font-mono">{new Date(selectedDetection.timestamp).toLocaleString()}</strong>
                  </div>
                </div>
              </div>
            </div>

            <div className="bg-[#1a2030] px-6 py-3 border-t border-[#252d42] flex justify-end">
              <button
                onClick={() => setSelectedDetection(null)}
                className="px-4 py-2 bg-[#0a0d14] hover:bg-slate-800 text-slate-300 rounded-lg text-xs font-bold uppercase tracking-wider border border-[#252d42]"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── ENROLLMENT MODAL ── */}
      {isEnrollModalOpen && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-md flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-[#111622] border border-[#252d42] rounded-2xl max-w-xl w-full overflow-hidden shadow-2xl space-y-0 my-8">
            <div className="bg-[#1a2030] px-6 py-4 border-b border-[#252d42] flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <Sparkles className="w-5 h-5 text-emerald-400" />
                <h3 className="font-bold text-slate-100 text-base uppercase">Enroll Subject In Watchlist</h3>
              </div>
              <button
                onClick={() => {
                  stopWebcamCapture();
                  setIsEnrollModalOpen(false);
                }}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handleEnrollSubmit} className="p-6 space-y-4 text-xs">
              {enrollError && (
                <div className="bg-red-950/40 border border-red-500/50 p-3 rounded-lg text-red-300 flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0" />
                  <span>{enrollError}</span>
                </div>
              )}

              {enrollSuccess && (
                <div className="bg-emerald-950/40 border border-emerald-500/50 p-3 rounded-lg text-emerald-300 flex items-center gap-2">
                  <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  <span>{enrollSuccess}</span>
                </div>
              )}

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-semibold uppercase text-[11px]">Full Name *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Major Vikram Rathore"
                    value={enrollName}
                    onChange={(e) => setEnrollName(e.target.value)}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-emerald-500 text-xs font-mono"
                  />
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-semibold uppercase text-[11px]">Person ID / Badge # *</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. BSF-8492"
                    value={enrollPersonId}
                    onChange={(e) => setEnrollPersonId(e.target.value)}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-emerald-500 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-slate-400 mb-1 font-semibold uppercase text-[11px]">Category</label>
                  <select
                    value={enrollCategory}
                    onChange={(e) => setEnrollCategory(e.target.value)}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-emerald-500 text-xs"
                  >
                    <option value="WATCHLIST">Watchlist (Person of Interest)</option>
                    <option value="SECURITY">Security / Patrol Personnel</option>
                    <option value="VIP">VIP / Diplomat</option>
                    <option value="BANNED">Banned / Prohibited Individual</option>
                  </select>
                </div>

                <div>
                  <label className="block text-slate-400 mb-1 font-semibold uppercase text-[11px]">Notes (Optional)</label>
                  <input
                    type="text"
                    placeholder="Special instructions or details..."
                    value={enrollNotes}
                    onChange={(e) => setEnrollNotes(e.target.value)}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-emerald-500 text-xs font-mono"
                  />
                </div>
              </div>

              {/* Photo Input / Webcam Capture */}
              <div className="space-y-2 pt-2 border-t border-[#252d42]">
                <label className="block text-slate-300 font-semibold uppercase text-[11px]">
                  Face Image (Photo Upload or Webcam Capture) *
                </label>

                {isCapturingWebcam ? (
                  <div className="space-y-2 bg-[#0a0d14] p-3 rounded-lg border border-[#252d42]">
                    <video ref={videoRef} className="w-full aspect-video rounded object-cover bg-black" autoPlay muted />
                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={capturePhotoFromWebcam}
                        className="flex-1 py-2 bg-emerald-600 hover:bg-emerald-500 text-white font-bold rounded text-xs uppercase flex items-center justify-center gap-1.5"
                      >
                        <CameraIcon className="w-4 h-4" /> Snap Photo
                      </button>
                      <button
                        type="button"
                        onClick={stopWebcamCapture}
                        className="px-3 py-2 bg-slate-800 text-slate-300 rounded text-xs uppercase"
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : enrollImagePreview ? (
                  <div className="relative aspect-video bg-[#0a0d14] rounded-lg overflow-hidden border border-[#252d42] flex items-center justify-center group">
                    <img src={enrollImagePreview} alt="Preview" className="w-full h-full object-contain" />
                    <button
                      type="button"
                      onClick={() => {
                        setEnrollImageFile(null);
                        setEnrollImagePreview(null);
                      }}
                      className="absolute top-2 right-2 p-1.5 bg-red-600 text-white rounded-full shadow"
                      title="Remove Photo"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>
                ) : (
                  <div className="grid grid-cols-2 gap-3">
                    <label className="flex flex-col items-center justify-center p-4 bg-[#0a0d14] hover:bg-[#1a2030] rounded-lg border-2 border-dashed border-[#252d42] hover:border-emerald-500/50 cursor-pointer transition-colors text-center">
                      <Upload className="w-6 h-6 text-slate-400 mb-1" />
                      <span className="text-[11px] text-slate-300 font-bold uppercase">Upload Image</span>
                      <span className="text-[9px] text-slate-500">JPG or PNG (Single Face)</span>
                      <input
                        type="file"
                        accept="image/jpeg,image/png,image/webp"
                        className="hidden"
                        onChange={(e) => {
                          if (e.target.files && e.target.files[0]) {
                            const file = e.target.files[0];
                            setEnrollImageFile(file);
                            setEnrollImagePreview(URL.createObjectURL(file));
                          }
                        }}
                      />
                    </label>

                    <button
                      type="button"
                      onClick={startWebcamCapture}
                      className="flex flex-col items-center justify-center p-4 bg-[#0a0d14] hover:bg-[#1a2030] rounded-lg border-2 border-dashed border-[#252d42] hover:border-emerald-500/50 transition-colors text-center"
                    >
                      <CameraIcon className="w-6 h-6 text-slate-400 mb-1" />
                      <span className="text-[11px] text-slate-300 font-bold uppercase">Use Live Webcam</span>
                      <span className="text-[9px] text-slate-500">Capture face directly</span>
                    </button>
                  </div>
                )}
              </div>

              {/* Hidden canvas for webcam frame extraction */}
              <canvas ref={canvasRef} className="hidden" />

              <div className="pt-3 border-t border-[#252d42] flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => {
                    stopWebcamCapture();
                    setIsEnrollModalOpen(false);
                  }}
                  className="px-4 py-2 bg-[#0a0d14] hover:bg-slate-800 text-slate-300 rounded-lg text-xs font-bold uppercase border border-[#252d42]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={enrolling}
                  className="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-2 shadow-lg shadow-emerald-950/40 transition-colors"
                >
                  {enrolling ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Enrolling &amp; Embedding...
                    </>
                  ) : (
                    <>
                      <Sparkles className="w-3.5 h-3.5" /> Save Watchlist Profile
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
