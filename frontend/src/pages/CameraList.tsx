import React, { useEffect, useState } from 'react';
import { Camera, Plus, CheckCircle2, RefreshCw, X, Play, Square, Trash2, Video, AlertTriangle, Shield, Cpu } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useLocation } from 'react-router-dom';

export const CameraList: React.FC = () => {
  const [cameras, setCameras] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [webcamStatus, setWebcamStatus] = useState<string | null>(null);

  const { token, user } = useAuth();
  const location = useLocation();

  const [form, setForm] = useState({
    camera_id: '',
    name: '',
    description: '',
    location: '',
    protocol: 'WEBCAM', // WEBCAM, RTSP, MP4
    stream_url: '0',
    latitude: 26.9124,
    longitude: 70.9025
  });

  const [loading, setLoading] = useState(true);

  const fetchCameras = async () => {
    try {
      const authToken = token || localStorage.getItem('ibvap_token');
      const headers: any = {};
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/cameras', { headers });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setCameras(data);
        }
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCameras();
    const interval = setInterval(fetchCameras, 3000);
    const query = new URLSearchParams(location.search);
    if (query.get('add') === 'true') {
      setShowModal(true);
    }
    return () => clearInterval(interval);
  }, [token, location]);

  const handleSourceTypeChange = (proto: string) => {
    let defaultUrl = '0';
    if (proto === 'RTSP') defaultUrl = 'rtsp://192.168.1.100:554/live';
    if (proto === 'MP4') defaultUrl = 'storage/demo_videos/border_patrol.mp4';

    setForm(prev => ({
      ...prev,
      protocol: proto,
      stream_url: defaultUrl,
      camera_id: prev.camera_id || `CAM-${Date.now().toString().slice(-4)}`
    }));
    setErrorMessage(null);
    setWebcamStatus(null);
  };

  const handleTestConnection = async () => {
    setTesting(true);
    setTestResult(null);
    setErrorMessage(null);

    try {
      const res = await fetch('/api/cameras/test-connection', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          protocol: form.protocol,
          stream_url: form.stream_url
        })
      });
      if (res.ok) {
        const data = await res.json();
        setTestResult(data);
        if (data.status === 'FAILED') {
          setErrorMessage(data.message);
        }
      }
    } catch (e: any) {
      setErrorMessage('Failed to test connection to stream source.');
    } finally {
      setTesting(false);
    }
  };

  const handleWebcamPermissionAndSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setWebcamStatus(null);

    const cid = form.camera_id || `CAM-${Date.now().toString().slice(-4)}`;
    const camName = form.name || `Webcam ${cid}`;

    if (form.protocol === 'WEBCAM') {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setErrorMessage('NO CAMERA DEVICE FOUND / Browser mediaDevices API not supported.');
        return;
      }

      try {
        setWebcamStatus('Requesting browser camera permission...');
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        // Permission granted! Stop transient preview stream tracks
        stream.getTracks().forEach(track => track.stop());
        setWebcamStatus('Camera permission granted!');
      } catch (err: any) {
        console.error('Webcam permission error:', err);
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          setErrorMessage('CAMERA PERMISSION DENIED. Please grant camera access in browser settings.');
        } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
          setErrorMessage('NO CAMERA DEVICE FOUND. Ensure a camera hardware is connected.');
        } else {
          setErrorMessage(`Webcam Error: ${err.message || 'Unable to access camera.'}`);
        }
        return;
      }
    }

    // Save Camera to backend
    try {
      const createRes = await fetch('/api/cameras', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          ...form,
          camera_id: cid,
          name: camName
        })
      });

      const rawTxt = await createRes.text();

      if (!createRes.ok) {
        let errDetail = `HTTP ${createRes.status}: ${createRes.statusText}`;
        if (rawTxt) {
          try {
            const errData = JSON.parse(rawTxt);
            if (typeof errData.detail === 'string') {
              errDetail = errData.detail;
            } else if (Array.isArray(errData.detail)) {
              errDetail = errData.detail.map((d: any) => `${d.loc ? d.loc.join('.') : ''}: ${d.msg}`).join(', ');
            } else if (errData.message) {
              errDetail = errData.message;
            }
          } catch (jsonErr) {
            errDetail = rawTxt;
          }
        }
        if (createRes.status === 401 || errDetail.includes('Could not validate credentials')) {
          errDetail = 'SESSION EXPIRED: Your login session timed out. Please click the Logout icon (top-right) and log back in as admin.';
        }
        setErrorMessage(errDetail);
        return;
      }

      // Automatically start stream ingestion for created camera
      const startRes = await fetch(`/api/cameras/${cid}/start`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (!startRes.ok) {
        console.warn(`Camera created, but start stream returned status ${startRes.status}`);
      }

      setShowModal(false);
      fetchCameras();
    } catch (err: any) {
      setErrorMessage(err.message || 'Error initializing camera.');
    }
  };

  const getAuthHeaders = () => {
    const authToken = token || localStorage.getItem('ibvap_token');
    const headers: any = {};
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
  };

  const handleStartStream = async (cameraId: string) => {
    try {
      setErrorMessage(null);
      // Update UI state immediately for instant feedback
      setCameras(prev => prev.map(c => c.camera_id === cameraId ? { ...c, status: 'CONNECTING' } : c));
      
      const res = await fetch(`/api/cameras/${cameraId}/start`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
      if (!res.ok) {
        const text = await res.text();
        let errMsg = text || res.statusText;
        try {
          const parsed = JSON.parse(text);
          if (parsed.detail) errMsg = parsed.detail;
        } catch(e) {}

        if (res.status === 401) {
          setErrorMessage('SESSION EXPIRED: Please log out (top-right icon) and log back in.');
        } else {
          setErrorMessage(`Failed to start camera: ${errMsg}`);
        }
        fetchCameras();
      } else {
        fetchCameras();
      }
    } catch (e: any) {
      console.error(e);
      setErrorMessage(e.message || 'Error starting camera.');
    }
  };

  const handleStopStream = async (cameraId: string) => {
    try {
      setErrorMessage(null);
      await fetch(`/api/cameras/${cameraId}/stop`, {
        method: 'POST',
        headers: getAuthHeaders()
      });
      fetchCameras();
    } catch (e: any) {
      console.error(e);
    }
  };

  const handleDeleteCamera = async (cameraId: string) => {
    if (!window.confirm(`Are you sure you want to delete camera ${cameraId}?`)) return;
    try {
      setErrorMessage(null);
      await fetch(`/api/cameras/${cameraId}`, {
        method: 'DELETE',
        headers: getAuthHeaders()
      });
      fetchCameras();
    } catch (e: any) {
      console.error(e);
    }
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header Bar */}
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">CAMERA MANAGEMENT</h2>
          <p className="text-xs text-slate-400 font-mono">Real-time video source ingestion & hardware configuration</p>
        </div>
        {user?.role === 'Administrator' && (
          <button
            onClick={() => {
              setForm({
                camera_id: `CAM-${Date.now().toString().slice(-4)}`,
                name: '',
                description: '',
                location: '',
                protocol: 'WEBCAM',
                stream_url: '0',
                latitude: 26.9124,
                longitude: 70.9025
              });
              setErrorMessage(null);
              setTestResult(null);
              setShowModal(true);
            }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 transition-colors shadow-lg shadow-blue-600/20"
          >
            <Plus className="w-4 h-4" /> ADD CAMERA
          </button>
        )}
      </div>

      {testResult && (
        <div className={`p-4 rounded-xl text-xs font-mono flex items-center justify-between border ${
          testResult.status === 'SUCCESS' ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-300' : 'bg-red-950/40 border-red-500/40 text-red-300'
        }`}>
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-400" />
            <span>{testResult.message} Latency: {testResult.latency_ms}ms</span>
          </div>
          <button onClick={() => setTestResult(null)} className="text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Camera Table */}
      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        {cameras.length === 0 && loading ? (
          <div className="p-12 text-center text-slate-400 font-mono space-y-3">
            <RefreshCw className="w-8 h-8 animate-spin mx-auto text-blue-500 mb-2" />
            <h3 className="text-slate-200 font-bold text-sm uppercase">LOADING SURVEILLANCE CAMERAS...</h3>
          </div>
        ) : cameras.length === 0 ? (
          <div className="p-12 text-center text-slate-400 font-mono space-y-3">
            <Video className="w-10 h-10 text-slate-600 mx-auto" />
            <h3 className="text-slate-200 font-bold text-sm uppercase">NO CAMERAS CONFIGURED</h3>
            <p className="text-xs text-slate-400 max-w-md mx-auto">
              Click <strong className="text-blue-400">+ ADD CAMERA</strong> to configure a local Webcam, RTSP CCTV feed, or MP4 video file.
            </p>
          </div>
        ) : (
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
              <tr>
                <th className="p-3">Camera ID</th>
                <th className="p-3">Name</th>
                <th className="p-3">Location</th>
                <th className="p-3">Protocol</th>
                <th className="p-3">Role</th>
                <th className="p-3">Status</th>
                <th className="p-3">FPS</th>
                <th className="p-3">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#252d42]">
              {cameras.map((c) => (
                <tr key={c.id} className="hover:bg-[#1a2030] transition-colors">
                  <td className="p-3 font-bold text-blue-400">{c.camera_id}</td>
                  <td className="p-3 text-slate-200">{c.name}</td>
                  <td className="p-3 text-slate-400">{c.location}</td>
                  <td className="p-3 text-amber-400 font-bold">{c.protocol}</td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      c.role === 'primary' ? 'bg-blue-500/20 text-blue-400 border border-blue-500/30' : 'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}>
                      {(c.role || 'secondary').toUpperCase()}
                    </span>
                  </td>
                  <td className="p-3">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                      c.status === 'ONLINE' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' :
                      c.status === 'CONNECTING' ? 'bg-amber-500/20 text-amber-400 border border-amber-500/30' :
                      'bg-slate-800 text-slate-400 border border-slate-700'
                    }`}>
                      {c.status}
                    </span>
                  </td>
                  <td className="p-3 text-slate-300">{c.fps}</td>
                  <td className="p-3 flex items-center gap-2">
                    {c.role !== 'primary' && (
                      <button
                        onClick={async () => {
                          await fetch(`/api/cameras/${c.camera_id}/set-primary`, {
                            method: 'POST',
                            headers: getAuthHeaders()
                          });
                          fetchCameras();
                        }}
                        className="px-2 py-1 bg-blue-950/40 hover:bg-blue-600/30 text-blue-300 border border-blue-800/40 rounded text-[10px] font-semibold transition-colors"
                        title="Designate as Primary Camera for Dashboard"
                      >
                        SET PRIMARY
                      </button>
                    )}
                    {c.status === 'ONLINE' || c.status === 'CONNECTING' ? (
                      <button
                        onClick={() => handleStopStream(c.camera_id)}
                        className="px-2.5 py-1 bg-red-950/40 hover:bg-red-600/30 text-red-300 border border-red-800/40 rounded text-[11px] font-semibold transition-colors flex items-center gap-1"
                      >
                        <Square className="w-3 h-3 fill-current" /> STOP CAMERA
                      </button>
                    ) : (
                      <button
                        onClick={() => handleStartStream(c.camera_id)}
                        className="px-2.5 py-1 bg-emerald-950/40 hover:bg-emerald-600/30 text-emerald-300 border border-emerald-800/40 rounded text-[11px] font-semibold transition-colors flex items-center gap-1"
                      >
                        <Play className="w-3 h-3 fill-current" /> START CAMERA
                      </button>
                    )}
                    {user?.role === 'Administrator' && (
                      <button
                        onClick={() => handleDeleteCamera(c.camera_id)}
                        className="p-1 bg-slate-800 hover:bg-red-900/40 text-slate-400 hover:text-red-400 rounded transition-colors"
                        title="Delete Camera"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Add Camera Modal */}
      {showModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#111622] border border-[#252d42] rounded-xl max-w-lg w-full p-6 space-y-5 shadow-2xl relative">
            <div className="flex items-center justify-between border-b border-[#252d42] pb-3">
              <div className="flex items-center gap-2">
                <Camera className="w-5 h-5 text-blue-400" />
                <h3 className="font-bold font-mono text-slate-100 text-sm uppercase">ADD VIDEO SURVEILLANCE SOURCE</h3>
              </div>
              <button
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {errorMessage && (
              <div className="p-3 bg-red-950/50 border border-red-500/50 rounded-lg text-xs font-mono text-red-300 flex items-start gap-2">
                <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                <span>{errorMessage}</span>
              </div>
            )}

            {webcamStatus && (
              <div className="p-3 bg-emerald-950/50 border border-emerald-500/50 rounded-lg text-xs font-mono text-emerald-300 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>{webcamStatus}</span>
              </div>
            )}

            <form onSubmit={handleWebcamPermissionAndSave} className="space-y-4 font-mono text-xs">
              {/* SOURCE TYPE RADIO SELECTOR */}
              <div className="space-y-2">
                <label className="text-slate-300 font-bold block uppercase text-[11px]">SELECT SOURCE TYPE</label>
                <div className="grid grid-cols-3 gap-2">
                  <button
                    type="button"
                    onClick={() => handleSourceTypeChange('WEBCAM')}
                    className={`p-2.5 rounded-lg border text-center font-bold transition-all flex flex-col items-center gap-1.5 ${
                      form.protocol === 'WEBCAM'
                        ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                        : 'bg-[#0a0d14] border-[#252d42] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Cpu className="w-4 h-4" />
                    <span>WEBCAM</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSourceTypeChange('RTSP')}
                    className={`p-2.5 rounded-lg border text-center font-bold transition-all flex flex-col items-center gap-1.5 ${
                      form.protocol === 'RTSP'
                        ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                        : 'bg-[#0a0d14] border-[#252d42] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Video className="w-4 h-4" />
                    <span>RTSP CCTV</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSourceTypeChange('MP4')}
                    className={`p-2.5 rounded-lg border text-center font-bold transition-all flex flex-col items-center gap-1.5 ${
                      form.protocol === 'MP4'
                        ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                        : 'bg-[#0a0d14] border-[#252d42] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <Play className="w-4 h-4" />
                    <span>MP4 VIDEO</span>
                  </button>
                </div>
              </div>

              {/* COMMON FIELDS */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">Camera ID</label>
                  <input
                    type="text"
                    required
                    value={form.camera_id}
                    onChange={(e) => setForm({ ...form, camera_id: e.target.value })}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    placeholder="e.g. CAM-01"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">Camera Name</label>
                  <input
                    type="text"
                    required
                    value={form.name}
                    onChange={(e) => setForm({ ...form, name: e.target.value })}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    placeholder="e.g. Perimeter Gate 4"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-1">Location</label>
                  <input
                    type="text"
                    required
                    value={form.location}
                    onChange={(e) => setForm({ ...form, location: e.target.value })}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    placeholder="e.g. Sector 4 Border Outpost"
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-1">Description</label>
                  <input
                    type="text"
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    placeholder="Optional description"
                  />
                </div>
              </div>

              {/* DYNAMIC SOURCE SPECIFIC FIELDS */}
              {form.protocol === 'WEBCAM' && (
                <div className="p-3 bg-blue-950/30 border border-blue-500/30 rounded-lg space-y-2 text-blue-200 text-[11px]">
                  <div className="font-bold flex items-center gap-1.5 text-blue-400">
                    <Shield className="w-4 h-4" /> BROWSER WEBCAM INTEGRATION
                  </div>
                  <p className="text-slate-400 leading-relaxed">
                    Clicking <strong>START CAMERA & CONNECT</strong> will request real browser webcam permission using `navigator.mediaDevices.getUserMedia`.
                  </p>
                  <div>
                    <label className="text-slate-400 block mb-1">Camera Device Index</label>
                    <input
                      type="text"
                      value={form.stream_url}
                      onChange={(e) => setForm({ ...form, stream_url: e.target.value })}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                      placeholder="0 for default built-in webcam"
                    />
                  </div>
                </div>
              )}

              {form.protocol === 'RTSP' && (
                <div className="space-y-3 p-3 bg-slate-900/50 border border-[#252d42] rounded-lg">
                  <div>
                    <label className="text-slate-400 block mb-1">RTSP Stream URL</label>
                    <input
                      type="text"
                      required
                      value={form.stream_url}
                      onChange={(e) => setForm({ ...form, stream_url: e.target.value })}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                      placeholder="rtsp://admin:secret@192.168.1.100:554/live"
                    />
                  </div>

                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={testing || !form.stream_url}
                    className="w-full py-2 bg-[#1a2030] hover:bg-blue-600/30 text-blue-300 border border-[#252d42] rounded font-bold uppercase transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${testing ? 'animate-spin' : ''}`} />
                    {testing ? 'TESTING RTSP CONNECTION...' : 'TEST RTSP CONNECTION'}
                  </button>
                </div>
              )}

              {form.protocol === 'MP4' && (
                <div className="space-y-2 p-3 bg-slate-900/50 border border-[#252d42] rounded-lg">
                  <label className="text-slate-400 block mb-1">MP4 Video File Path / URL</label>
                  <input
                    type="text"
                    required
                    value={form.stream_url}
                    onChange={(e) => setForm({ ...form, stream_url: e.target.value })}
                    className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                    placeholder="storage/demo_videos/border_patrol.mp4"
                  />
                  <p className="text-[10px] text-slate-500">
                    Provide a path to a local MP4 file. Video frames will feed the real AI inference pipeline.
                  </p>
                </div>
              )}

              {/* ACTION BUTTONS */}
              <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#252d42]">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded font-bold uppercase transition-colors"
                >
                  CANCEL
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded font-bold uppercase tracking-wider transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-600/20"
                >
                  <Play className="w-4 h-4 fill-current" />
                  {form.protocol === 'WEBCAM' ? 'START CAMERA & CONNECT' : form.protocol === 'RTSP' ? 'SAVE & CONNECT RTSP' : 'START VIDEO & SAVE'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
