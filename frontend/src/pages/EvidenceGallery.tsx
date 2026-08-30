import React, { useEffect, useState, useCallback } from 'react';
import {
  Camera, ShieldAlert, Search, LayoutGrid, TableProperties,
  Eye, ArrowUpDown, RefreshCw, Cpu, AlertTriangle, X,
  ChevronLeft, ChevronRight, Download, Maximize2, Info, Trash2, CheckSquare, Square
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';
import { formatISTDate, formatISTTime, formatISTDateTime } from '../utils/timeFormat';

function getObjectDisplayLabel(objCls?: string): string {
  const c = (objCls || '').toLowerCase().trim();
  if (c === 'truck' || c === 'lorry') return 'TRUCK / LORRY';
  if (c === 'person') return 'PERSON';
  if (c === 'car') return 'CAR';
  if (c === 'bus') return 'BUS';
  if (c === 'motorcycle') return 'MOTORCYCLE';
  if (c === 'bicycle') return 'BICYCLE';
  if (c === 'cell phone') return 'PHONE';
  if (c === 'laptop') return 'LAPTOP';
  if (c === 'backpack' || c === 'handbag' || c === 'suitcase') return c.toUpperCase();
  if (c === 'chair' || c === 'couch' || c === 'bed') return c.toUpperCase();
  if (c === 'drone') return 'DRONE';
  if (c === 'unknown') return 'UNKNOWN OBJECT';
  return (objCls || 'OBJECT').toUpperCase();
}

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

// ---- Delete Confirmation Modal ----
function DeleteConfirmationModal({
  item,
  isDeleting,
  onConfirm,
  onCancel,
}: {
  item: any;
  isDeleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  if (!item) return null;
  const dt = item.captured_at ? new Date(item.captured_at) : new Date();

  return (
    <div className="fixed inset-0 z-[110] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
      <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
        {/* Header */}
        <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
              <Trash2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE DETECTION?</h3>
              <p className="text-[11px] text-red-400/80 font-mono">PERMANENT REMOVAL</p>
            </div>
          </div>
          <button
            onClick={onCancel}
            disabled={isDeleting}
            className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content Details */}
        <div className="p-6 space-y-4 text-xs">
          <p className="text-slate-300 font-sans text-xs leading-relaxed">
            Are you sure you want to permanently delete this detection record and its associated snapshot image?
          </p>

          <div className="bg-[#0a0d14] p-3.5 rounded-xl border border-[#252d42] space-y-2 text-[11px]">
            <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
              <span className="text-slate-400">Object:</span>
              <strong className="text-blue-400 uppercase font-bold">
                {getObjectDisplayLabel(item.display_label || item.object_class)}
              </strong>
            </div>
            <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
              <span className="text-slate-400">Track ID:</span>
              <strong className="text-amber-400">{item.track_id || '—'}</strong>
            </div>
            <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
              <span className="text-slate-400">Camera:</span>
              <strong className="text-slate-200">{item.camera_number || item.camera_id}</strong>
            </div>
            <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
              <span className="text-slate-400">Location:</span>
              <span className="text-slate-300 truncate max-w-[200px]">{item.location || '—'}</span>
            </div>
            <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
              <span className="text-slate-400">Date:</span>
              <span className="text-slate-200 font-mono">{formatISTDate(item.captured_at || item.created_at || item.timestamp)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-400">Time:</span>
              <span className="text-slate-200 font-mono">{formatISTTime(item.captured_at || item.created_at || item.timestamp)}</span>
            </div>
          </div>

          <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
            ⚠ This action is destructive and cannot be undone. An audit log entry will be recorded.
          </div>
        </div>

        {/* Footer Actions */}
        <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={isDeleting}
            className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-red-950/50 transition-all disabled:opacity-50"
          >
            {isDeleting ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Deleting...
              </>
            ) : (
              <>
                <Trash2 className="w-3.5 h-3.5" />
                Delete
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---- Bulk Delete Confirmation Modal ----
function BulkDeleteModal({
  count,
  isDeleting,
  onConfirm,
  onCancel,
}: {
  count: number;
  isDeleting: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-[110] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
      <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0">
        <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
              <Trash2 className="w-5 h-5" />
            </div>
            <div>
              <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE {count} DETECTIONS?</h3>
              <p className="text-[11px] text-red-400/80 font-mono">BULK PERMANENT REMOVAL</p>
            </div>
          </div>
          <button
            onClick={onCancel}
            disabled={isDeleting}
            className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6 space-y-4 text-xs">
          <p className="text-slate-300 leading-relaxed font-sans">
            Are you sure you want to permanently delete <strong className="text-red-400 font-mono">{count}</strong> selected detection records and their associated snapshot files?
          </p>
          <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
            ⚠ This action cannot be undone. All selected evidence snapshots will be permanently erased.
          </div>
        </div>

        <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
          <button
            onClick={onCancel}
            disabled={isDeleting}
            className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-red-950/50 transition-all disabled:opacity-50"
          >
            {isDeleting ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                Deleting {count}...
              </>
            ) : (
              <>
                <Trash2 className="w-3.5 h-3.5" />
                Delete All ({count})
              </>
            )}
          </button>
        </div>
      </div>
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

  // Deletion States
  const [itemToDelete, setItemToDelete] = useState<any | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Filters & Search
  const [search, setSearch] = useState('');
  const [objectFilter, setObjectFilter] = useState('all');
  const [cameraFilter, setCameraFilter] = useState('all');
  const [severityFilter, setSeverityFilter] = useState('all');
  const [eventFilter, setEventFilter] = useState('all');
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');

  const { token } = useAuth();
  const { lastMessage } = useWebSocket();

  const showToast = (type: 'success' | 'error', text: string) => {
    setToastMessage({ type, text });
    setTimeout(() => {
      setToastMessage(null);
    }, 4000);
  };

  const fetchEvidence = useCallback(async () => {
    setLoading(true);
    setApiError(null);
    try {
      const authToken = token || localStorage.getItem('ibvap_token') || localStorage.getItem('token');
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
        display_label: ws.display_label,
        confidence: ws.confidence,
        track_id: ws.track_id,
        event_type: ws.event_type || 'NORMAL DETECTION',
        risk_score: ws.risk_score ?? 0.0,
        severity: ws.severity || 'INFO',
        captured_at: ws.timestamp || new Date().toISOString(),
        file_url: ws.file_url,
        evidence_url: ws.file_url,
      };
      if (newEv.id) {
        setItems((prev) => [newEv, ...prev.filter((x) => x.id !== newEv.id)]);
        setTotalCount((c) => c + 1);
      }
    }
  }, [lastMessage]);

  // Handle single deletion
  const handleDeleteConfirm = async () => {
    if (!itemToDelete) return;
    setIsDeleting(true);
    const targetId = itemToDelete.id;

    try {
      const authToken = token || localStorage.getItem('ibvap_token') || localStorage.getItem('token');
      const headers: Record<string, string> = {};
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch(`/api/evidence/${targetId}`, {
        method: 'DELETE',
        headers,
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText);
        throw new Error(`Deletion failed (${res.status}): ${errText}`);
      }

      // Immediate state update
      setItems((prev) => prev.filter((it) => it.id !== targetId));
      setTotalCount((c) => Math.max(0, c - 1));
      setSelectedIds((prev) => {
        const next = new Set(prev);
        next.delete(targetId);
        return next;
      });

      showToast('success', `✓ Detection #${targetId.substring(0, 8)} deleted successfully`);
      setItemToDelete(null);
    } catch (err: any) {
      console.error('[EVIDENCE] Delete error:', err);
      showToast('error', `⚠ DELETE FAILED: ${err.message || 'Unable to delete detection'}`);
    } finally {
      setIsDeleting(false);
    }
  };

  // Handle bulk deletion
  const handleBulkDeleteConfirm = async () => {
    if (selectedIds.size === 0) return;
    setIsDeleting(true);
    const idsArray = Array.from(selectedIds);

    try {
      const authToken = token || localStorage.getItem('ibvap_token') || localStorage.getItem('token');
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
      };
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const res = await fetch('/api/evidence/bulk-delete', {
        method: 'POST',
        headers,
        body: JSON.stringify({ evidence_ids: idsArray }),
      });

      if (!res.ok) {
        const errText = await res.text().catch(() => res.statusText);
        throw new Error(`Bulk deletion failed (${res.status}): ${errText}`);
      }

      const data = await res.json();
      const deletedSet = new Set(data.deleted_ids || idsArray);

      setItems((prev) => prev.filter((it) => !deletedSet.has(it.id)));
      setTotalCount((c) => Math.max(0, c - deletedSet.size));
      setSelectedIds(new Set());
      setShowBulkDeleteModal(false);

      showToast('success', `✓ ${deletedSet.size} detection records deleted successfully`);
    } catch (err: any) {
      console.error('[EVIDENCE] Bulk delete error:', err);
      showToast('error', `⚠ BULK DELETE FAILED: ${err.message || 'Unable to delete records'}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const toggleSelectId = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === items.length && items.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((it) => it.id)));
    }
  };

  const sortedItems = [...items].sort((a, b) => {
    const tA = new Date(a.captured_at || 0).getTime();
    const tB = new Date(b.captured_at || 0).getTime();
    return sortOrder === 'newest' ? tB - tA : tA - tB;
  });

  // Derive unique camera list for camera filter
  const cameraOptions = Array.from(
    new Set(items.map((it) => it.camera_number || it.camera_id).filter(Boolean))
  );

  // Image URL resolver
  const resolveImageUrl = (item: any): string | null => {
    if (item.id && item.file_url) {
      if (item.file_url.startsWith('/api/evidence')) return item.file_url;
      return `/api/evidence/${item.id}/image`;
    }
    return item.file_url || item.evidence_url || null;
  };

  return (
    <div className="p-6 space-y-6 font-mono relative">
      {/* ── Toast Notification Banner ── */}
      {toastMessage && (
        <div className={`fixed top-6 right-6 z-[120] px-4 py-3 rounded-xl border shadow-2xl flex items-center gap-3 transition-all animate-in slide-in-from-top-4 ${
          toastMessage.type === 'success'
            ? 'bg-[#0f241a] border-emerald-500/50 text-emerald-300'
            : 'bg-[#2a0f14] border-red-500/50 text-red-300'
        }`}>
          <span className="font-bold text-xs">{toastMessage.text}</span>
          <button onClick={() => setToastMessage(null)} className="text-slate-400 hover:text-white">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

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
          {selectedIds.size > 0 && (
            <button
              onClick={() => setShowBulkDeleteModal(true)}
              className="px-3.5 py-2 bg-gradient-to-r from-red-600 to-red-700 hover:from-red-500 hover:to-red-600 text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center gap-1.5 shadow-lg shadow-red-950/40 border border-red-500/30 transition-all"
            >
              <Trash2 className="w-3.5 h-3.5" />
              Delete Selected ({selectedIds.size})
            </button>
          )}
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
            <option value="truck">Truck / Lorry</option>
            <option value="bus">Bus</option>
            <option value="motorcycle">Motorcycle</option>
            <option value="bicycle">Bicycle</option>
            <option value="laptop">Laptop</option>
            <option value="cell phone">Phone</option>
            <option value="backpack">Backpack / Bag</option>
            <option value="chair">Furniture</option>
            <option value="drone">Drone</option>
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
            <option value="NORMAL DETECTION">Normal Detection</option>
          </select>
        </div>

        {/* Sort & Select All Row */}
        <div className="flex items-center justify-between mt-3 pt-3 border-t border-[#252d42]">
          <div className="flex items-center gap-3">
            <button
              onClick={toggleSelectAll}
              className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1.5 transition-colors font-mono"
            >
              {selectedIds.size > 0 && selectedIds.size === items.length ? (
                <CheckSquare className="w-4 h-4 text-blue-400" />
              ) : (
                <Square className="w-4 h-4" />
              )}
              {selectedIds.size > 0 ? `Deselect All (${selectedIds.size})` : 'Select All'}
            </button>
          </div>

          <button
            onClick={() => setSortOrder((o) => (o === 'newest' ? 'oldest' : 'newest'))}
            className="text-xs text-slate-400 hover:text-slate-200 flex items-center gap-1 transition-colors"
          >
            <ArrowUpDown className="w-3.5 h-3.5 text-blue-400" />
            Sort: <strong className="text-slate-200 uppercase">{sortOrder === 'newest' ? 'Newest First' : 'Oldest First'}</strong>
          </button>
        </div>
      </div>

      {/* ── Content Area ── */}
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
            const isSelected = selectedIds.has(item.id);

            return (
              <div
                key={item.id}
                className={`bg-[#111622] rounded-xl border transition-all overflow-hidden flex flex-col group shadow-xl relative ${
                  isSelected ? 'border-blue-500 bg-[#141b2b]' : 'border-[#252d42] hover:border-blue-500/50'
                }`}
              >
                {/* Snapshot Image */}
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

                  {/* Selection checkbox */}
                  <div
                    className="absolute top-2 left-2 z-10"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelectId(item.id);
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={() => {}}
                      className="w-4 h-4 rounded border-slate-700 bg-slate-900/90 text-blue-600 focus:ring-0 cursor-pointer shadow"
                    />
                  </div>

                  {/* Expand icon */}
                  <div className="absolute inset-0 flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity bg-black/30">
                    <Maximize2 className="w-8 h-8 text-white drop-shadow-lg" />
                  </div>

                  {/* Object badge */}
                  <div className="absolute top-2 left-8 bg-blue-600/90 text-white font-bold text-[10px] px-2 py-0.5 rounded shadow uppercase font-mono">
                    {getObjectDisplayLabel(item.display_label || item.object_class)} {item.confidence ? `${(item.confidence * 100).toFixed(0)}%` : ''}
                  </div>

                  {/* Track badge */}
                  <div className="absolute top-2 right-2 bg-slate-950/90 text-amber-400 font-bold text-[10px] px-2 py-0.5 rounded border border-amber-500/40 font-mono">
                    {item.track_id || '—'}
                  </div>
                </div>

                {/* Card Body */}
                <div className="p-3.5 space-y-2.5 flex-1 flex flex-col justify-between text-xs">
                  <div>
                    <div className="flex items-center justify-between mb-1 font-mono">
                      <span className="font-bold text-sm text-slate-100 tracking-wide">
                        {getObjectDisplayLabel(item.display_label || item.object_class)}
                      </span>
                      <span className="font-bold text-sm text-blue-400 font-mono">
                        {item.confidence ? `${(item.confidence * 100).toFixed(0)}%` : ''}
                      </span>
                    </div>

                    <div className="text-amber-400 font-mono text-[11px] mb-2 font-semibold">
                      Track ID: <span className="text-amber-300">{item.track_id || '—'}</span>
                    </div>

                    <div className="text-[11px] text-slate-400 space-y-1 font-mono bg-[#0a0d14] p-2.5 rounded-lg border border-[#252d42]">
                      <div>Camera: <strong className="text-blue-400">{item.camera_number || item.camera_id}</strong></div>
                      <div className="truncate">Location: <strong className="text-slate-300">{item.location || '—'}</strong></div>
                      <div className="text-slate-400 flex flex-wrap gap-x-2">
                        <span>Date: <strong className="text-slate-200">{formatISTDate(item.captured_at || item.created_at || item.timestamp)}</strong></span>
                        <span>Time: <strong className="text-slate-200">{formatISTTime(item.captured_at || item.created_at || item.timestamp)}</strong></span>
                      </div>
                      <div className="flex items-center justify-between pt-1 border-t border-[#252d42] mt-1">
                        <span className="text-slate-400">Event: <strong className="text-amber-400 text-[10px] uppercase">{item.event_type || 'NORMAL DETECTION'}</strong></span>
                        <SeverityBadge severity={item.severity || 'INFO'} />
                      </div>
                    </div>
                  </div>

                  {/* Actions Row: [ VIEW ] [ DETAILS ] [ 🗑 TRASH ] */}
                  <div className="flex items-center gap-1.5 pt-1">
                    <button
                      onClick={() => setLightboxIdx(idx)}
                      className="flex-1 py-1.5 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded text-[10px] font-bold uppercase flex items-center justify-center gap-1 border border-[#252d42] transition-colors"
                      title="View snapshot"
                    >
                      <Maximize2 className="w-3 h-3" /> View
                    </button>
                    <button
                      onClick={() => setSelectedItem(item)}
                      className="flex-1 py-1.5 bg-[#1a2030] hover:bg-blue-600 text-slate-300 hover:text-white rounded text-[10px] font-bold uppercase flex items-center justify-center gap-1 border border-[#252d42] hover:border-blue-500 transition-colors"
                      title="View metadata details"
                    >
                      <Info className="w-3 h-3" /> Details
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setItemToDelete(item);
                      }}
                      className="p-1.5 bg-red-950/30 hover:bg-red-600 text-red-400 hover:text-white rounded border border-red-500/30 hover:border-red-500 transition-all"
                      title="Delete detection"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
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
                  <th className="p-3 w-8">
                    <input
                      type="checkbox"
                      checked={selectedIds.size === items.length && items.length > 0}
                      onChange={toggleSelectAll}
                      className="w-4 h-4 rounded border-slate-700 bg-slate-900 text-blue-600 cursor-pointer"
                    />
                  </th>
                  <th className="p-3">Snapshot</th>
                  <th className="p-3">Object</th>
                  <th className="p-3">Confidence</th>
                  <th className="p-3">Camera</th>
                  <th className="p-3">Location</th>
                  <th className="p-3">Date &amp; Time</th>
                  <th className="p-3">Event</th>
                  <th className="p-3">Severity</th>
                  <th className="p-3">Track ID</th>
                  <th className="p-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#252d42] text-slate-300 font-mono">
                {sortedItems.map((item, idx) => {
                  const imgUrl = resolveImageUrl(item);
                  const dt = item.captured_at ? new Date(item.captured_at) : null;
                  const isSelected = selectedIds.has(item.id);

                  return (
                    <tr key={item.id} className={`hover:bg-[#1a2030]/60 transition-colors ${isSelected ? 'bg-blue-950/20' : ''}`}>
                      <td className="p-3">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectId(item.id)}
                          className="w-4 h-4 rounded border-slate-700 bg-slate-900 text-blue-600 cursor-pointer"
                        />
                      </td>
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
                      <td className="p-3 font-bold text-blue-400 uppercase">{getObjectDisplayLabel(item.display_label || item.object_class)}</td>
                      <td className="p-3 text-emerald-400 font-bold">{item.confidence ? `${(item.confidence * 100).toFixed(0)}%` : '—'}</td>
                      <td className="p-3 text-blue-400 font-bold">{item.camera_number || item.camera_id}</td>
                      <td className="p-3 text-slate-400 truncate max-w-[140px]">{item.location || '—'}</td>
                      <td className="p-3 text-slate-300 whitespace-nowrap font-mono">
                        {formatISTDateTime(item.captured_at || item.created_at || item.timestamp)}
                      </td>
                      <td className="p-3 text-amber-400 font-bold max-w-[160px] truncate">{item.event_type}</td>
                      <td className="p-3"><SeverityBadge severity={item.severity || 'INFO'} /></td>
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
                            className="px-2.5 py-1.5 bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white rounded border border-blue-500/30 text-[11px] font-bold uppercase transition-colors"
                          >
                            Details
                          </button>
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              setItemToDelete(item);
                            }}
                            className="p-1.5 bg-red-950/40 hover:bg-red-600 text-red-400 hover:text-white rounded border border-red-500/40 text-xs transition-colors"
                            title="Delete detection"
                          >
                            <Trash2 className="w-3 h-3" />
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

      {/* ── Single Delete Confirmation Dialog ── */}
      {itemToDelete && (
        <DeleteConfirmationModal
          item={itemToDelete}
          isDeleting={isDeleting}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setItemToDelete(null)}
        />
      )}

      {/* ── Bulk Delete Confirmation Dialog ── */}
      {showBulkDeleteModal && (
        <BulkDeleteModal
          count={selectedIds.size}
          isDeleting={isDeleting}
          onConfirm={handleBulkDeleteConfirm}
          onCancel={() => setShowBulkDeleteModal(false)}
        />
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
          item={selectedItem}
          onClose={() => setSelectedItem(null)}
        />
      )}
    </div>
  );
};

export default EvidenceGallery;
