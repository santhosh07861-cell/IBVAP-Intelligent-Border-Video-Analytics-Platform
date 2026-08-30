import React, { useState, useEffect, useCallback, useRef } from 'react';
import { useWebSocket } from '../context/WebSocketContext';
import { authFetch } from '../utils/auth';
import { formatISTDateTime } from '../utils/timeFormat';
import './ANPRView.css';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ANPRRecord {
  id: string;
  camera_id: string;
  plate_number: string;
  vehicle_type: string;
  vehicle_track_id: number | null;
  camera_name: string | null;
  camera_location: string | null;
  detection_confidence: number;
  ocr_confidence: number;
  snapshot_url: string | null;
  status: string;
  is_watchlist_match: boolean;
  timestamp: string;
}

interface WatchlistEntry {
  id: string;
  plate_number: string;
  vehicle_type: string | null;
  reason: string | null;
  severity: string;
  is_active: boolean;
  notes: string | null;
  added_by: string | null;
  created_at: string;
}

interface Stats {
  total_today: number;
  confirmed_today: number;
  watchlist_matches_today: number;
  total_all_time: number;
}

interface Camera {
  id: string;
  camera_id: string;
  name: string;
}

const VEHICLE_TYPES = ['All', 'Car', 'Truck', 'Bus', 'Motorcycle', 'Bicycle', 'Van', 'Auto-Rickshaw', 'Unknown'];
const VEHICLE_ICONS: Record<string, string> = {
  'CAR': '🚗', 'TRUCK': '🚛', 'BUS': '🚌', 'MOTORCYCLE': '🏍️',
  'BICYCLE': '🚲', 'VAN': '🚐', 'AUTO-RICKSHAW': '🛺', 'UNKNOWN': '🚘',
};

function vehicleIcon(type: string) {
  return VEHICLE_ICONS[type?.toUpperCase()] || '🚘';
}

function fmtConf(v: number) {
  return `${Math.round((v || 0) * 100)}%`;
}

function fmtTime(iso: string) {
  return formatISTDateTime(iso);
}

// ─── Evidence Modal ───────────────────────────────────────────────────────────

