import React, { useEffect, useState, useCallback } from 'react';
import {
  Camera, ShieldAlert, Search, LayoutGrid, TableProperties,
  Eye, ArrowUpDown, RefreshCw, Cpu, AlertTriangle, X,
  ChevronLeft, ChevronRight, Download, Maximize2, Info
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';

const API_BASE = 'http://localhost:8000';

// ---- Severity badge helper ----
function SeverityBadge({ severity }: { severity: string }) {
  const cls =
    severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border-red-500/40' :
    severity === 'HIGH'     ? 'bg-amber-500/20 text-amber-400 border-amber-500/40' :
    severity === 'MEDIUM'   ? 'bg-orange-500/20 text-orange-400 border-orange-500/40' :
    severity === 'LOW'      ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/40' :
    'bg-blue-500/20 text-blue-400 border-blue-500/40';
  return (
    <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase ${cls}`}>
      {severity}
    </span>
  );
}

// ---- Lightbox ----
function ImageLightbox({
  src, alt, onClose, onPrev, onNext, hasPrev, hasNext
}: {
  src: string; alt: string; onClose: () => void;
  onPrev: () => void; onNext: () => void;
  hasPrev: boolean; hasNext: boolean;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
      if (e.key === 'ArrowLeft' && hasPrev) onPrev();
      if (e.key === 'ArrowRight' && hasNext) onNext();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose, onPrev, onNext, hasPrev, hasNext]);

  return (
    <div
      className="fixed inset-0 z-[100] bg-black/95 flex items-center justify-center"
      onClick={onClose}
    >
      <button
        onClick={onClose}
        className="absolute top-4 right-4 p-2 bg-slate-800 hover:bg-slate-700 rounded-full text-white"
      >
        <X className="w-5 h-5" />
      </button>
      {hasPrev && (
        <button
          onClick={(e) => { e.stopPropagation(); onPrev(); }}
          className="absolute left-4 p-3 bg-slate-800 hover:bg-slate-700 rounded-full text-white"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
      )}
      {hasNext && (
        <button
          onClick={(e) => { e.stopPropagation(); onNext(); }}
          className="absolute right-4 p-3 bg-slate-800 hover:bg-slate-700 rounded-full text-white"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      )}
      <img
        src={src}
        alt={alt}
        className="max-w-[90vw] max-h-[90vh] object-contain rounded-lg shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      />
    </div>
  );
}

// ---- Main Page ----
export const EvidenceGallery: React.FC = () => {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [apiError, setApiError] = useState<string | null>(null);
  const [totalCount, setTotalCount] = useState(0);
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
  const [selectedItem, setSelectedItem] = useState<any | null>(null);
  const [lightboxIdx, setLightboxIdx] = useState<number | null>(null);

  // Filters & Search
  const [search, setSearch] = useState('');
  const [objectFilter, setObjectFilter] = useState('all');
  const [cameraFilter, setCameraFilter] = useState('all');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [eventFilter, setEventFilter] = useState('all');
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');

  const { token } = useAuth();
  const { lastMessage } = useWebSocket();

  const fetchEvidence = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      const authToken = token || localStorage.getItem('ibvap_token');
      const headers: Record<string, string> = {};
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const params = new URLSearchParams();
      if (objectFilter !== 'all') params.append('object_class', objectFilter);
      if (cameraFilter !== 'all') params.append('camera_id', cameraFilter);
      if (severityFilter !== 'all') params.append('severity', severityFilter);
      if (eventFilter !== 'all') params.append('event_type', eventFilter);
      if (search) params.append('search', search);
      params.append('limit', '100');

      const res = await fetch(`/api/evidence?${params.toString()}`, { headers });

      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText);
        throw new Error(`API returned ${res.status}: ${errText.slice(0, 200)}`);
      }

      const data = await res.json();
      const fetched = data.items || [];
      setItems(fetched);
      setTotalCount(data.total ?? fetched.length);
      console.log(`[EVIDENCE] API returned ${fetched.length} records (total=${data.total})`);
    } catch (err: any) {
      console.error('[EVIDENCE] Fetch failed:', err);
      setApiError(err?.message || 'Failed to load evidence from backend');
    } finally {
      setLoading(false);
    }
  }, [token, objectFilter, cameraFilter, severityFilter, eventFilter, search]);

  // Initial load + re-fetch on filter change
  useEffect(() => {
    fetchEvidence();
  }, [fetchEvidence]);

  // Real-time: prepend new evidence from WebSocket
  useEffect(() => {
    if (lastMessage && lastMessage.type === 'EVIDENCE_NEW') {
      const ws = lastMessage as any;
      const newEv = ws.evidence || {
        id: ws.evidence_id,
        camera_id: ws.camera_id,
        camera_number: ws.camera_number,
        camera_name: ws.camera_name,
        location: ws.location,
        object_class: ws.object_class,
        confidence: ws.confidence,
        track_id: ws.track_id,
        event_type: ws.event_type || 'DETECTION',
        risk_score: ws.risk_score ?? 0.0,
        severity: ws.severity || 'INFO',
        captured_at: ws.timestamp || new Date().toISOString(),
        file_url: ws.file_url,
        evidence_url: ws.file_url,
      };
      if (newEv.id) {
        setItems((prev) => [newEv, ...prev.filter((x) => x.id !== newEv.id)]);
        setTotalCount((c) => c + 1);
        console.log('[EVIDENCE] Real-time EVIDENCE_NEW prepended:', newEv.id);
      }
    }
  }, [lastMessage]);

  const sortedItems = [...items].sort((a, b) => {
    const tA = new Date(a.captured_at || 0).getTime();
    const tB = new Date(b.captured_at || 0).getTime();
    return sortOrder === 'newest' ? tB - tA : tA - tB;
  });

  // Derive unique camera list for camera filter
  const cameraOptions = Array.from(
    new Set(items.map((it) => it.camera_number || it.camera_id).filter(Boolean))
  );

  // Image URL resolver — prefer /api/evidence/{id}/image, fall back to file_url
  const resolveImageUrl = (item: any): string | null => {
    if (item.id && item.file_url) {
      // If the file_url already starts with /api/evidence, use as-is
      if (item.file_url.startsWith('/api/evidence')) return item.file_url;
      // Otherwise use the /api/evidence/{id}/image endpoint
      return `/api/evidence/${item.id}/image`;
    }
    return item.file_url || item.evidence_url || null;
  };

  return (
    <div className="p-6 space-y-6 font-mono">
      {/* ── Top Header ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-400" />
            AI Detection History &amp; Evidence Gallery
          </h2>
          <p className="text-xs text-slate-400 mt-0.5">
            Real AI-detected objects &amp; automatic evidence snapshots ·{' '}
            <span className="text-emerald-400 font-bold">{totalCount}</span> records
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchEvidence}
            disabled={loading}
            className="px-3 py-2 bg-[#1a2030] hover:bg-[#252d42] text-slate-300 rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 border border-[#252d42] transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
          <div className="flex items-center bg-[#0a0d14] rounded-lg border border-[#252d42] p-1">
            <button
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded transition-colors ${viewMode === 'grid' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
              title="Grid Cards View"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button
              onClick={() => setViewMode('table')}
              className={`p-1.5 rounded transition-colors ${viewMode === 'table' ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-slate-200'}`}
              title="Table List View"
            >
              <TableProperties className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* ── Filter Bar ── */}
      <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 text-xs">
          {/* Search */}
          <div className="relative col-span-1 sm:col-span-2">
            <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
            <input
              type="text"
              placeholder="Search camera, object, track ID, location..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg pl-9 pr-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
            />
          </div>

          {/* Object Filter */}
          <select
            value={objectFilter}
            onChange={(e) => setObjectFilter(e.target.value)}
            className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
          >
            <option value="all">All Objects</option>
            <option value="person">Person</option>
            <option value="car">Car</option>
            <option value="truck">Truck</option>
            <option value="bus">Bus</option>
            <option value="motorcycle">Motorcycle</option>
            <option value="bicycle">Bicycle</option>
          </select>

          {/* Camera Filter */}
          <select
            value={cameraFilter}
            onChange={(e) => setCameraFilter(e.target.value)}
            className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
          >
            <option value="all">All Cameras</option>
            {cameraOptions.map((c) => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>

          {/* Severity Filter */}
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
          >
            <option value="all">All Severities</option>
            <option value="CRITICAL">CRITICAL</option>
            <option value="HIGH">HIGH</option>
            <option value="MEDIUM">MEDIUM</option>
            <option value="LOW">LOW</option>
            <option value="INFO">INFO</option>
          </select>

          {/* Event Filter */}
          <select
            value={eventFilter}
            onChange={(e) => setEventFilter(e.target.value)}
            className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 text-xs"
          >
            <option value="all">All Event Types</option>
            <option value="RESTRICTED ZONE INTRUSION">Restricted Zone Intrusion</option>
            <option value="ZONE LOITERING DETECTED">Zone Loitering</option>
            <option value="DETECTION">Detection (Confirmed Track)</option>
            <option value="INTRUSION">General Intrusion</option>
          </select>
        </div>

        {/* Sort row */}
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-[#252d42]">
          <button
            onClick={() => setSortOrder((p) => p === 'newest' ? 'oldest' : 'newest')}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            <ArrowUpDown className="w-3.5 h-3.5 text-blue-400" />
            Sort: <strong className="text-slate-200">{sortOrder === 'newest' ? 'Newest First' : 'Oldest First'}</strong>
          </button>
          {(search || objectFilter !== 'all' || cameraFilter !== 'all' || severityFilter !== 'all' || eventFilter !== 'all') && (
            <button
              onClick={() => { setSearch(''); setObjectFilter('all'); setCameraFilter('all'); setSeverityFilter('all'); setEventFilter('all'); }}
              className="text-xs text-red-400 hover:text-red-300 flex items-center gap-1"
            >
              <X className="w-3 h-3" /> Clear filters
            </button>
          )}
        </div>
      </div>

      {/* ── Main Content ── */}
      {loading ? (
        <div className="p-16 text-center">
          <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4" />
          <p className="text-slate-400 font-mono text-xs">Loading evidence snapshots from database...</p>
        </div>
      ) : apiError ? (
        <div className="bg-red-950/30 p-8 rounded-xl border border-red-500/40 text-center space-y-3">
          <AlertTriangle className="w-8 h-8 text-red-400 mx-auto" />
          <p className="font-bold text-red-400 text-sm">Evidence API Error</p>
          <p className="text-xs text-red-300 font-mono max-w-lg mx-auto">{apiError}</p>
          <button
            onClick={fetchEvidence}
            className="mt-2 px-4 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg text-xs font-bold uppercase"
          >
            Retry
          </button>
        </div>
      ) : sortedItems.length === 0 ? (
        <div className="bg-[#111622] p-16 rounded-xl border border-[#252d42] text-center space-y-3">
          <Camera className="w-10 h-10 text-slate-600 mx-auto" />
          <p className="font-bold text-slate-300 text-sm uppercase tracking-wider">NO REAL AI DETECTION RECORDS</p>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            Waiting for real camera detections... Connect an active camera stream with virtual security zones or trigger an intrusion event to generate real-time AI detection evidence.
          </p>
          <button onClick={fetchEvidence} className="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-bold uppercase tracking-wider">
            Refresh
          </button>
        </div>
      ) : viewMode === 'grid' ? (
        /* ── GRID VIEW ── */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
          {sortedItems.map((item, idx) => {
            const imgUrl = resolveImageUrl(item);
            const dt = item.captured_at ? new Date(item.captured_at) : null;
            return (
              <div
                key={item.id}
                className="bg-[#111622] rounded-xl border border-[#252d42] hover:border-blue-500/50 transition-all overflow-hidden flex flex-col group shadow-xl"
              >
                {/* Snapshot */}
                <div
                  className="relative aspect-video bg-slate-950 overflow-hidden cursor-pointer"
                  onClick={() => setLightboxIdx(idx)}
                >
                  {imgUrl ? (
                    <img
                      src={imgUrl}
                      alt={`Evidence ${item.id}`}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                      onError={(e) => {
                        (e.target as HTMLImageElement).src = '';
                        (e.target as HTMLImageElement).style.display = 'none';
                      }}
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs flex-col gap-1">
                      <Camera className="w-6 h-6" />
                      No Image
                    </div>
                  )}
                  {/* Expand icon */}
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/30">
                    <Maximize2 className="w-8 h-8 text-white drop-shadow-lg" />
                  </div>
                  {/* Object badge */}
                  <div className="absolute top-2 left-2 bg-blue-600/90 text-white font-bold text-[10px] px-2 py-0.5 rounded shadow uppercase">
                    {(item.object_class || 'obj').toUpperCase()} {item.confidence ? `${(item.confidence * 100).toFixed(0)}%` : ''}
                  </div>
                  {/* Track badge */}
                  <div className="absolute top-2 right-2 bg-slate-950/90 text-amber-400 font-bold text-[10px] px-2 py-0.5 rounded border border-amber-500/40 font-mono">
                    {item.track_id || '—'}
                  </div>
                </div>

                {/* Card Body */}
                <div className="p-3 space-y-2 flex-1 flex flex-col justify-between text-xs">
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <span className="text-amber-400 font-bold truncate text-[11px] max-w-[60%]">
                        {item.event_type || 'DETECTION'}
                      </span>
                      <SeverityBadge severity={item.severity || 'INFO'} />
                    </div>
                    <div className="text-[11px] text-slate-400 space-y-0.5 font-mono">
                      <div>Cam: <strong className="text-blue-400">{item.camera_number || item.camera_id}</strong></div>
                      <div className="truncate">Loc: <strong className="text-slate-300">{item.location || '—'}</strong></div>
                      {dt && (
                        <div className="text-slate-500">{dt.toLocaleDateString()} {dt.toLocaleTimeString()}</div>
                      )}
                    </div>
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={() => setLightboxIdx(idx)}
                      className="flex-1 py-1.5 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded text-[10px] font-bold uppercase flex items-center justify-center gap-1 border border-[#252d42] transition-colors"
                    >
                      <Maximize2 className="w-3 h-3" /> View
                    </button>
                    <button
                      onClick={() => setSelectedItem(item)}
                      className="flex-1 py-1.5 bg-[#1a2030] hover:bg-blue-600 text-slate-300 hover:text-white rounded text-[10px] font-bold uppercase flex items-center justify-center gap-1 border border-[#252d42] hover:border-blue-500 transition-colors"
                    >
                      <Info className="w-3 h-3" /> Details
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* ── TABLE VIEW ── */
        <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="bg-[#1a2030] border-b border-[#252d42] text-slate-400 uppercase font-mono text-[11px]">
                  <th className="p-3">Snapshot</th>
                  <th className="p-3">Object</th>
                  <th className="p-3">Confidence</th>
                  <th className="p-3">Camera</th>
                  <th className="p-3">Location</th>
                  <th className="p-3">Date &amp; Time</th>
                  <th className="p-3">Event</th>
                  <th className="p-3">Severity</th>
                  <th className="p-3">Risk</th>
                  <th className="p-3">Track ID</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#252d42] text-slate-300 font-mono">
                {sortedItems.map((item, idx) => {
                  const imgUrl = resolveImageUrl(item);
                  const dt = item.captured_at ? new Date(item.captured_at) : null;
                  return (
                    <tr key={item.id} className="hover:bg-[#1a2030]/60 transition-colors">
                      <td className="p-3">
                        <div
                          className="w-16 h-11 bg-slate-950 rounded overflow-hidden cursor-pointer relative group"
                          onClick={() => setLightboxIdx(idx)}
                        >
                          {imgUrl ? (
                            <img src={imgUrl} alt="Snapshot" className="w-full h-full object-cover" />
                          ) : (
                            <div className="w-full h-full flex items-center justify-center text-[9px] text-slate-600">N/A</div>
                          )}
                          <div className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
                            <Eye className="w-4 h-4 text-white" />
                          </div>
                        </div>
                      </td>
                      <td className="p-3 font-bold text-blue-400 uppercase">{item.object_class || '—'}</td>
                      <td className="p-3 text-emerald-400 font-bold">{item.confidence ? `${(item.confidence * 100).toFixed(0)}%` : '—'}</td>
                      <td className="p-3 text-blue-400 font-bold">{item.camera_number || item.camera_id}</td>
                      <td className="p-3 text-slate-400 truncate max-w-[140px]">{item.location || '—'}</td>
                      <td className="p-3 text-slate-400 whitespace-nowrap">
                        {dt ? `${dt.toLocaleDateString()} ${dt.toLocaleTimeString()}` : '—'}
                      </td>
                      <td className="p-3 text-amber-400 font-bold max-w-[160px] truncate">{item.event_type}</td>
                      <td className="p-3"><SeverityBadge severity={item.severity || 'INFO'} /></td>
                      <td className="p-3 font-bold text-red-400">{item.risk_score ?? 0}/100</td>
                      <td className="p-3 text-emerald-400 font-bold">{item.track_id || '—'}</td>
                      <td className="p-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {imgUrl && (
                            <a
                              href={imgUrl}
                              download
                              target="_blank"
                              rel="noreferrer"
                              className="p-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700"
                              title="Download"
                            >
                              <Download className="w-3 h-3" />
                            </a>
                          )}
                          <button
                            onClick={() => setSelectedItem(item)}
                            className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white rounded border border-blue-500/30 text-[11px] font-bold uppercase transition-colors"
                          >
                            Details
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Lightbox ── */}
      {lightboxIdx !== null && sortedItems[lightboxIdx] && (() => {
        const imgUrl = resolveImageUrl(sortedItems[lightboxIdx]);
        return imgUrl ? (
          <ImageLightbox
            src={imgUrl}
            alt={`Evidence ${sortedItems[lightboxIdx].id}`}
            onClose={() => setLightboxIdx(null)}
            onPrev={() => setLightboxIdx((i) => (i !== null && i > 0 ? i - 1 : i))}
            onNext={() => setLightboxIdx((i) => (i !== null && i < sortedItems.length - 1 ? i + 1 : i))}
            hasPrev={lightboxIdx > 0}
            hasNext={lightboxIdx < sortedItems.length - 1}
          />
        ) : null;
      })()}

      {/* ── Evidence Detail Modal ── */}
      {selectedItem && (
        <EvidenceDetailModal
          item={{ ...selectedItem, file_url: resolveImageUrl(selectedItem) }}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </div>
  );
};
