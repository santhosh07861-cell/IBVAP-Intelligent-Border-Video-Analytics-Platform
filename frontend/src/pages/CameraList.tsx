import React, { useEffect, useState } from 'react';
import { Camera, Plus, CheckCircle2, RefreshCw, X, Play, Square, Trash2, Video, AlertTriangle, Shield, Cpu, Wifi, Search } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useLocation } from 'react-router-dom';

const validateClientUrl = (url: string, proto: string): string | null => {
  if (proto === 'WEBCAM') {
    if (!url || !url.trim() || !/^\d+$/.test(url.trim())) {
      return 'Invalid camera URL. For WEBCAM, enter a valid device index (e.g. 0 or 1).';
    }
    return null;
  }
  if (proto === 'MP4') {
    if (!url || !url.trim()) {
      return 'Invalid video path. Please enter a video path or URL.';
    }
    return null;
  }
  // RTSP / IP CAM
  const trimmed = (url || '').trim();
  if (!trimmed.startsWith('http://') && !trimmed.startsWith('https://') && !trimmed.startsWith('rtsp://')) {
    return 'Invalid camera URL. Enter the complete phone IP address.';
  }
  try {
    const parsed = new URL(trimmed.replace(/^rtsp:\/\//i, 'http://'));
    const host = parsed.hostname;
    if (!host) {
      return 'Invalid camera URL. Enter the complete phone IP address.';
    }
    const parts = host.split('.');
    if (parts.length === 4) {
      for (const part of parts) {
        if (!part || !/^\d+$/.test(part) || Number(part) < 0 || Number(part) > 255) {
          return 'Invalid camera URL. Enter the complete phone IP address.';
        }
      }
    } else {
      return 'Invalid camera URL. Enter the complete phone IP address.';
    }
  } catch (e) {
    return 'Invalid camera URL. Enter the complete phone IP address.';
  }
  return null;
};

export const CameraList: React.FC = () => {
  const [cameras, setCameras] = useState<any[]>([]);
  const [showModal, setShowModal] = useState(false);
  const [testResult, setTestResult] = useState<any>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [discovering, setDiscovering] = useState(false);
  const [discoveredStreams, setDiscoveredStreams] = useState<Array<{ ip: string; port: number; app: string; stream_url: string; label: string }>>([]);
  const [webcamStatus, setWebcamStatus] = useState<string | null>(null);
  const [availableDevices, setAvailableDevices] = useState<Array<{ deviceId: string; label: string; index: number }>>([]);
  const [networkInfo, setNetworkInfo] = useState<{ server_ip: string; subnet: string; sample_phone_url?: string } | null>(null);

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

  const fetchCameras = async (showSpinner = false) => {
    if (showSpinner) setLoading(true);
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

  const enumerateWebcams = async () => {
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
      try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices
          .filter((d) => d.kind === 'videoinput')
          .map((d, idx) => ({
            deviceId: d.deviceId,
            label: d.label || `Camera Device ${idx}`,
            index: idx
          }));
        setAvailableDevices(videoDevices);
      } catch (err) {
        console.warn('Error enumerating video devices:', err);
      }
    }
  };

  const fetchNetworkInfo = async () => {
    if (!token) return;
    try {
      const res = await fetch('/api/cameras/network-info', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setNetworkInfo(data);
      }
    } catch (e) {
      console.warn('Could not fetch server network info:', e);
    }
  };

  useEffect(() => {
    fetchCameras(true);
    fetchNetworkInfo();
    enumerateWebcams();
    const timer = setTimeout(() => setLoading(false), 500);
    const interval = setInterval(() => fetchCameras(false), 5000);
    const query = new URLSearchParams(location.search);
    if (query.get('add') === 'true') {
      setShowModal(true);
    }
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [token, location]);

  const handleDiscoverPhoneCams = async () => {
    setDiscovering(true);
    setErrorMessage(null);
    setDiscoveredStreams([]);
    try {
      const res = await fetch('/api/cameras/discover-phone-cams', {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setDiscoveredStreams(data.discovered || []);
        if (!data.discovered || data.discovered.length === 0) {
          setErrorMessage(`No active phone camera streams found on subnet ${data.subnet || 'your Wi-Fi'}. Make sure your phone's IP Webcam is running with 'Start server' enabled.`);
        } else {
          setWebcamStatus(`Found ${data.discovered.length} active camera stream(s) on Wi-Fi!`);
        }
      }
    } catch (e) {
      setErrorMessage('Failed to scan for phone camera streams.');
    } finally {
      setDiscovering(false);
    }
  };

  const handleSourceTypeChange = (proto: string) => {
    let defaultUrl = '0';
    if (proto === 'RTSP') {
      defaultUrl = '';
    }
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

    let urlToTest = form.stream_url.trim ? form.stream_url.trim() : form.stream_url;
    if (urlToTest.startsWith('https://') && (urlToTest.includes(':8080') || urlToTest.includes(':4747') || urlToTest.includes('192.168.') || urlToTest.includes('10.'))) {
      urlToTest = urlToTest.replace(/^https:\/\//, 'http://');
      setForm(prev => ({ ...prev, stream_url: urlToTest }));
    }
    if ((urlToTest.startsWith('http://') || urlToTest.startsWith('https://')) && !urlToTest.includes('/video') && !urlToTest.includes('/shot.jpg') && !urlToTest.endsWith('.mp4')) {
      urlToTest = urlToTest.replace(/\/$/, '') + '/video';
      setForm(prev => ({ ...prev, stream_url: urlToTest }));
    }

    const valErr = validateClientUrl(urlToTest, form.protocol);
    if (valErr) {
      setErrorMessage(valErr);
      setTesting(false);
      return;
    }

    try {
      const res = await fetch('/api/cameras/test-connection', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          protocol: form.protocol,
          stream_url: urlToTest
        })
      });

      const rawTxt = await res.text();
      let data: any = {};
      try { data = JSON.parse(rawTxt); } catch(e) {}

      if (!res.ok) {
        setErrorMessage(data.detail || data.message || `Failed to connect to stream at ${urlToTest}`);
      } else {
        setTestResult(data);
        if (data.status === 'FAILED') {
          setErrorMessage(data.message);
        }
      }
    } catch (e: any) {
      setErrorMessage('Failed to test connection to stream source. Ensure backend server is running.');
    } finally {
      setTesting(false);
    }
  };

  const [submitting, setSubmitting] = useState(false);

  const handleWebcamPermissionAndSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage(null);
    setWebcamStatus(null);
    setSubmitting(true);

    const cid = form.camera_id || `CAM-${Date.now().toString().slice(-4)}`;
    const camName = form.name || `Camera ${cid}`;

    let urlToSave = form.stream_url.trim();
    if (urlToSave.startsWith('https://') && (urlToSave.includes(':8080') || urlToSave.includes(':4747') || urlToSave.includes('192.168.') || urlToSave.includes('10.'))) {
      urlToSave = urlToSave.replace(/^https:\/\//, 'http://');
    }
    if ((urlToSave.startsWith('http://') || urlToSave.startsWith('https://')) && !urlToSave.includes('/video') && !urlToSave.includes('/shot.jpg') && !urlToSave.endsWith('.mp4')) {
      urlToSave = urlToSave.replace(/\/$/, '') + '/video';
    }

    const valErr = validateClientUrl(urlToSave, form.protocol);
    if (valErr) {
      setErrorMessage(valErr);
      setSubmitting(false);
      return;
    }

    if (form.protocol === 'WEBCAM') {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setErrorMessage('NO CAMERA DEVICE FOUND / Browser mediaDevices API not supported.');
        setSubmitting(false);
        return;
      }

      try {
        setWebcamStatus('Requesting browser camera permission...');
        const stream = await navigator.mediaDevices.getUserMedia({ video: true });
        stream.getTracks().forEach(track => track.stop());
        setWebcamStatus('Camera permission granted!');
        await enumerateWebcams();
      } catch (err: any) {
        console.error('Webcam permission error:', err);
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          setErrorMessage('CAMERA PERMISSION DENIED. Please grant camera access in browser settings.');
        } else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') {
          setErrorMessage('NO CAMERA DEVICE FOUND. Ensure a camera hardware is connected.');
        } else {
          setErrorMessage(`Webcam Error: ${err.message || 'Unable to access camera.'}`);
        }
        setSubmitting(false);
        return;
      }
    }

    // For RTSP / IP CAM: Enforce connection test before saving
    if (form.protocol === 'RTSP') {
      setWebcamStatus('Testing connection to camera stream...');
      try {
        const testRes = await fetch('/api/cameras/test-connection', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${token}`
          },
          body: JSON.stringify({
            protocol: form.protocol,
            stream_url: urlToSave
          })
        });
        const testData = await testRes.json();
        if (!testRes.ok || testData.status === 'FAILED') {
          setErrorMessage(testData.message || 'Cannot connect to stream host. Please verify phone IP and server state.');
          setWebcamStatus(null);
          setSubmitting(false);
          return;
        }
      } catch (testErr) {
        setErrorMessage('Failed to reach stream host. Please check network connection.');
        setWebcamStatus(null);
        setSubmitting(false);
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
          name: camName,
          stream_url: urlToSave
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
        setErrorMessage(errDetail);
        setSubmitting(false);
        return;
      }

      // Automatically start stream ingestion for created camera
      const startRes = await fetch(`/api/cameras/${cid}/start`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${token}` }
      });

      if (!startRes.ok) {
        const rawStart = await startRes.text();
        let startErr = rawStart;
        try {
          const parsed = JSON.parse(rawStart);
          if (parsed.detail) startErr = parsed.detail;
        } catch(jsonErr) {}
        setErrorMessage(`CANNOT CONNECT TO STREAM: ${startErr}`);
        fetchCameras();
        setSubmitting(false);
        return;
      }

      setShowModal(false);
      fetchCameras();
    } catch (err: any) {
      setErrorMessage(err.message || 'Error initializing camera.');
    } finally {
      setSubmitting(false);
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
      setCameras(prev => prev.map(c => (c.camera_id === cameraId || c.id === cameraId) ? { ...c, status: 'CONNECTING' } : c));
      
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
        setErrorMessage(`Failed to start camera ${cameraId}: ${errMsg}`);
      }
      fetchCameras();
    } catch (e: any) {
      console.error(e);
      setErrorMessage(e.message || 'Error starting camera.');
    }
  };

  const handleStopStream = async (cameraId: string) => {
    try {
      setErrorMessage(null);
      setCameras(prev => prev.map(c => (c.camera_id === cameraId || c.id === cameraId) ? { ...c, status: 'STOPPED', fps: 0 } : c));

      const res = await fetch(`/api/cameras/${cameraId}/stop`, {
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
        setErrorMessage(`Failed to stop camera: ${errMsg}`);
      }
      fetchCameras();
    } catch (e: any) {
      console.error(e);
      setErrorMessage(e.message || 'Error stopping camera.');
      fetchCameras();
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
          <p className="text-xs text-slate-400 font-mono">Independent multi-camera video ingestion & hardware stream configuration</p>
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
              enumerateWebcams();
              setShowModal(true);
            }}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 transition-colors shadow-lg shadow-blue-600/20"
          >
            <Plus className="w-4 h-4" /> ADD CAMERA
          </button>
        )}
      </div>

      {/* Error Message Banner */}
      {errorMessage && (
        <div className="p-4 rounded-xl text-xs font-mono flex items-start justify-between border bg-red-950/60 border-red-500/60 text-red-200 shadow-lg shadow-red-950/40">
          <div className="flex items-start gap-2.5">
            <AlertTriangle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
            <div>
              <strong className="block text-red-300 uppercase tracking-wider font-extrabold mb-0.5">CAMERA STATUS NOTIFICATION</strong>
              <span>{errorMessage}</span>
            </div>
          </div>
          <button onClick={() => setErrorMessage(null)} className="text-slate-400 hover:text-white p-1 rounded hover:bg-red-900/40 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

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
              Click <strong className="text-blue-400">+ ADD CAMERA</strong> to configure a Webcam device, RTSP stream, or MP4 video feed.
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
                <tr key={c.id || c.camera_id} className="hover:bg-[#1a2030] transition-colors">
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
                        title="Designate as Primary Camera"
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
              <div className="p-3 bg-red-950/60 border border-red-500/60 rounded-lg text-xs font-mono text-red-300 space-y-2">
                <div className="flex items-start gap-2 font-bold text-red-200">
                  <AlertTriangle className="w-4 h-4 text-red-400 shrink-0 mt-0.5" />
                  <span>{errorMessage}</span>
                </div>
              </div>
            )}

            {webcamStatus && (
              <div className="p-3 bg-emerald-950/50 border border-emerald-500/50 rounded-lg text-xs font-mono text-emerald-300 flex items-center gap-2">
                <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                <span>{webcamStatus}</span>
              </div>
            )}

            {networkInfo && (
              <div className="p-2.5 bg-slate-900/80 border border-blue-500/30 rounded-lg text-[11px] font-mono flex items-center justify-between text-slate-300">
                <div className="flex items-center gap-2">
                  <Wifi className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                  <span>IBVAP Server IP: <strong className="text-emerald-400">{networkInfo.server_ip}</strong> (Subnet: <strong className="text-blue-400">{networkInfo.subnet}</strong>)</span>
                </div>
                <span className="text-[10px] text-slate-400 hidden sm:inline">Phone must be on same Wi-Fi</span>
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
                    className={`p-2 rounded-lg border text-center font-bold transition-all flex flex-col items-center gap-1 ${
                      form.protocol === 'WEBCAM'
                        ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                        : 'bg-[#0a0d14] border-[#252d42] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <Cpu className="w-3.5 h-3.5" />
                      <span>WEBCAM</span>
                    </div>
                    <span className="text-[9px] text-emerald-400 font-normal">Mac Camera (Instant)</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSourceTypeChange('RTSP')}
                    className={`p-2 rounded-lg border text-center font-bold transition-all flex flex-col items-center gap-1 ${
                      form.protocol === 'RTSP'
                        ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                        : 'bg-[#0a0d14] border-[#252d42] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <Video className="w-3.5 h-3.5" />
                      <span>RTSP / IP CAM</span>
                    </div>
                    <span className="text-[9px] text-blue-400 font-normal">Phone & IP Stream</span>
                  </button>

                  <button
                    type="button"
                    onClick={() => handleSourceTypeChange('MP4')}
                    className={`p-2 rounded-lg border text-center font-bold transition-all flex flex-col items-center gap-1 ${
                      form.protocol === 'MP4'
                        ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                        : 'bg-[#0a0d14] border-[#252d42] text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center gap-1.5">
                      <Play className="w-3.5 h-3.5" />
                      <span>MP4 VIDEO</span>
                    </div>
                    <span className="text-[9px] text-slate-400 font-normal">Pre-recorded File</span>
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
                    placeholder="e.g. Main Campus Gate"
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
                    placeholder="e.g. North Gate Entry"
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
                    <Shield className="w-4 h-4" /> WEBCAM DEVICE CONFIGURATION
                  </div>
                  <div>
                    <label className="text-slate-400 block mb-1">Select Available Hardware Device</label>
                    {availableDevices.length > 0 ? (
                      <select
                        value={form.stream_url}
                        onChange={(e) => setForm({ ...form, stream_url: e.target.value })}
                        className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                      >
                        {availableDevices.map((dev) => (
                          <option key={dev.deviceId || dev.index} value={String(dev.index)}>
                            {dev.label} (Index {dev.index})
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={form.stream_url}
                        onChange={(e) => setForm({ ...form, stream_url: e.target.value })}
                        className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                        placeholder="0 for default camera, 1 for secondary USB camera"
                      />
                    )}
                  </div>
                </div>
              )}

              {form.protocol === 'RTSP' && (
                <div className="space-y-3 p-3 bg-slate-900/50 border border-[#252d42] rounded-lg">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <label className="text-slate-400 block">RTSP / Phone IP Camera Stream URL</label>
                      {form.stream_url.startsWith('https://') && (
                        <button
                          type="button"
                          onClick={() => setForm(prev => ({ ...prev, stream_url: prev.stream_url.replace(/^https:\/\//, 'http://') }))}
                          className="text-[10px] text-amber-400 hover:text-amber-300 underline font-semibold"
                        >
                          Convert to http:// (Recommended)
                        </button>
                      )}
                    </div>
                    <input
                      type="text"
                      required
                      value={form.stream_url}
                      onChange={(e) => setForm({ ...form, stream_url: e.target.value })}
                      className="w-full bg-[#0a0d14] border border-[#252d42] rounded p-2 text-slate-200 font-mono focus:border-blue-500 outline-none"
                      placeholder="e.g. http://192.168.1.50:8080/video or rtsp://..."
                    />
                  </div>

                  {/* Subnet Mismatch Live Warning */}
                  {(() => {
                    if (form.protocol !== 'RTSP' || !networkInfo?.subnet || !form.stream_url) return null;
                    const ipMatch = form.stream_url.match(/\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/);
                    if (!ipMatch) return null;
                    const enteredIp = ipMatch[1];
                    const subnetPrefix = networkInfo.subnet.replace(/x$/, '').replace(/\.$/, '');
                    if (subnetPrefix && !enteredIp.startsWith(subnetPrefix)) {
                      return (
                        <div className="p-2.5 bg-rose-950/60 border border-rose-500/60 rounded-lg text-xs font-mono text-rose-300 space-y-1.5">
                          <div className="flex items-center gap-1.5 font-bold text-rose-400">
                            <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
                            <span>⚠️ NETWORK SUBNET MISMATCH DETECTED</span>
                          </div>
                          <p className="text-[11px] text-rose-200">
                            Your phone URL is pointing to <strong className="text-white underline">{enteredIp}</strong>, but this computer is on <strong className="text-white underline">{networkInfo.server_ip}</strong> (Subnet: {networkInfo.subnet}).
                          </p>
                          <p className="text-[10px] text-rose-300/90 leading-relaxed">
                            Your phone is likely using <strong>Mobile Data (4G/5G)</strong>. For video streaming to work:
                            <br />• Connect your phone to the <strong>same Wi-Fi</strong> network as this PC, OR
                            <br />• Turn on <strong>Personal Hotspot</strong> on your phone and connect this PC to it.
                          </p>
                        </div>
                      );
                    }
                    return null;
                  })()}

                  {/* Auto-Discovery & Quick Preset Buttons */}
                  <div className="space-y-2 pt-1">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] text-slate-500 uppercase font-semibold">Templates:</span>
                        <button
                          type="button"
                          onClick={() => setForm(prev => ({ ...prev, stream_url: 'http://192.168.1.100:8080/video' }))}
                          className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-blue-300 rounded text-[10px] border border-blue-500/20"
                        >
                          📱 Phone IP Webcam
                        </button>
                        <button
                          type="button"
                          onClick={() => setForm(prev => ({ ...prev, stream_url: 'http://192.168.1.100:4747/video' }))}
                          className="px-2 py-0.5 bg-slate-800 hover:bg-slate-700 text-purple-300 rounded text-[10px] border border-purple-500/20"
                        >
                          📱 DroidCam
                        </button>
                      </div>

                      <button
                        type="button"
                        onClick={handleDiscoverPhoneCams}
                        disabled={discovering}
                        className="px-2.5 py-1 bg-blue-950/60 hover:bg-blue-900/60 text-blue-300 rounded text-[10px] border border-blue-500/40 flex items-center gap-1 font-bold disabled:opacity-50 transition-colors"
                      >
                        <Search className={`w-3 h-3 ${discovering ? 'animate-spin' : ''}`} />
                        <span>{discovering ? 'SCANNING WI-FI...' : '🔍 AUTO-DISCOVER PHONE ON WI-FI'}</span>
                      </button>
                    </div>

                    {discoveredStreams.length > 0 && (
                      <div className="p-2.5 bg-emerald-950/40 border border-emerald-500/40 rounded-lg space-y-1.5">
                        <div className="text-[11px] font-bold text-emerald-300 flex items-center gap-1.5">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          <span>DISCOVERED ACTIVE PHONE CAMERAS ON WI-FI:</span>
                        </div>
                        <div className="space-y-1">
                          {discoveredStreams.map((s, idx) => (
                            <div key={idx} className="flex items-center justify-between bg-slate-900/90 p-1.5 px-2 rounded border border-emerald-500/20 text-xs">
                              <span className="text-slate-200 font-mono text-[11px]">{s.label} ({s.stream_url})</span>
                              <button
                                type="button"
                                onClick={() => {
                                  setForm(prev => ({ ...prev, stream_url: s.stream_url, name: s.label }));
                                  setErrorMessage(null);
                                }}
                                className="px-2 py-0.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-[10px] font-bold uppercase transition-colors"
                              >
                                Use This Camera
                              </button>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>

                  {form.stream_url.startsWith('https://') && (
                    <div className="p-2 bg-amber-950/40 border border-amber-500/40 rounded text-[11px] text-amber-300 flex items-start gap-1.5">
                      <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-400" />
                      <span>
                        Phone camera apps (Android IP Webcam / DroidCam) stream over unencrypted <strong>http://</strong>, not https://. Click &quot;Convert to http://&quot; above.
                      </span>
                    </div>
                  )}

                  <button
                    type="button"
                    onClick={handleTestConnection}
                    disabled={testing || !form.stream_url}
                    className="w-full py-2 bg-[#1a2030] hover:bg-blue-600/30 text-blue-300 border border-[#252d42] rounded font-bold uppercase transition-colors flex items-center justify-center gap-1.5 disabled:opacity-50"
                  >
                    <RefreshCw className={`w-3.5 h-3.5 ${testing ? 'animate-spin' : ''}`} />
                    {testing ? 'TESTING RTSP / IP CAM CONNECTION...' : 'TEST RTSP / IP CAM CONNECTION'}
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
                    Video frames will feed the real AI detection and security inference pipeline.
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
                  disabled={submitting}
                  className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-blue-800 text-white rounded font-bold uppercase tracking-wider transition-colors flex items-center gap-1.5 shadow-lg shadow-blue-600/20 disabled:opacity-60"
                >
                  {submitting ? (
                    <>
                      <RefreshCw className="w-4 h-4 animate-spin" />
                      <span>CONNECTING STREAM...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" />
                      <span>START & SAVE CAMERA</span>
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