function EvidenceModal({
  record,
  onClose,
  onDelete
}: {
  record: ANPRRecord;
  onClose: () => void;
  onDelete?: (record: ANPRRecord) => void;
}) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div className="anpr-modal-overlay" onClick={onClose}>
      <div className="anpr-modal" onClick={e => e.stopPropagation()}>
        <div className="anpr-modal-header">
          <div className="anpr-modal-title-row">
            <span className="anpr-modal-icon">{vehicleIcon(record.vehicle_type)}</span>
            <div>
              <div className="anpr-modal-plate">{record.plate_number}</div>
              <div className="anpr-modal-sub">{record.vehicle_type} — {record.status}</div>
            </div>
            {record.is_watchlist_match && (
              <span className="anpr-badge anpr-badge-watchlist anpr-modal-wl-badge">⚠ WATCHLIST</span>
            )}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {onDelete && (
              <button
                className="anpr-action-btn anpr-action-delete"
                onClick={() => onDelete(record)}
                title="Delete ANPR Record"
                style={{ padding: '6px 12px', fontSize: '11px' }}
              >
                🗑 Delete
              </button>
            )}
            <button className="anpr-modal-close" onClick={onClose}>✕</button>
          </div>
        </div>

        {record.snapshot_url ? (
          <div className="anpr-modal-img-wrap">
            <img
              src={record.snapshot_url}
              alt={`ANPR Evidence: ${record.plate_number}`}
              className="anpr-modal-img"
              onError={e => { (e.currentTarget as HTMLImageElement).src = ''; (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
            />
          </div>
        ) : (
          <div className="anpr-modal-no-img">No evidence image available</div>
        )}

        <div className="anpr-modal-meta-grid">
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Plate Number</span>
            <span className="anpr-modal-meta-value anpr-plate-bold">{record.plate_number}</span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Vehicle Type</span>
            <span className="anpr-modal-meta-value">{vehicleIcon(record.vehicle_type)} {record.vehicle_type}</span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Track ID</span>
            <span className="anpr-modal-meta-value">{record.vehicle_track_id != null ? `V-${record.vehicle_track_id}` : '—'}</span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Status</span>
            <span className={`anpr-modal-meta-value ${record.is_watchlist_match ? 'anpr-status-watchlist' : record.status === 'CONFIRMED' ? 'anpr-status-ok' : 'anpr-status-uncertain'}`}>
              {record.is_watchlist_match ? '⚠ WATCHLIST MATCH' : record.status}
            </span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Detection Conf</span>
            <span className="anpr-modal-meta-value">{fmtConf(record.detection_confidence)}</span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">OCR Confidence</span>
            <span className={`anpr-modal-meta-value ${record.ocr_confidence >= 0.85 ? 'anpr-conf-high' : record.ocr_confidence >= 0.60 ? 'anpr-conf-mid' : 'anpr-conf-low'}`}>
              {fmtConf(record.ocr_confidence)}
            </span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Camera</span>
            <span className="anpr-modal-meta-value">{record.camera_name || '—'}</span>
          </div>
          <div className="anpr-modal-meta-item">
            <span className="anpr-modal-meta-label">Location</span>
            <span className="anpr-modal-meta-value">{record.camera_location || '—'}</span>
          </div>
          <div className="anpr-modal-meta-item anpr-modal-meta-full">
            <span className="anpr-modal-meta-label">Timestamp</span>
            <span className="anpr-modal-meta-value">{fmtTime(record.timestamp)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Detection Card ───────────────────────────────────────────────────────────

function ANPRCard({
  record,
  onClick,
  onDelete
}: {
  record: ANPRRecord;
  onClick: () => void;
  onDelete?: (record: ANPRRecord) => void;
}) {
  const isWatchlist = record.is_watchlist_match;
  const isUncertain = record.status === 'UNCERTAIN';

  return (
    <div
      className={`anpr-card ${isWatchlist ? 'anpr-card-watchlist' : isUncertain ? 'anpr-card-uncertain' : 'anpr-card-normal'}`}
      onClick={onClick}
      id={`anpr-card-${record.id}`}
      style={{ position: 'relative' }}
    >
      {isWatchlist && <div className="anpr-card-wl-banner">⚠ WATCHLIST MATCH</div>}

      <div className="anpr-card-img-wrap">
        {record.snapshot_url ? (
          <img
            src={record.snapshot_url}
            alt={`ANPR: ${record.plate_number}`}
            className="anpr-card-img"
            onError={e => {
              (e.currentTarget as HTMLImageElement).parentElement!.innerHTML =
                `<div class="anpr-card-no-img">${vehicleIcon(record.vehicle_type)}</div>`;
            }}
          />
        ) : (
          <div className="anpr-card-no-img">{vehicleIcon(record.vehicle_type)}</div>
        )}
      </div>

      <div className="anpr-card-body">
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div className="anpr-card-plate">{record.plate_number}</div>
          {onDelete && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onDelete(record);
              }}
              style={{
                background: 'rgba(239, 68, 68, 0.15)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#f87171',
                borderRadius: '6px',
                padding: '3px 7px',
                fontSize: '11px',
                cursor: 'pointer'
              }}
              title="Delete ANPR record"
            >
              🗑
            </button>
          )}
        </div>

        <div className="anpr-card-row">
          <span className="anpr-card-vtype">{vehicleIcon(record.vehicle_type)} {record.vehicle_type}</span>
          <span className={`anpr-card-status ${isWatchlist ? 'anpr-status-watchlist' : isUncertain ? 'anpr-status-uncertain' : 'anpr-status-ok'}`}>
            {isWatchlist ? '⚠ WATCHLIST' : isUncertain ? '⚠ UNCERTAIN' : '✅ CONFIRMED'}
          </span>
        </div>

        <div className="anpr-card-confs">
          <span title="Detection Confidence">Det: {fmtConf(record.detection_confidence)}</span>
          <span className="anpr-card-sep">│</span>
          <span title="OCR Confidence" className={record.ocr_confidence >= 0.85 ? 'anpr-conf-high' : record.ocr_confidence >= 0.60 ? 'anpr-conf-mid' : 'anpr-conf-low'}>
            OCR: {fmtConf(record.ocr_confidence)}
          </span>
        </div>

        <div className="anpr-card-cam">{record.camera_name || record.camera_id}</div>
        <div className="anpr-card-loc">{record.camera_location || ''}</div>
        <div className="anpr-card-time">{fmtTime(record.timestamp)}</div>

        <button className="anpr-card-btn" onClick={e => { e.stopPropagation(); onClick(); }}>
          VIEW EVIDENCE
        </button>
      </div>
    </div>
  );
}

// ─── Watchlist Manager ────────────────────────────────────────────────────────

function WatchlistManager() {
  const [entries, setEntries] = useState<WatchlistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ plate_number: '', vehicle_type: '', reason: '', severity: 'HIGH', notes: '' });
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const r = await authFetch('/api/anpr/watchlist/list');
      if (r.ok) setEntries(await r.json());
    } catch { }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    if (!form.plate_number.trim()) { setError('Plate number is required'); return; }
    try {
      const r = await authFetch('/api/anpr/watchlist', { method: 'POST', body: JSON.stringify(form) });
      if (r.ok) { setAdding(false); setForm({ plate_number: '', vehicle_type: '', reason: '', severity: 'HIGH', notes: '' }); load(); }
      else { const d = await r.json(); setError(d.detail || 'Failed to add'); }
    } catch { setError('Network error'); }
  };

  const handleToggle = async (entry: WatchlistEntry) => {
    try {
      const r = await authFetch(`/api/anpr/watchlist/${entry.id}`, {
        method: 'PUT', body: JSON.stringify({ is_active: !entry.is_active })
      });
      if (r.ok) load();
    } catch { }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Remove this plate from watchlist?')) return;
    try {
      await authFetch(`/api/anpr/watchlist/${id}`, { method: 'DELETE' });
      load();
    } catch { }
  };

  if (loading) return <div className="anpr-loading">Loading watchlist…</div>;

  return (
    <div className="anpr-watchlist-section">
      <div className="anpr-watchlist-toolbar">
        <h3 className="anpr-watchlist-title">🛡 Plate Watchlist</h3>
        <button className="anpr-add-btn" onClick={() => setAdding(v => !v)}>
          {adding ? '✕ Cancel' : '+ Add Plate'}
        </button>
      </div>

      {adding && (
        <form className="anpr-wl-form" onSubmit={handleAdd}>
          <div className="anpr-wl-form-row">
            <input
              className="anpr-input" placeholder="Plate Number *" value={form.plate_number}
              onChange={e => setForm(f => ({ ...f, plate_number: e.target.value.toUpperCase() }))}
            />
            <select className="anpr-input" value={form.vehicle_type} onChange={e => setForm(f => ({ ...f, vehicle_type: e.target.value }))}>
              <option value="">Any Vehicle</option>
              {VEHICLE_TYPES.slice(1).map(t => <option key={t} value={t.toUpperCase()}>{t}</option>)}
            </select>
            <select className="anpr-input" value={form.severity} onChange={e => setForm(f => ({ ...f, severity: e.target.value }))}>
              <option value="HIGH">HIGH</option>
              <option value="CRITICAL">CRITICAL</option>
            </select>
          </div>
          <input className="anpr-input anpr-input-full" placeholder="Reason (e.g. Stolen vehicle)" value={form.reason}
            onChange={e => setForm(f => ({ ...f, reason: e.target.value }))} />
          <input className="anpr-input anpr-input-full" placeholder="Notes (optional)" value={form.notes}
            onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
          {error && <div className="anpr-wl-error">{error}</div>}
          <button className="anpr-submit-btn" type="submit">ADD TO WATCHLIST</button>
        </form>
      )}

      {entries.length === 0 ? (
        <div className="anpr-empty">No plates on watchlist. Click "+ Add Plate" to begin.</div>
      ) : (
        <div className="anpr-wl-table-wrap">
          <table className="anpr-wl-table">
            <thead>
              <tr>
                <th>PLATE</th><th>VEHICLE</th><th>SEVERITY</th><th>REASON</th><th>ADDED BY</th><th>STATUS</th><th>ACTIONS</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(e => (
                <tr key={e.id} className={!e.is_active ? 'anpr-wl-inactive' : ''}>
                  <td className="anpr-wl-plate">{e.plate_number}</td>
                  <td>{e.vehicle_type || 'Any'}</td>
                  <td><span className={`anpr-badge ${e.severity === 'CRITICAL' ? 'anpr-badge-critical' : 'anpr-badge-high'}`}>{e.severity}</span></td>
                  <td className="anpr-wl-reason">{e.reason || '—'}</td>
                  <td>{e.added_by || '—'}</td>
                  <td>
                    <span className={`anpr-badge ${e.is_active ? 'anpr-badge-active' : 'anpr-badge-disabled'}`}>
                      {e.is_active ? 'ACTIVE' : 'DISABLED'}
                    </span>
                  </td>
                  <td className="anpr-wl-actions">
                    <button className="anpr-action-btn" onClick={() => handleToggle(e)}>
                      {e.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <button className="anpr-action-btn anpr-action-delete" onClick={() => handleDelete(e.id)}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ─── Main ANPR Page ───────────────────────────────────────────────────────────

export default function ANPRView() {
  const { lastAnprDetection } = useWebSocket();
  const [records, setRecords] = useState<ANPRRecord[]>([]);
  const [total, setTotal] = useState(0);
  const [stats, setStats] = useState<Stats | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedRecord, setSelectedRecord] = useState<ANPRRecord | null>(null);
  const [activeTab, setActiveTab] = useState<'detections' | 'watchlist'>('detections');

  // Filters
  const [plateQuery, setPlateQuery] = useState('');
  const [vehicleType, setVehicleType] = useState('All');
  const [cameraId, setCameraId] = useState('all');
  const [status, setStatus] = useState('');
  const [watchlistOnly, setWatchlistOnly] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [minOcr, setMinOcr] = useState(0);
  const [sort, setSort] = useState('newest');
  const [offset, setOffset] = useState(0);
  const LIMIT = 30;

  const loadRef = useRef(0);

  const buildQuery = useCallback(() => {
    const p = new URLSearchParams();
    if (plateQuery.trim()) p.set('plate_query', plateQuery.trim());
    if (vehicleType !== 'All') p.set('vehicle_type', vehicleType.toUpperCase());
    if (cameraId !== 'all') p.set('camera_id', cameraId);
    if (status) p.set('status', status);
    if (watchlistOnly) p.set('watchlist_only', 'true');
    if (dateFrom) p.set('date_from', dateFrom);
    if (dateTo) p.set('date_to', dateTo);
    if (minOcr > 0) p.set('min_ocr_confidence', (minOcr / 100).toFixed(2));
    p.set('sort', sort);
    p.set('limit', String(LIMIT));
    p.set('offset', String(offset));
    return p.toString();
  }, [plateQuery, vehicleType, cameraId, status, watchlistOnly, dateFrom, dateTo, minOcr, sort, offset]);

  const loadData = useCallback(async () => {
    const thisLoad = ++loadRef.current;
    setLoading(true);
    try {
      const [recRes, statsRes, camRes] = await Promise.all([
        authFetch(`/api/anpr?${buildQuery()}`),
        authFetch('/api/anpr/stats'),
        authFetch('/api/cameras'),
      ]);
      if (thisLoad !== loadRef.current) return;
      if (recRes.ok) {
        const d = await recRes.json();
        setRecords(d.results || []);
        setTotal(d.total || 0);
      }
      if (statsRes.ok) setStats(await statsRes.json());
      if (camRes.ok) {
        const d = await camRes.json();
        setCameras(Array.isArray(d) ? d : d.cameras || []);
      }
    } catch { }
    setLoading(false);
  }, [buildQuery]);

  useEffect(() => { loadData(); }, [loadData]);

  // Real-time prepend on ANPR_DETECTION WebSocket event
  useEffect(() => {
    if (!lastAnprDetection) return;
    const d = lastAnprDetection as any;
    if (d.type !== 'ANPR_DETECTION' && d.type !== 'ANPR_WATCHLIST_MATCH') return;
    const newRec: ANPRRecord = {
      id: d.anpr_id || d.id || String(Date.now()),
      camera_id: d.camera_id || '',
      plate_number: d.plate_number || 'PLATE UNCERTAIN',
      vehicle_type: d.vehicle_type || 'UNKNOWN',
      vehicle_track_id: d.vehicle_track_id || null,
      camera_name: d.camera_name || null,
      camera_location: d.location || null,
      detection_confidence: d.detection_confidence || 0,
      ocr_confidence: d.ocr_confidence || 0,
      snapshot_url: d.snapshot_url || d.evidence_url || null,
      status: d.status || 'CONFIRMED',
      is_watchlist_match: d.is_watchlist_match || d.type === 'ANPR_WATCHLIST_MATCH',
      timestamp: d.timestamp || new Date().toISOString(),
    };
    setRecords(prev => {
      const filtered = prev.filter(r => r.id !== newRec.id);
      return [newRec, ...filtered].slice(0, 200);
    });
    setTotal(t => t + 1);
  }, [lastAnprDetection]);

  const handleFilterReset = () => {
    setPlateQuery(''); setVehicleType('All'); setCameraId('all'); setStatus('');
    setWatchlistOnly(false); setDateFrom(''); setDateTo(''); setMinOcr(0);
    setSort('newest'); setOffset(0);
  };

  const handleDeleteRecord = async (record: ANPRRecord) => {
    if (!window.confirm(`Are you sure you want to delete ANPR record for plate ${record.plate_number}?`)) return;
    try {
      const res = await authFetch(`/api/anpr/results/${record.id}`, { method: 'DELETE' });
      if (res.ok) {
        setRecords(prev => prev.filter(r => r.id !== record.id));
        setTotal(t => Math.max(0, t - 1));
        if (selectedRecord?.id === record.id) setSelectedRecord(null);
      } else {
        alert('Failed to delete ANPR detection record.');
      }
    } catch (err) {
      console.error('Failed to delete ANPR record:', err);
      alert('Error deleting ANPR record.');
    }
  };

  const totalPages = Math.ceil(total / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

  return (
    <div className="anpr-page">
      {/* ── Stats Bar ──────────────────────────────────────────────────────────── */}
      <div className="anpr-stats-bar">
        <div className="anpr-stat-card">
          <div className="anpr-stat-val">{stats?.total_today ?? '—'}</div>
          <div className="anpr-stat-label">Detections Today</div>
        </div>
        <div className="anpr-stat-card">
          <div className="anpr-stat-val anpr-stat-green">{stats?.confirmed_today ?? '—'}</div>
          <div className="anpr-stat-label">Confirmed Plates</div>
        </div>
        <div className="anpr-stat-card">
          <div className={`anpr-stat-val ${(stats?.watchlist_matches_today ?? 0) > 0 ? 'anpr-stat-red' : ''}`}>
            {stats?.watchlist_matches_today ?? '—'}
          </div>
          <div className="anpr-stat-label">Watchlist Matches</div>
        </div>
        <div className="anpr-stat-card">
          <div className="anpr-stat-val anpr-stat-blue">{stats?.total_all_time ?? '—'}</div>
          <div className="anpr-stat-label">Total All Time</div>
        </div>
      </div>

      {/* ── Tab Bar ──────────────────────────────────────────────────────────────  */}
      <div className="anpr-tab-bar">
        <button
          className={`anpr-tab ${activeTab === 'detections' ? 'anpr-tab-active' : ''}`}
          onClick={() => setActiveTab('detections')}
        >
          🚗 ANPR Detections
        </button>
        <button
          className={`anpr-tab ${activeTab === 'watchlist' ? 'anpr-tab-active' : ''}`}
          onClick={() => setActiveTab('watchlist')}
        >
          🛡 Plate Watchlist
        </button>
      </div>

      {activeTab === 'watchlist' ? (
        <WatchlistManager />
      ) : (
        <>
          {/* ── Filter Toolbar ────────────────────────────────────────────────────  */}
          <div className="anpr-filters">
            <input
              id="anpr-plate-search"
              className="anpr-input"
              placeholder="🔍 Search plate…"
              value={plateQuery}
              onChange={e => { setPlateQuery(e.target.value.toUpperCase()); setOffset(0); }}
            />
            <select id="anpr-vtype-filter" className="anpr-input" value={vehicleType} onChange={e => { setVehicleType(e.target.value); setOffset(0); }}>
              {VEHICLE_TYPES.map(t => <option key={t}>{t}</option>)}
            </select>
            <select id="anpr-camera-filter" className="anpr-input" value={cameraId} onChange={e => { setCameraId(e.target.value); setOffset(0); }}>
              <option value="all">All Cameras</option>
              {cameras.map(c => <option key={c.id} value={c.camera_id}>{c.name}</option>)}
            </select>
            <select id="anpr-status-filter" className="anpr-input" value={status} onChange={e => { setStatus(e.target.value); setOffset(0); }}>
              <option value="">All Status</option>
              <option value="CONFIRMED">Confirmed</option>
              <option value="UNCERTAIN">Uncertain</option>
              <option value="WATCHLIST_MATCH">Watchlist Match</option>
            </select>
            <label className="anpr-wl-toggle">
              <input type="checkbox" checked={watchlistOnly} onChange={e => { setWatchlistOnly(e.target.checked); setOffset(0); }} />
              Watchlist Only
            </label>
            <input type="date" className="anpr-input" value={dateFrom} onChange={e => { setDateFrom(e.target.value); setOffset(0); }} title="From date" />
            <input type="date" className="anpr-input" value={dateTo} onChange={e => { setDateTo(e.target.value); setOffset(0); }} title="To date" />
            <div className="anpr-ocr-slider" title="Min OCR confidence">
              <label>OCR ≥ {minOcr}%</label>
              <input type="range" min={0} max={100} step={5} value={minOcr} onChange={e => { setMinOcr(Number(e.target.value)); setOffset(0); }} />
            </div>
            <select id="anpr-sort" className="anpr-input" value={sort} onChange={e => setSort(e.target.value)}>
              <option value="newest">Newest First</option>
              <option value="oldest">Oldest First</option>
            </select>
            <button className="anpr-reset-btn" onClick={handleFilterReset}>Reset</button>
            <button className="anpr-refresh-btn" onClick={() => loadData()}>↺ Refresh</button>
          </div>

          {/* ── Summary Row ──────────────────────────────────────────────────────  */}
          <div className="anpr-summary-row">
            <span className="anpr-total-label">{total} records found</span>
            {loading && <span className="anpr-loading-spinner">Loading…</span>}
          </div>

          {/* ── Cards Grid ───────────────────────────────────────────────────────  */}
          {!loading && records.length === 0 ? (
            <div className="anpr-empty-state">
              <div className="anpr-empty-icon">🚗</div>
              <div className="anpr-empty-title">No ANPR Records Found</div>
              <div className="anpr-empty-sub">
                Records appear here in real-time when the AI surveillance pipeline detects and reads a vehicle license plate from an active camera stream.
              </div>
            </div>
          ) : (
            <div className="anpr-cards-grid" id="anpr-cards-grid">
              {records.map(rec => (
                <ANPRCard
                  key={rec.id}
                  record={rec}
                  onClick={() => setSelectedRecord(rec)}
                  onDelete={handleDeleteRecord}
                />
              ))}
            </div>
          )}

          {/* ── Pagination ───────────────────────────────────────────────────────  */}
          {totalPages > 1 && (
            <div className="anpr-pagination">
              <button className="anpr-page-btn" disabled={currentPage <= 1} onClick={() => setOffset(0)}>«</button>
              <button className="anpr-page-btn" disabled={currentPage <= 1} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>‹ Prev</button>
              <span className="anpr-page-info">Page {currentPage} of {totalPages}</span>
              <button className="anpr-page-btn" disabled={currentPage >= totalPages} onClick={() => setOffset(offset + LIMIT)}>Next ›</button>
              <button className="anpr-page-btn" disabled={currentPage >= totalPages} onClick={() => setOffset((totalPages - 1) * LIMIT)}>»</button>
            </div>
          )}
        </>
      )}

      {/* ── Evidence Modal ────────────────────────────────────────────────────── */}
      {selectedRecord && (
        <EvidenceModal
          record={selectedRecord}
          onClose={() => setSelectedRecord(null)}
          onDelete={handleDeleteRecord}
        />
      )}
    </div>
  );
}
