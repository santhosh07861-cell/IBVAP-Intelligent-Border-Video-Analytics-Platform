import React, { useEffect, useState, useCallback } from 'react';
import {
  Route as RouteIcon, ShieldAlert, Camera, MapPin, Clock,
  RefreshCw, ChevronRight, Eye, X, CheckCircle2, AlertTriangle,
  User, Activity, FileText, Image as ImageIcon, Sparkles, Trash2
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { formatISTDateTime, formatISTTime } from '../utils/timeFormat';

interface MovementEvent {
  id: string;
  chain_id: string;
  sequence_number: number;
  watchlist_person_id: string;
  watchlist_person_name: string;
  camera_id: string;
  camera_number: string;
  camera_name: string;
  location: string;
  latitude: number | null;
  longitude: number | null;
  first_seen_at: string | null;
  last_seen_at: string | null;
  timestamp: string | null;
  date: string;
  time: string;
  confidence: number;
  face_similarity: number;
  track_id: number | null;
  evidence_id: string | null;
  evidence_url: string | null;
  crop_url: string | null;
  created_at: string | null;
}

interface MovementChain {
  id: string;
  watchlist_person_id: string;
  person_name: string;
  person_id: string;
  category: string;
  status: 'ACTIVE' | 'LAST SEEN' | 'NO CURRENT DETECTION' | string;
  current_camera_id: string | null;
  current_camera_number: string | null;
  current_camera_name: string | null;
  current_location: string | null;
  current_latitude: number | null;
  current_longitude: number | null;
  first_detected_at: string | null;
  last_detected_at: string | null;
  total_detections: number;
  photo_url: string | null;
  events_count: number;
  events: MovementEvent[];
}

export const WatchlistMovementView: React.FC = () => {
  const { token } = useAuth();
  const { lastMessage, isConnected } = useWebSocket();

  const [chains, setChains] = useState<MovementChain[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [statusFilter, setStatusFilter] = useState<string>('ALL');
  const [evidenceLoading, setEvidenceLoading] = useState<boolean>(false);
  const [selectedEvidence, setSelectedEvidence] = useState<{
    url: string;
    title: string;
    camera: string;
    cameraId: string;
    location: string;
    time: string;
    similarity: number;
    evidenceId?: string | null;
    eventId?: string;
    error?: string | null;
  } | null>(null);

  const [chainToDelete, setChainToDelete] = useState<MovementChain | null>(null);
  const [isDeletingChain, setIsDeletingChain] = useState<boolean>(false);
  const [showClearAllModal, setShowClearAllModal] = useState<boolean>(false);
  const [isClearingAll, setIsClearingAll] = useState<boolean>(false);
  const [eventToDelete, setEventToDelete] = useState<{ chainId: string; event: MovementEvent } | null>(null);
  const [isDeletingEvent, setIsDeletingEvent] = useState<boolean>(false);

  // Consolidates consecutive same-camera events into a single visit node
  const consolidateSameCameraEvents = (events: MovementEvent[]): MovementEvent[] => {
    if (!events || events.length === 0) return [];
    const consolidated: MovementEvent[] = [];
    for (const ev of events) {
      if (!ev.camera_number && !ev.camera_id) continue;
      const prev = consolidated.length > 0 ? consolidated[consolidated.length - 1] : null;
      const isSameCamera = prev && (
        (ev.camera_id && prev.camera_id === ev.camera_id) ||
        (ev.camera_number && prev.camera_number === ev.camera_number)
      );
      if (isSameCamera && prev) {
        if (ev.last_seen_at && (!prev.last_seen_at || new Date(ev.last_seen_at).getTime() > new Date(prev.last_seen_at).getTime())) {
          prev.last_seen_at = ev.last_seen_at;
        }
        if (ev.first_seen_at && (!prev.first_seen_at || new Date(ev.first_seen_at).getTime() < new Date(prev.first_seen_at).getTime())) {
          prev.first_seen_at = ev.first_seen_at;
        }
        prev.face_similarity = Math.max(prev.face_similarity || 0, ev.face_similarity || 0);
        prev.confidence = Math.max(prev.confidence || 0, ev.confidence || 0);
        if (ev.evidence_url) {
          prev.evidence_url = ev.evidence_url;
          prev.evidence_id = ev.evidence_id || prev.evidence_id;
          prev.id = ev.id || prev.id;
        }
        if (ev.crop_url) {
          prev.crop_url = ev.crop_url;
        }
      } else {
        consolidated.push({ ...ev });
      }
    }
    return consolidated.map((ev, idx) => ({
      ...ev,
      sequence_number: idx + 1
    }));
  };

  const handleViewEvidence = async (event: MovementEvent) => {
    setEvidenceLoading(true);
    const initialUrl = event.evidence_url || `/api/movement/events/${event.id}/evidence/image`;
    const camDisplay = `${event.camera_number || event.camera_id} - ${event.camera_name}`;
    const initialTime = formatISTDateTime(event.last_seen_at || event.timestamp || event.first_seen_at);

    setSelectedEvidence({
      url: initialUrl,
      title: `${event.watchlist_person_name} (${event.camera_number || event.camera_id})`,
      camera: camDisplay,
      cameraId: event.camera_number || event.camera_id,
      location: event.location || 'LOCATION NOT CONFIGURED',
      time: initialTime,
      similarity: event.face_similarity || event.confidence || 0,
      evidenceId: event.evidence_id,
      eventId: event.id,
      error: null
    });

    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const res = await fetch(`/api/movement/events/${event.id}/evidence`, { headers });
      if (res.ok) {
        const meta = await res.json();
        setSelectedEvidence((prev) =>
          prev
            ? {
                ...prev,
                url: meta.image_url || prev.url,
                evidenceId: meta.evidence_id || prev.evidenceId,
                camera: `${meta.camera_number} - ${meta.camera_name}`,
                cameraId: meta.camera_number,
                location: meta.location,
                time: formatISTDateTime(meta.last_seen_at || meta.timestamp || meta.first_seen_at),
                similarity: meta.face_similarity ?? prev.similarity,
                error: null
              }
            : null
        );
      } else {
        const errData = await res.json().catch(() => ({}));
        const reason = errData.detail || 'EVIDENCE NOT AVAILABLE: Surveillance snapshot file not found on storage';
        setSelectedEvidence((prev) => (prev ? { ...prev, error: reason } : null));
      }
    } catch (err: any) {
      const errMsg = err?.message || 'Unable to load evidence. Connection error.';
      setSelectedEvidence((prev) => (prev ? { ...prev, error: errMsg } : null));
    } finally {
      setEvidenceLoading(false);
    }
  };

  const fetchChains = useCallback(async () => {
    try {
      setLoading(true);
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }
      const res = await fetch('/api/movement/chains', { headers });
      if (res.ok) {
        const data: MovementChain[] = await res.json();
        const cleanedChains = data.map((c) => ({
          ...c,
          events: consolidateSameCameraEvents(c.events || [])
        }));
        setChains(cleanedChains);
      } else {
        setChains([]);
      }
    } catch (err) {
      console.error('Error fetching watchlist movement chains:', err);
    } finally {
      setLoading(false);
    }
  }, [token]);

  const handleConfirmDeleteChain = async () => {
    if (!chainToDelete) return;
    setIsDeletingChain(true);
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch(`/api/movement/chains/${chainToDelete.id}`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) {
        setChains((prev) => prev.filter((c) => c.id !== chainToDelete.id));
        setChainToDelete(null);
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || 'Failed to delete movement trajectory');
      }
    } catch (err) {
      console.error('Error deleting movement chain:', err);
      alert('Connection error deleting movement trajectory');
    } finally {
      setIsDeletingChain(false);
    }
  };

  const handleConfirmClearAll = async () => {
    setIsClearingAll(true);
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/movement/chains', {
        method: 'DELETE',
        headers
      });
      if (res.ok) {
        setChains([]);
        setShowClearAllModal(false);
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || 'Failed to clear movement history');
      }
    } catch (err) {
      console.error('Error clearing movement chains:', err);
      alert('Connection error clearing movement history');
    } finally {
      setIsClearingAll(false);
    }
  };

  const handleConfirmDeleteEvent = async () => {
    if (!eventToDelete) return;
    setIsDeletingEvent(true);
    try {
      const headers: Record<string, string> = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch(`/api/movement/events/${eventToDelete.event.id}`, {
        method: 'DELETE',
        headers
      });
      if (res.ok) {
        setChains((prev) => {
          return prev
            .map((c) => {
              if (c.id !== eventToDelete.chainId) return c;
              const remainingEvents = (c.events || []).filter((e) => e.id !== eventToDelete.event.id);
              return {
                ...c,
                events: remainingEvents,
                events_count: remainingEvents.length
              };
            })
            .filter((c) => (c.events || []).length > 0);
        });
        setEventToDelete(null);
      } else {
        const err = await res.json().catch(() => ({}));
        alert(err.detail || 'Failed to delete event');
      }
    } catch (err) {
      console.error('Error deleting event:', err);
      alert('Connection error deleting event');
    } finally {
      setIsDeletingEvent(false);
    }
  };

  useEffect(() => {
    fetchChains();
  }, [fetchChains]);

  // Real-time WebSocket listener for WATCHLIST_MOVEMENT_UPDATE
  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'WATCHLIST_MOVEMENT_UPDATE') return;

    const update = lastMessage as any;
    const chainId = update.chain_id;
    const personId = update.watchlist_person_id;
    const incomingEvent = update.event;
    if (!incomingEvent) return;

    setChains((prevChains) => {
      const existingIndex = prevChains.findIndex(
        (c) => c.id === chainId || c.watchlist_person_id === personId
      );

      if (existingIndex >= 0) {
        const target = prevChains[existingIndex];
        const existingEvents = [...(target.events || [])];
        const eventIndex = existingEvents.findIndex(
          (e) => (incomingEvent.id && e.id === incomingEvent.id) ||
                 (e.camera_id === incomingEvent.camera_id || e.camera_number === incomingEvent.camera_number)
        );

        if (eventIndex >= 0) {
          existingEvents[eventIndex] = { ...existingEvents[eventIndex], ...incomingEvent };
        } else {
          existingEvents.push(incomingEvent);
        }

        const consolidated = consolidateSameCameraEvents(existingEvents);

        const updatedChain: MovementChain = {
          ...target,
          status: update.status || 'ACTIVE',
          current_camera_id: update.current_camera_id,
          current_camera_number: update.current_camera_number,
          current_camera_name: update.current_camera_name,
          current_location: update.current_location || 'LOCATION NOT CONFIGURED',
          current_latitude: update.current_latitude,
          current_longitude: update.current_longitude,
          last_detected_at: update.last_detected_at,
          total_detections: update.total_detections,
          events_count: consolidated.length,
          events: consolidated
        };

        const otherChains = prevChains.filter((_, i) => i !== existingIndex);
        return [updatedChain, ...otherChains];
      } else {
        // New chain detected in real-time
        const consolidated = consolidateSameCameraEvents([incomingEvent]);
        const newChain: MovementChain = {
          id: chainId,
          watchlist_person_id: personId,
          person_name: update.person_name,
          person_id: update.person_id,
          category: update.category,
          status: update.status || 'ACTIVE',
          current_camera_id: update.current_camera_id,
          current_camera_number: update.current_camera_number,
          current_camera_name: update.current_camera_name,
          current_location: update.current_location || 'LOCATION NOT CONFIGURED',
          current_latitude: update.current_latitude,
          current_longitude: update.current_longitude,
          first_detected_at: update.last_detected_at,
          last_detected_at: update.last_detected_at,
          total_detections: update.total_detections || 1,
          photo_url: null,
          events_count: consolidated.length,
          events: consolidated
        };
        return [newChain, ...prevChains];
      }
    });
  }, [lastMessage]);

  const filteredChains = chains.filter((c) => {
    if (statusFilter === 'ALL') return true;
    const s = (c.status || '').toUpperCase().replace('_', ' ');
    return s === statusFilter.toUpperCase().replace('_', ' ');
  });

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 border-b border-[#252d42] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-red-950/50 border border-red-800/40 text-red-400">
              <RouteIcon className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-wide text-white uppercase flex items-center gap-2">
                Watchlist Movement Tracking
                <span className="text-[11px] font-mono font-normal px-2 py-0.5 rounded bg-blue-900/40 border border-blue-700/50 text-blue-300">
                  REAL CROSS-CAMERA CHAIN
                </span>
              </h1>
              <p className="text-xs text-slate-400">
                Authoritative cross-camera chronological surveillance trajectories for confirmed watchlist persons
              </p>
            </div>
          </div>
        </div>

        {/* Action / Status Controls */}
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-[#111622] border border-[#252d42] text-xs font-mono">
            <span
              className={`w-2 h-2 rounded-full ${
                isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'
              }`}
            />
            <span className={isConnected ? 'text-emerald-400 font-medium' : 'text-red-400 font-medium'}>
              {isConnected ? 'LIVE WEBSOCKET' : 'CONNECTING...'}
            </span>
          </div>

          <button
            onClick={fetchChains}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-semibold shadow-sm transition-all disabled:opacity-50 cursor-pointer"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>

          {chains.length > 0 && (
            <button
              onClick={() => setShowClearAllModal(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-red-950/40 hover:bg-red-600/80 text-red-300 hover:text-white border border-red-700/50 hover:border-red-500 text-xs font-semibold shadow-sm transition-all cursor-pointer"
              title="Clear all movement trajectories"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Clear All
            </button>
          )}
        </div>
      </div>

      {/* Filter Tabs */}
      <div className="flex items-center gap-2">
        {(['ALL', 'ACTIVE', 'LAST SEEN'] as const).map((filter) => (
          <button
            key={filter}
            onClick={() => setStatusFilter(filter)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              statusFilter === filter
                ? 'bg-blue-600/20 text-blue-400 border border-blue-500/40 font-semibold'
                : 'text-slate-400 hover:text-slate-200 hover:bg-[#1a2030] border border-transparent'
            }`}
          >
            {filter} ({filter === 'ALL' ? chains.length : chains.filter((c) => (c.status || '').toUpperCase().replace('_', ' ') === filter).length})
          </button>
        ))}
      </div>

      {/* Empty State — NO RANDOM / MOCK / DEFAULT DATA */}
      {filteredChains.length === 0 && !loading && (
        <div className="p-12 rounded-xl bg-[#111622] border border-[#252d42] text-center max-w-2xl mx-auto space-y-3">
          <div className="w-12 h-12 rounded-full bg-slate-800/80 border border-slate-700 flex items-center justify-center mx-auto text-slate-400">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <h2 className="text-sm font-bold tracking-wider text-slate-200 uppercase font-mono">
            NO CONFIRMED MOVEMENT DETECTED
          </h2>
          <p className="text-xs text-slate-400 leading-relaxed">
            No confirmed watchlist persons have been identified across live surveillance streams yet.
            When a verified watchlist match occurs on live cameras, their independent cross-camera movement
            chain will appear here in real-time with authoritative camera IDs, locations, and evidence snapshots.
          </p>
        </div>
      )}

      {/* Loading Skeleton */}
      {loading && chains.length === 0 && (
        <div className="space-y-4">
          {[1, 2].map((i) => (
            <div key={i} className="p-6 rounded-xl bg-[#111622] border border-[#252d42] animate-pulse space-y-4">
              <div className="h-6 bg-slate-800 rounded w-1/3" />
              <div className="h-24 bg-slate-800/60 rounded" />
            </div>
          ))}
        </div>
      )}

      {/* Watchlist Person Movement Chains */}
      <div className="space-y-6">
        {filteredChains.map((chain) => {
          const isActive = chain.status === 'ACTIVE';
          return (
            <div
              key={chain.id}
              className={`rounded-xl bg-[#111622] border transition-all duration-300 overflow-hidden ${
                isActive
                  ? 'border-emerald-500/40 shadow-[0_0_20px_rgba(16,185,129,0.08)]'
                  : 'border-[#252d42] hover:border-slate-700'
              }`}
            >
              {/* Person Summary Header */}
              <div className="p-5 bg-[#141a29] border-b border-[#252d42] flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div className="flex items-center gap-4">
                  {/* Photo or Avatar */}
                  <div className="w-14 h-14 rounded-lg bg-[#0a0d14] border border-[#252d42] overflow-hidden flex items-center justify-center shrink-0">
                    {chain.photo_url ? (
                      <img
                        src={chain.photo_url}
                        alt={chain.person_name}
                        className="w-full h-full object-cover"
                      />
                    ) : (
                      <User className="w-7 h-7 text-slate-500" />
                    )}
                  </div>

                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-bold text-white tracking-wide">
                        {chain.person_name}
                      </h3>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300 font-semibold">
                        {chain.person_id}
                      </span>
                      <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-red-950/60 border border-red-700/50 text-red-300 font-semibold">
                        {chain.category}
                      </span>
                    </div>

                    <div className="text-xs text-slate-400 mt-1 flex flex-wrap items-center gap-3 font-mono">
                      <span>
                        DB ID: <span className="text-slate-300">{chain.watchlist_person_id.substring(0, 8)}...</span>
                      </span>
                      <span>•</span>
                      <span>
                        Total Detections: <span className="text-white font-semibold">{chain.total_detections}</span>
                      </span>
                      <span>•</span>
                      <span>
                        Last Detected: <span className="text-slate-200 font-medium">{formatISTDateTime(chain.last_detected_at)}</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Status & Current Location Badge */}
                <div className="flex flex-col items-start md:items-end gap-1.5">
                  <div className="flex items-center gap-2">
                    <span
                      className={`text-xs font-mono font-bold px-2.5 py-1 rounded-full flex items-center gap-1.5 ${
                        isActive
                          ? 'bg-emerald-950/70 border border-emerald-500/50 text-emerald-400 animate-pulse'
                          : 'bg-amber-950/60 border border-amber-700/50 text-amber-300'
                      }`}
                    >
                      <Activity className="w-3.5 h-3.5" />
                      STATUS: {chain.status}
                    </span>

                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setChainToDelete(chain);
                      }}
                      className="flex items-center gap-1.5 px-2.5 py-1 bg-red-950/40 hover:bg-red-600 text-red-400 hover:text-white rounded-lg border border-red-500/30 hover:border-red-500 transition-colors text-xs font-semibold cursor-pointer shadow-sm"
                      title={`Delete movement trajectory for ${chain.person_name}`}
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                      DELETE
                    </button>
                  </div>

                  <div className="text-xs text-slate-400 font-mono flex items-center gap-1.5">
                    <Camera className="w-3.5 h-3.5 text-blue-400" />
                    <span>
                      Current/Last: <strong className="text-slate-200">{chain.current_camera_number || '—'}</strong>
                    </span>
                    <span className="text-slate-600">|</span>
                    <MapPin className="w-3.5 h-3.5 text-amber-400" />
                    <span className="text-slate-300">{chain.current_location || 'LOCATION NOT CONFIGURED'}</span>
                  </div>
                </div>
              </div>

              {/* Movement Chain Step Flow */}
              <div className="p-5 space-y-4">
                <div className="flex items-center justify-between text-xs text-slate-400 font-mono border-b border-[#1f2638] pb-2">
                  <span className="font-semibold text-slate-300 flex items-center gap-1.5">
                    <RouteIcon className="w-4 h-4 text-blue-400" />
                    CHRONOLOGICAL CROSS-CAMERA TRAJECTORY ({chain.events?.length || 0} CAMERA {chain.events?.length === 1 ? 'VISIT' : 'VISITS'})
                  </span>
                  <span className="text-[11px] text-slate-500">
                    Source: Persistent Database Sequence
                  </span>
                </div>

                {/* Trajectory Summary Path Ribbon: CAM-01 → CAM-07 → CAM-03 */}
                {chain.events && chain.events.length > 0 && (
                  <div className="p-3 rounded-lg bg-[#070a10] border border-[#1f2638] flex items-center flex-wrap gap-2">
                    <span className="text-[11px] font-mono font-bold text-slate-400 uppercase tracking-wider flex items-center gap-1.5 shrink-0">
                      <RouteIcon className="w-3.5 h-3.5 text-blue-400" />
                      CAMERA TRAJECTORY:
                    </span>
                    {chain.events.map((ev, i) => (
                      <React.Fragment key={ev.id || i}>
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-md bg-[#111622] border border-[#2b354d]">
                          <Camera className="w-3.5 h-3.5 text-blue-400 shrink-0" />
                          <div className="flex flex-col">
                            <span className="font-mono font-bold text-xs text-white leading-tight">
                              {ev.camera_number || ev.camera_id}
                            </span>
                            <span className="text-[10px] font-mono text-slate-400 leading-tight">
                              {ev.camera_name ? `${ev.camera_name} • ` : ''}{ev.location || 'LOCATION NOT CONFIGURED'}
                            </span>
                          </div>
                        </div>
                        {i < chain.events.length - 1 && (
                          <ChevronRight className="w-4 h-4 text-blue-400 shrink-0" />
                        )}
                      </React.Fragment>
                    ))}
                  </div>
                )}

                {/* Horizontal / Vertical Nodes Flow */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4 pt-2">
                  {(chain.events || []).map((event, idx) => {
                    const isLatest = idx === (chain.events.length - 1);
                    return (
                      <div
                        key={event.id || idx}
                        className={`relative rounded-lg p-4 bg-[#0d121c] border flex flex-col justify-between transition-all ${
                          isLatest
                            ? 'border-blue-500/50 shadow-md ring-1 ring-blue-500/20'
                            : 'border-[#252d42] hover:border-slate-600'
                        }`}
                      >
                        {/* Node Number & Camera */}
                        <div>
                          <div className="flex items-center justify-between gap-2 mb-2.5">
                            <div className="flex items-center gap-2">
                              <div className="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center shrink-0 text-blue-400">
                                <Camera className="w-4 h-4" />
                              </div>
                              <div>
                                <span className="text-[10px] font-mono font-bold tracking-wider text-slate-400 block uppercase">
                                  CAMERA ID
                                </span>
                                <span className="font-mono font-bold text-sm text-white tracking-wide">
                                  {event.camera_number || event.camera_id}
                                </span>
                              </div>
                            </div>

                            <div className="flex items-center gap-1.5">
                              <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-slate-800 border border-slate-700 text-slate-300">
                                EVENT {idx + 1}
                              </span>
                              {isLatest && (
                                <span
                                  className={`text-[9px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${
                                    isActive
                                      ? 'bg-emerald-950 border-emerald-600 text-emerald-400'
                                      : 'bg-amber-950 border-amber-600 text-amber-300'
                                  }`}
                                >
                                  {isActive ? 'CURRENT' : 'LAST SEEN'}
                                </span>
                              )}
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setEventToDelete({ chainId: chain.id, event });
                                }}
                                className="p-1 hover:bg-red-950/40 text-slate-500 hover:text-red-400 rounded transition-colors cursor-pointer"
                                title="Delete this observation event node"
                              >
                                <Trash2 className="w-3 h-3" />
                              </button>
                            </div>
                          </div>

                          <p className="text-xs text-slate-300 font-semibold truncate mb-1">
                            {event.camera_name}
                          </p>

                          {/* Location */}
                          <div className="flex items-center gap-1.5 text-xs text-slate-300 mb-2">
                            <MapPin className="w-3.5 h-3.5 text-amber-400 shrink-0" />
                            <span className="truncate font-mono">
                              {event.location || 'LOCATION NOT CONFIGURED'}
                            </span>
                          </div>

                          {/* Timestamps */}
                          <div className="p-2 rounded bg-[#070a10] border border-[#1f2638] text-[11px] font-mono space-y-1 mb-3">
                            <div className="flex justify-between text-slate-400">
                              <span>First Seen:</span>
                              <span className="text-slate-200 font-medium">
                                {formatISTTime(event.first_seen_at || event.timestamp)}
                              </span>
                            </div>
                            <div className="flex justify-between text-slate-400">
                              <span>Last Seen:</span>
                              <span className="text-slate-200 font-medium">
                                {formatISTTime(event.last_seen_at || event.timestamp)}
                              </span>
                            </div>
                            <div className="flex justify-between text-slate-500 text-[10px] pt-0.5 border-t border-slate-800">
                              <span>Date:</span>
                              <span className="text-slate-400">
                                {event.date || (event.timestamp ? event.timestamp.substring(0, 10) : '—')}
                              </span>
                            </div>
                          </div>

                          {/* AI Match Metrics */}
                          <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 mb-3 px-1">
                            <span>Match Similarity:</span>
                            <span className="text-emerald-400 font-bold">
                              {((event.face_similarity || event.confidence || 0) * 100).toFixed(1)}%
                            </span>
                          </div>
                        </div>

                        {/* Evidence Snapshot / Thumbnail */}
                        <div>
                          <button
                            onClick={() => handleViewEvidence(event)}
                            className="w-full flex items-center justify-center gap-2 py-2 px-3 rounded-lg bg-blue-950/40 hover:bg-blue-900/60 border border-blue-800/40 text-blue-300 text-xs font-medium transition-all group shadow-sm hover:border-blue-700"
                          >
                            <Eye className="w-3.5 h-3.5 text-blue-400 group-hover:scale-110 transition-transform" />
                            <span>View Real Evidence</span>
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* High-Resolution Evidence Modal */}
      {selectedEvidence && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-[#111622] border border-[#252d42] rounded-xl max-w-3xl w-full overflow-hidden shadow-2xl animate-in fade-in zoom-in-95 duration-200">
            {/* Modal Header */}
            <div className="p-4 bg-[#161c2c] border-b border-[#252d42] flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ImageIcon className="w-5 h-5 text-blue-400" />
                <h3 className="font-bold text-white text-sm">
                  CONFIRMED SURVEILLANCE EVIDENCE — {selectedEvidence.title}
                </h3>
              </div>
              <button
                onClick={() => setSelectedEvidence(null)}
                className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body with Image or Error */}
            <div className="p-4 space-y-4">
              {evidenceLoading ? (
                <div className="h-64 bg-[#070a10] rounded-lg border border-[#252d42] flex flex-col items-center justify-center gap-3">
                  <RefreshCw className="w-8 h-8 text-blue-400 animate-spin" />
                  <span className="text-xs font-mono text-slate-400 tracking-wider">
                    VERIFYING SURVEILLANCE EVIDENCE FILE...
                  </span>
                </div>
              ) : selectedEvidence.error ? (
                <div className="py-12 px-6 bg-[#070a10] rounded-lg border border-amber-500/30 flex flex-col items-center justify-center text-center">
                  <AlertTriangle className="w-10 h-10 text-amber-400 mb-3" />
                  <h4 className="text-amber-300 font-mono font-bold text-sm tracking-wider uppercase mb-1">
                    EVIDENCE NOT AVAILABLE
                  </h4>
                  <p className="text-slate-400 font-mono text-xs max-w-md">
                    {selectedEvidence.error}
                  </p>
                </div>
              ) : (
                <div className="max-h-[60vh] bg-black rounded-lg overflow-hidden flex items-center justify-center border border-[#252d42] relative">
                  <img
                    src={selectedEvidence.url}
                    alt="Evidence Snapshot"
                    className="max-h-[58vh] w-auto object-contain"
                    onError={() => {
                      setSelectedEvidence((prev) =>
                        prev
                          ? {
                              ...prev,
                              error:
                                'EVIDENCE NOT AVAILABLE: Physical snapshot image could not be loaded from storage.'
                            }
                          : null
                      );
                    }}
                  />
                </div>
              )}

              {/* Authoritative Metadata Bar */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 p-3 rounded-lg bg-[#0a0d14] border border-[#252d42] text-xs font-mono">
                <div>
                  <div className="text-slate-500 text-[10px]">CAMERA</div>
                  <div className="text-white font-semibold">{selectedEvidence.camera}</div>
                </div>
                <div>
                  <div className="text-slate-500 text-[10px]">LOCATION</div>
                  <div className="text-white font-semibold">{selectedEvidence.location}</div>
                </div>
                <div>
                  <div className="text-slate-500 text-[10px]">AUTHORITATIVE TIME</div>
                  <div className="text-slate-200 font-semibold">{selectedEvidence.time}</div>
                </div>
                <div>
                  <div className="text-slate-500 text-[10px]">MATCH SIMILARITY</div>
                  <div className="text-emerald-400 font-bold">
                    {(selectedEvidence.similarity * 100).toFixed(1)}%
                  </div>
                </div>
              </div>
            </div>

            {/* Modal Footer */}
            <div className="p-3 bg-[#0d121c] border-t border-[#252d42] flex justify-between items-center text-xs text-slate-400 font-mono">
              <span>EVIDENCE REF: {selectedEvidence.evidenceId || `EVENT-${selectedEvidence.eventId?.substring(0, 8) || 'STORED'}`}</span>
              <button
                onClick={() => setSelectedEvidence(null)}
                className="px-4 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 font-medium transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Watchlist Movement Chain Delete Confirmation Modal ── */}
      {chainToDelete && (
        <div className="fixed inset-0 z-[110] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE MOVEMENT TRAJECTORY?</h3>
                  <p className="text-[11px] text-red-400/80 font-mono">CONFIRMED PERSON TRACK RECORD</p>
                </div>
              </div>
              <button
                onClick={() => setChainToDelete(null)}
                disabled={isDeletingChain}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300 font-sans leading-relaxed">
                Are you sure you want to permanently delete the movement trajectory history for this confirmed watchlist person? All chronological camera transitions and timestamps will be removed.
              </p>

              <div className="bg-[#0a0d14] p-3.5 rounded-xl border border-[#252d42] space-y-2 text-[11px]">
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Subject:</span>
                  <strong className="text-red-300 uppercase font-bold">
                    {chainToDelete.person_name}
                  </strong>
                </div>
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Person ID / Category:</span>
                  <span className="text-slate-200 font-mono">{chainToDelete.person_id} • {chainToDelete.category}</span>
                </div>
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Camera Visits:</span>
                  <strong className="text-white">{chainToDelete.events?.length || 0} visits ({chainToDelete.total_detections} detections)</strong>
                </div>
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Last Camera:</span>
                  <span className="text-slate-200 font-mono">{chainToDelete.current_camera_number || '—'} ({chainToDelete.current_location || 'NO LOCATION'})</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Last Seen:</span>
                  <span className="text-slate-200 font-mono">{formatISTDateTime(chainToDelete.last_detected_at)}</span>
                </div>
              </div>

              <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
                ℹ Note: The enrolled watchlist subject profile is preserved. Only the movement trajectory history is deleted.
              </div>
            </div>

            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setChainToDelete(null)}
                disabled={isDeletingChain}
                className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDeleteChain}
                disabled={isDeletingChain}
                className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-red-950/50 transition-all disabled:opacity-50 cursor-pointer"
              >
                {isDeletingChain ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete Trajectory
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Clear All Movement Chains Modal ── */}
      {showClearAllModal && (
        <div className="fixed inset-0 z-[110] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/50 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/60 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/40">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">CLEAR ALL MOVEMENT TRACKS?</h3>
                  <p className="text-[11px] text-red-400 font-mono">PURGE MOVEMENT TRAJECTORIES</p>
                </div>
              </div>
              <button
                onClick={() => setShowClearAllModal(false)}
                disabled={isClearingAll}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300 font-sans leading-relaxed">
                Are you sure you want to clear all active and historical cross-camera movement chains? All sequential surveillance trajectories for confirmed watchlist persons will be purged from the timeline.
              </p>

              <div className="bg-[#0a0d14] p-3.5 rounded-xl border border-[#252d42] space-y-2 text-[11px]">
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Total Tracked Persons:</span>
                  <strong className="text-red-400 font-bold">{chains.length}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Total Camera Observation Nodes:</span>
                  <strong className="text-white font-bold">
                    {chains.reduce((sum, c) => sum + (c.events?.length || 0), 0)}
                  </strong>
                </div>
              </div>

              <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
                ℹ Note: This action only clears the surveillance movement chains. Registered watchlist persons and cameras remain untouched.
              </div>
            </div>

            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setShowClearAllModal(false)}
                disabled={isClearingAll}
                className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmClearAll}
                disabled={isClearingAll}
                className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-red-950/50 transition-all disabled:opacity-50 cursor-pointer"
              >
                {isClearingAll ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Clearing All...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    Purge All Tracks
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Movement Observation Event Node Delete Modal ── */}
      {eventToDelete && (
        <div className="fixed inset-0 z-[110] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE OBSERVATION EVENT?</h3>
                  <p className="text-[11px] text-red-400/80 font-mono">SINGLE CAMERA VISIT NODE</p>
                </div>
              </div>
              <button
                onClick={() => setEventToDelete(null)}
                disabled={isDeletingEvent}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42] cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300 font-sans leading-relaxed">
                Are you sure you want to delete this observation event node from the movement sequence?
              </p>

              <div className="bg-[#0a0d14] p-3.5 rounded-xl border border-[#252d42] space-y-2 text-[11px]">
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Camera:</span>
                  <strong className="text-white">
                    {eventToDelete.event.camera_number || eventToDelete.event.camera_id} - {eventToDelete.event.camera_name}
                  </strong>
                </div>
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Location:</span>
                  <span className="text-slate-200">{eventToDelete.event.location || 'LOCATION NOT CONFIGURED'}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">First Seen / Time:</span>
                  <span className="text-slate-200 font-mono">
                    {formatISTDateTime(eventToDelete.event.first_seen_at || eventToDelete.event.timestamp)}
                  </span>
                </div>
              </div>
            </div>

            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setEventToDelete(null)}
                disabled={isDeletingEvent}
                className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors disabled:opacity-50 cursor-pointer"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDeleteEvent}
                disabled={isDeletingEvent}
                className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-red-950/50 transition-all disabled:opacity-50 cursor-pointer"
              >
                {isDeletingEvent ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    Deleting...
                  </>
                ) : (
                  <>
                    <Trash2 className="w-3.5 h-3.5" />
                    Delete Event
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
