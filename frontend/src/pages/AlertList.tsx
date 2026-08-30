import React, { useEffect, useState, useRef } from 'react';
import {
  Bell, CheckCircle2, ShieldAlert, Eye, Trash2, CheckSquare, Square, X, RefreshCw
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';
import { formatISTDateTime } from '../utils/timeFormat';

export const AlertList: React.FC = () => {
  const [alerts, setAlerts] = useState<any[]>([]);
  const [selectedEvidence, setSelectedEvidence] = useState<any | null>(null);
  const [alertToDelete, setAlertToDelete] = useState<any | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const { token, user } = useAuth();
  // ✅ Consume canonical shared store — latestAlerts is pre-populated by WebSocketContext
  const { latestAlerts, lastAlert } = useWebSocket();
  const initializedFromContext = useRef(false);
  const lastAlertIdRef = useRef<string | null>(null);

  const showToast = (type: 'success' | 'error', text: string) => {
    setToastMessage({ type, text });
    setTimeout(() => setToastMessage(null), 4000);
  };

  const getHeaders = () => {
    const headers: Record<string, string> = {};
    const authToken = token || localStorage.getItem('ibvap_token');
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
  };

  const fetchAlerts = async () => {
    try {
      const res = await fetch('/api/alerts?limit=100', { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setAlerts(data);
          // Sync back into the seen set so WebSocket doesn't re-add them
        }
      }
    } catch (e) {
      console.error(e);
    }
  };

  // On mount: use canonical store if already populated, otherwise HTTP fetch
  useEffect(() => {
    if (latestAlerts.length > 0 && !initializedFromContext.current) {
      initializedFromContext.current = true;
      setAlerts(latestAlerts);
    } else {
      fetchAlerts();
    }
  }, [token]);

  // Keep local state in sync when canonical store grows (new WS alerts)
  useEffect(() => {
    if (latestAlerts.length > 0) {
      setAlerts(latestAlerts);
    }
  }, [latestAlerts]);

  const handleAcknowledge = async (alertId: string) => {
    try {
      const res = await fetch(`/api/alerts/${alertId}/acknowledge`, {
        method: 'PUT',
        headers: getHeaders()
      });
      if (res.ok) {
        fetchAlerts();
        showToast('success', '✓ Alert acknowledged');
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteSingle = async () => {
    if (!alertToDelete) return;
    setIsDeleting(true);
    const targetId = alertToDelete.id || alertToDelete.alert_id;
    try {
      const res = await fetch(`/api/alerts/${targetId}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (res.ok) {
        setAlerts((prev) => prev.filter((a) => (a.id || a.alert_id) !== targetId));
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(targetId);
          return next;
        });
        showToast('success', `✓ Alert #${targetId.substring(0, 8)} permanently deleted`);
        setAlertToDelete(null);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast('error', `⚠ Failed to delete alert: ${err.detail || 'Server error'}`);
      }
    } catch (e: any) {
      console.error('Delete alert error:', e);
      showToast('error', `⚠ Error deleting alert: ${e.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    setIsDeleting(true);
    const idsArray = Array.from(selectedIds);
    try {
      const res = await fetch('/api/alerts/bulk-delete', {
        method: 'POST',
        headers: {
          ...getHeaders(),
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ alert_ids: idsArray })
      });
      if (res.ok) {
        const data = await res.json();
        const deletedSet = new Set(data.deleted_ids || idsArray);
        setAlerts((prev) => prev.filter((a) => !deletedSet.has(a.id || a.alert_id)));
        setSelectedIds(new Set());
        setShowBulkDeleteModal(false);
        showToast('success', `✓ ${deletedSet.size} alerts permanently deleted`);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast('error', `⚠ Failed bulk delete: ${err.detail || 'Server error'}`);
      }
    } catch (e: any) {
      console.error('Bulk delete error:', e);
      showToast('error', `⚠ Error bulk deleting alerts: ${e.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === alerts.length && alerts.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(alerts.map((a) => a.id || a.alert_id).filter(Boolean)));
    }
  };

  const toggleSelectItem = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="p-6 space-y-6">
      {/* Toast Notification */}
      {toastMessage && (
        <div
          className={`fixed top-4 right-4 z-[200] px-4 py-3 rounded-xl border text-xs font-mono font-bold shadow-2xl flex items-center gap-2 animate-in fade-in slide-in-from-top-3 duration-200 ${
            toastMessage.type === 'success'
              ? 'bg-emerald-950/90 border-emerald-500/50 text-emerald-300'
              : 'bg-red-950/90 border-red-500/50 text-red-300'
          }`}
        >
          <span>{toastMessage.text}</span>
          <button onClick={() => setToastMessage(null)} className="ml-2 text-slate-400 hover:text-white">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {/* Evidence Modal */}
      {selectedEvidence && (
        <EvidenceDetailModal
          item={selectedEvidence}
          onClose={() => setSelectedEvidence(null)}
        />
      )}

      {/* Top Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2">
            <Bell className="w-5 h-5 text-amber-400" /> LIVE ALERTS STREAM
          </h2>
          <p className="text-xs text-slate-400 font-mono">Real-Time Threat Notifications, Watchlist Matches & Operator Acknowledgement Queue</p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {selectedIds.size > 0 && (
            <button
              onClick={() => setShowBulkDeleteModal(true)}
              className="px-3 py-1.5 bg-red-950/60 hover:bg-red-900/80 text-red-300 border border-red-500/40 rounded-lg text-xs font-mono font-bold transition-all flex items-center gap-1.5"
            >
              <Trash2 className="w-3.5 h-3.5" />
              DELETE SELECTED ({selectedIds.size})
            </button>
          )}
          <button
            onClick={fetchAlerts}
            className="px-3 py-1.5 bg-[#1a2030] hover:bg-[#252d42] text-slate-300 rounded-lg text-xs font-mono border border-[#252d42] transition-colors"
          >
            REFRESH ALERTS
          </button>
        </div>
      </div>

      {/* Alerts Table */}
      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3 w-10 text-center">
                <button
                  onClick={toggleSelectAll}
                  className="text-slate-400 hover:text-slate-200 transition-colors"
                  title={selectedIds.size === alerts.length ? 'Deselect All' : 'Select All'}
                >
                  {alerts.length > 0 && selectedIds.size === alerts.length ? (
                    <CheckSquare className="w-4 h-4 text-red-400" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
              </th>
              <th className="p-3">Timestamp</th>
              <th className="p-3">Event Type</th>
              <th className="p-3">Camera & Location</th>
              <th className="p-3">Severity</th>
              <th className="p-3">Risk Score</th>
              <th className="p-3">Evidence</th>
              <th className="p-3">Status</th>
              <th className="p-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {alerts.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-slate-500">
                  No active security alerts recorded.
                </td>
              </tr>
            ) : (
              alerts.map((al) => {
                const alertId = al.id || al.alert_id;
                const isSelected = selectedIds.has(alertId);
                const isWatchlist = (al.event_type || '').includes('WATCHLIST') || Boolean(al.person_name);
                return (
                  <tr
                    key={alertId}
                    className={`transition-colors ${
                      isSelected
                        ? 'bg-red-950/30'
                        : isWatchlist || al.severity === 'CRITICAL'
                        ? 'bg-red-950/20 hover:bg-red-950/40'
                        : 'hover:bg-[#1a2030]'
                    }`}
                  >
                    <td className="p-3 text-center">
                      <button
                        onClick={() => toggleSelectItem(alertId)}
                        className="text-slate-400 hover:text-slate-200"
                      >
                        {isSelected ? (
                          <CheckSquare className="w-4 h-4 text-red-400" />
                        ) : (
                          <Square className="w-4 h-4" />
                        )}
                      </button>
                    </td>
                    <td className="p-3 text-slate-300 font-mono">{formatISTDateTime(al.timestamp || al.created_at)}</td>
                    <td className="p-3">
                      <div className="font-bold">
                        {isWatchlist ? (
                          <span className="text-red-400 flex items-center gap-1.5 font-extrabold">
                            <ShieldAlert className="w-3.5 h-3.5" />
                            WATCHLIST: {al.person_name || 'ENROLLED SUBJECT'}
                            {al.person_id && <span className="text-[10px] bg-red-500/30 px-1 py-0.5 rounded border border-red-500/40">ID: {al.person_id}</span>}
                          </span>
                        ) : (
                          <span className="text-amber-400">{al.event_type}</span>
                        )}
                      </div>
                    </td>
                    <td className="p-3">
                      <span className="text-blue-400 font-bold font-mono text-xs">{al.camera_display || (al.camera_number && al.camera_name ? `${al.camera_number} - ${al.camera_name}` : (al.camera_number || al.camera_id))}</span>
                      <span className="text-slate-500 block text-[10px]">{al.location || 'Campus Perimeter'}</span>
                    </td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        isWatchlist || al.severity === 'CRITICAL'
                          ? 'bg-red-500/30 text-red-300 border border-red-500/50'
                          : 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                      }`}>
                        {al.severity}
                      </span>
                    </td>
                    <td className="p-3 font-bold text-red-400">{al.risk_score || 95}/100</td>
                    <td className="p-3">
                      {al.evidence_url ? (
                        <button
                          onClick={() => setSelectedEvidence(al)}
                          className="px-2 py-1 bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 rounded text-[10px] font-bold border border-blue-500/40 flex items-center gap-1 cursor-pointer"
                        >
                          <Eye className="w-3 h-3" /> SNAPSHOT
                        </button>
                      ) : (
                        <span className="text-slate-600 text-[10px]">None</span>
                      )}
                    </td>
                    <td className="p-3">
                      {al.status === 'NEW' ? (
                        <button
                          onClick={() => handleAcknowledge(alertId)}
                          className="px-2.5 py-1 bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30 rounded text-[11px] font-semibold transition-colors flex items-center gap-1 cursor-pointer"
                        >
                          <CheckCircle2 className="w-3 h-3" /> Acknowledge
                        </button>
                      ) : (
                        <span className="text-emerald-500 text-[10px] font-bold flex items-center gap-1">
                          <CheckCircle2 className="w-3 h-3" /> ACKNOWLEDGED
                        </span>
                      )}
                    </td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => setAlertToDelete(al)}
                        className="p-1.5 rounded-lg bg-red-950/30 text-red-400 hover:bg-red-900/50 hover:text-red-300 border border-red-500/30 transition-colors"
                        title="Delete Alert"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Single Delete Confirmation Modal */}
      {alertToDelete && (
        <div className="fixed inset-0 z-[150] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE ALERT RECORD?</h3>
                  <p className="text-[11px] text-red-400/80 font-mono">PERMANENT DATABASE REMOVAL</p>
                </div>
              </div>
              <button
                onClick={() => setAlertToDelete(null)}
                disabled={isDeleting}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300">
                Are you sure you want to permanently delete this alert record from the system?
              </p>
              <div className="bg-[#0a0d14] p-3.5 rounded-xl border border-[#252d42] space-y-2 text-[11px]">
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Event:</span>
                  <strong className="text-amber-400">{alertToDelete.event_type}</strong>
                </div>
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Camera:</span>
                  <strong className="text-slate-200">{alertToDelete.camera_number || alertToDelete.camera_id}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Time:</span>
                  <span className="text-slate-200 font-mono">{formatISTDateTime(alertToDelete.timestamp || alertToDelete.created_at)}</span>
                </div>
              </div>
              <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
                ⚠ This action is permanent. An immutable audit log entry will be recorded.
              </div>
            </div>
            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setAlertToDelete(null)}
                disabled={isDeleting}
                className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteSingle}
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
                    Delete Alert
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Delete Modal */}
      {showBulkDeleteModal && (
        <div className="fixed inset-0 z-[150] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE {selectedIds.size} ALERTS?</h3>
                  <p className="text-[11px] text-red-400/80 font-mono">BULK DATABASE REMOVAL</p>
                </div>
              </div>
              <button
                onClick={() => setShowBulkDeleteModal(false)}
                disabled={isDeleting}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300">
                Are you sure you want to permanently delete <strong className="text-red-400 font-mono">{selectedIds.size}</strong> selected alert records?
              </p>
              <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
                ⚠ This action is destructive and cannot be undone. An audit log entry will be created.
              </div>
            </div>
            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setShowBulkDeleteModal(false)}
                disabled={isDeleting}
                className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleBulkDelete}
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
                    Delete All ({selectedIds.size})
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

