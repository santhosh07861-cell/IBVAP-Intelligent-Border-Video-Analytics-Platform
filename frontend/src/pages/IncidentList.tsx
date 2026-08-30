import React, { useEffect, useState } from 'react';
import {
  AlertOctagon, ArrowUpRight, Trash2, CheckSquare, Square, X, RefreshCw
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { formatISTDateTime } from '../utils/timeFormat';

export const IncidentList: React.FC = () => {
  const [incidents, setIncidents] = useState<any[]>([]);
  const [incidentToDelete, setIncidentToDelete] = useState<any | null>(null);
  const [isDeleting, setIsDeleting] = useState<boolean>(false);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const { token } = useAuth();
  const { lastIncident } = useWebSocket();

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

  const fetchIncidents = async () => {
    try {
      const res = await fetch('/api/incidents?limit=100', {
        headers: getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        setIncidents(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  // Full fetch on mount only
  useEffect(() => {
    fetchIncidents();
  }, [token]);

  // ✅ Optimistic prepend when INCIDENT_NEW fires via WebSocket
  // Avoids full re-fetch race condition against SQLite WAL commit
  useEffect(() => {
    if (lastIncident) {
      const incidentId = lastIncident.id || lastIncident.incident_id;
      setIncidents(prev => {
        // Deduplicate by id
        const filtered = prev.filter(i => i.id !== incidentId);
        // Build a normalized incident object from the WS payload
        const newInc = {
          id: lastIncident.id || lastIncident.incident_id,
          incident_number: lastIncident.incident_number,
          camera_id: lastIncident.camera_id,
          camera_number: lastIncident.camera_number,
          camera_name: lastIncident.camera_name,
          camera_display: lastIncident.camera_display ||
            (lastIncident.camera_number && lastIncident.camera_name
              ? `${lastIncident.camera_number} - ${lastIncident.camera_name}`
              : lastIncident.camera_number || lastIncident.camera_id),
          title: lastIncident.title,
          description: lastIncident.description,
          severity: lastIncident.severity,
          risk_score: lastIncident.risk_score,
          status: lastIncident.status || 'NEW',
          start_time: lastIncident.start_time || lastIncident.created_at,
          created_at: lastIncident.created_at || lastIncident.start_time,
          alert_id: lastIncident.alert_id,
          event_id: lastIncident.event_id,
          evidence_url: lastIncident.evidence_url,
        };
        return [newInc, ...filtered];
      });
    }
  }, [lastIncident]);

  const handleDeleteSingle = async () => {
    if (!incidentToDelete) return;
    setIsDeleting(true);
    const targetId = incidentToDelete.id;
    const targetNum = incidentToDelete.incident_number;
    try {
      const res = await fetch(`/api/incidents/${targetId}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (res.ok) {
        setIncidents((prev) => prev.filter((i) => i.id !== targetId));
        setSelectedIds((prev) => {
          const next = new Set(prev);
          next.delete(targetId);
          return next;
        });
        showToast('success', `✓ Incident ${targetNum} permanently deleted`);
        setIncidentToDelete(null);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast('error', `⚠ Failed to delete incident: ${err.detail || 'Server error'}`);
      }
    } catch (e: any) {
      console.error('Delete incident error:', e);
      showToast('error', `⚠ Error deleting incident: ${e.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedIds.size === 0) return;
    setIsDeleting(true);
    const idsArray = Array.from(selectedIds);
    try {
      const res = await fetch('/api/incidents/bulk-delete', {
        method: 'POST',
        headers: {
          ...getHeaders(),
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ incident_ids: idsArray })
      });
      if (res.ok) {
        const data = await res.json();
        const deletedSet = new Set(data.deleted_ids || idsArray);
        setIncidents((prev) => prev.filter((i) => !deletedSet.has(i.id)));
        setSelectedIds(new Set());
        setShowBulkDeleteModal(false);
        showToast('success', `✓ ${deletedSet.size} incidents permanently deleted`);
      } else {
        const err = await res.json().catch(() => ({}));
        showToast('error', `⚠ Failed bulk delete: ${err.detail || 'Server error'}`);
      }
    } catch (e: any) {
      console.error('Bulk delete error:', e);
      showToast('error', `⚠ Error bulk deleting incidents: ${e.message}`);
    } finally {
      setIsDeleting(false);
    }
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === incidents.length && incidents.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(incidents.map((i) => i.id).filter(Boolean)));
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

      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2">
            <AlertOctagon className="w-5 h-5 text-red-400" /> INCIDENT MANAGEMENT
          </h2>
          <p className="text-xs text-slate-400 font-mono">Correlated Security Incidents, Investigation & Resolution Workflows</p>
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
            onClick={fetchIncidents}
            className="px-3 py-1.5 bg-[#1a2030] hover:bg-[#252d42] text-slate-300 rounded-lg text-xs font-mono border border-[#252d42] transition-colors"
          >
            REFRESH INCIDENTS
          </button>
        </div>
      </div>

      {/* Incidents Table */}
      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3 w-10 text-center">
                <button
                  onClick={toggleSelectAll}
                  className="text-slate-400 hover:text-slate-200 transition-colors"
                  title={selectedIds.size === incidents.length ? 'Deselect All' : 'Select All'}
                >
                  {incidents.length > 0 && selectedIds.size === incidents.length ? (
                    <CheckSquare className="w-4 h-4 text-red-400" />
                  ) : (
                    <Square className="w-4 h-4" />
                  )}
                </button>
              </th>
              <th className="p-3">Incident #</th>
              <th className="p-3">Title</th>
              <th className="p-3">Camera</th>
              <th className="p-3">Severity</th>
              <th className="p-3">Risk Score</th>
              <th className="p-3">Status</th>
              <th className="p-3">Created</th>
              <th className="p-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {incidents.length === 0 ? (
              <tr>
                <td colSpan={9} className="p-8 text-center text-slate-500">
                  No security incidents recorded.
                </td>
              </tr>
            ) : (
              incidents.map((inc) => {
                const isSelected = selectedIds.has(inc.id);
                return (
                  <tr
                    key={inc.id}
                    className={`transition-colors ${
                      isSelected ? 'bg-red-950/30' : 'hover:bg-[#1a2030]'
                    }`}
                  >
                    <td className="p-3 text-center">
                      <button
                        onClick={() => toggleSelectItem(inc.id)}
                        className="text-slate-400 hover:text-slate-200"
                      >
                        {isSelected ? (
                          <CheckSquare className="w-4 h-4 text-red-400" />
                        ) : (
                          <Square className="w-4 h-4" />
                        )}
                      </button>
                    </td>
                    <td className="p-3 font-bold text-blue-400">{inc.incident_number}</td>
                    <td className="p-3 text-slate-200">{inc.title}</td>
                    <td className="p-3 text-slate-400 font-mono text-xs">{inc.camera_display || inc.camera_number || inc.camera_id}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        inc.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400' : 'bg-amber-500/20 text-amber-400'
                      }`}>
                        {inc.severity}
                      </span>
                    </td>
                    <td className="p-3 font-bold text-red-400">{inc.risk_score}/100</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                        inc.status === 'NEW' ? 'bg-red-500/20 text-red-400' :
                        inc.status === 'RESOLVED' ? 'bg-emerald-500/20 text-emerald-400' : 'bg-amber-500/20 text-amber-400'
                      }`}>
                        {inc.status}
                      </span>
                    </td>
                    <td className="p-3 text-slate-300 font-mono">{formatISTDateTime(inc.start_time || inc.created_at)}</td>
                    <td className="p-3 text-right">
                      <div className="flex items-center justify-end gap-1.5">
                        <Link
                          to={`/incidents/${inc.id}`}
                          className="px-2.5 py-1 bg-blue-600/20 text-blue-300 border border-blue-500/30 rounded text-[11px] font-semibold hover:bg-blue-600/30 transition-colors flex items-center gap-1"
                        >
                          INVESTIGATE <ArrowUpRight className="w-3 h-3" />
                        </Link>
                        <button
                          onClick={() => setIncidentToDelete(inc)}
                          className="p-1.5 rounded-lg bg-red-950/30 text-red-400 hover:bg-red-900/50 hover:text-red-300 border border-red-500/30 transition-colors"
                          title="Delete Incident"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Single Delete Modal */}
      {incidentToDelete && (
        <div className="fixed inset-0 z-[150] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE INCIDENT?</h3>
                  <p className="text-[11px] text-red-400/80 font-mono">{incidentToDelete.incident_number}</p>
                </div>
              </div>
              <button
                onClick={() => setIncidentToDelete(null)}
                disabled={isDeleting}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300">
                Are you sure you want to permanently delete incident <strong className="text-blue-400">{incidentToDelete.incident_number}</strong>?
              </p>
              <div className="bg-[#0a0d14] p-3.5 rounded-xl border border-[#252d42] space-y-2 text-[11px]">
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Title:</span>
                  <span className="text-slate-200 truncate max-w-[220px]">{incidentToDelete.title}</span>
                </div>
                <div className="flex justify-between border-b border-[#1a2030] pb-1.5">
                  <span className="text-slate-400">Camera:</span>
                  <strong className="text-slate-200">{incidentToDelete.camera_id}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-400">Severity:</span>
                  <span className="text-red-400 font-bold">{incidentToDelete.severity}</span>
                </div>
              </div>
              <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
                ⚠ This action is permanent and creates an immutable audit trail.
              </div>
            </div>
            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setIncidentToDelete(null)}
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
                    Delete Incident
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
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE {selectedIds.size} INCIDENTS?</h3>
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
                Are you sure you want to permanently delete <strong className="text-red-400 font-mono">{selectedIds.size}</strong> selected incident records?
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

