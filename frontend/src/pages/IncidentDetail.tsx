import React, { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { AlertOctagon, CheckCircle2, ShieldAlert, MessageSquare, Image, FileText, ArrowLeft, Trash2, X, RefreshCw } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { formatISTDateTime, formatISTTime } from '../utils/timeFormat';

export const IncidentDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [incident, setIncident] = useState<any>(null);
  const [newNote, setNewNote] = useState('');
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const { token, user } = useAuth();

  const getHeaders = () => {
    const headers: Record<string, string> = {};
    const authToken = token || localStorage.getItem('ibvap_token');
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
  };

  const fetchDetail = async () => {
    try {
      const res = await fetch(`/api/incidents/${id}`, {
        headers: getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        setIncident(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchDetail();
  }, [id]);

  const handleUpdateStatus = async (status: string) => {
    try {
      const res = await fetch(`/api/incidents/${id}/status`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
          ...getHeaders()
        },
        body: JSON.stringify({ status })
      });
      if (res.ok) {
        fetchDetail();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleAddNote = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newNote.trim()) return;
    try {
      const res = await fetch(`/api/incidents/${id}/notes`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...getHeaders()
        },
        body: JSON.stringify({ note_text: newNote })
      });
      if (res.ok) {
        setNewNote('');
        fetchDetail();
      }
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteIncident = async () => {
    setIsDeleting(true);
    try {
      const res = await fetch(`/api/incidents/${id}`, {
        method: 'DELETE',
        headers: getHeaders()
      });
      if (res.ok) {
        navigate('/incidents');
      } else {
        const err = await res.json().catch(() => ({}));
        alert(`Failed to delete incident: ${err.detail || 'Server error'}`);
      }
    } catch (e: any) {
      console.error('Delete incident error:', e);
      alert(`Error deleting incident: ${e.message}`);
    } finally {
      setIsDeleting(false);
      setShowDeleteModal(false);
    }
  };

  if (!incident) {
    return <div className="p-6 text-slate-400 font-mono text-xs">Loading incident details...</div>;
  }

  return (
    <div className="p-6 space-y-6">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div className="flex items-center gap-3">
          <Link to="/incidents" className="p-2 bg-[#1a2030] hover:bg-slate-800 rounded-lg text-slate-300 transition-colors border border-[#252d42]">
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">{incident.incident_number}</h2>
              <span className={`px-2 py-0.5 rounded text-xs font-bold ${
                incident.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border border-red-500/30' : 'bg-amber-500/20 text-amber-400'
              }`}>
                {incident.severity} ({incident.risk_score}/100 RISK)
              </span>
            </div>
            <p className="text-xs text-slate-400 font-mono mt-0.5">{incident.title}</p>
          </div>
        </div>

        {/* Workflow Action Buttons */}
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => handleUpdateStatus('INVESTIGATING')}
            className="px-3 py-1.5 bg-blue-600/20 border border-blue-500/40 text-blue-300 hover:bg-blue-600/30 text-xs font-semibold rounded transition-colors"
          >
            INVESTIGATE
          </button>
          <button
            onClick={() => handleUpdateStatus('RESOLVED')}
            className="px-3 py-1.5 bg-emerald-600/20 border border-emerald-500/40 text-emerald-300 hover:bg-emerald-600/30 text-xs font-semibold rounded transition-colors"
          >
            RESOLVE
          </button>
          <button
            onClick={() => handleUpdateStatus('FALSE_POSITIVE')}
            className="px-3 py-1.5 bg-slate-800 border border-slate-700 text-slate-300 hover:bg-slate-700 text-xs font-semibold rounded transition-colors"
          >
            MARK FALSE POSITIVE
          </button>
          <button
            onClick={() => setShowDeleteModal(true)}
            className="px-3 py-1.5 bg-red-950/40 border border-red-500/40 text-red-400 hover:bg-red-900/60 hover:text-red-300 text-xs font-semibold rounded transition-colors flex items-center gap-1.5"
            title="Delete Incident"
          >
            <Trash2 className="w-3.5 h-3.5" />
            DELETE
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Details & Evidence */}
        <div className="lg:col-span-2 space-y-6">
          {/* Description & Metadata */}
          <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-3 font-mono text-xs">
            <h3 className="font-bold text-slate-200 uppercase">INCIDENT DETAILS & TIMELINE</h3>
            <p className="text-slate-300">{incident.description}</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 pt-2 text-[11px] text-slate-400 border-t border-[#252d42]">
              <div>Camera: <span className="text-blue-400 font-bold">{incident.camera_id}</span></div>
              <div>Start Time: <span className="text-slate-200 font-mono">{formatISTDateTime(incident.start_time || incident.created_at)}</span></div>
              <div>Status: <span className="text-emerald-400 font-bold">{incident.status}</span></div>
            </div>
          </div>

          {/* Captured Evidence Section */}
          <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-3 font-mono text-xs">
            <h3 className="font-bold text-slate-200 uppercase flex items-center gap-2">
              <Image className="w-4 h-4 text-blue-400" />
              CAPTURED EVIDENCE SNAPSHOTS & VIDEO CLIPS
            </h3>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {incident.evidence && incident.evidence.length > 0 ? (
                incident.evidence.map((ev: any) => (
                  <div key={ev.id} className="bg-slate-950 p-2 rounded-lg border border-[#252d42] space-y-2">
                    <img
                      src={ev.file_url}
                      alt="Captured Evidence"
                      className="w-full aspect-video object-cover rounded border border-[#252d42]"
                      onError={(e) => {
                        e.currentTarget.src = 'https://images.unsplash.com/photo-1541872703-74c5e44368f9?w=800&auto=format&fit=crop&q=80';
                      }}
                    />
                    <div className="text-[10px] text-slate-400 flex justify-between">
                      <span>TYPE: {(ev.evidence_type || 'SNAPSHOT').toUpperCase()}</span>
                      <span className="font-mono">{formatISTTime(ev.created_at)}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="col-span-2 bg-slate-950 p-4 rounded-lg border border-[#252d42] text-center text-slate-500">
                  NO ATTACHED EVIDENCE SNAPSHOTS FOR THIS INCIDENT
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Operator Notes Timeline */}
        <div className="bg-[#111622] p-5 rounded-xl border border-[#252d42] space-y-4 flex flex-col justify-between">
          <div>
            <h3 className="font-bold text-slate-200 text-xs font-mono uppercase flex items-center gap-2 mb-3">
              <MessageSquare className="w-4 h-4 text-emerald-400" />
              OPERATOR LOGS & NOTES
            </h3>

            <div className="space-y-3 max-h-[320px] overflow-y-auto pr-1">
              {incident.notes && incident.notes.length > 0 ? (
                incident.notes.map((n: any) => (
                  <div key={n.id} className="bg-[#0a0d14] p-3 rounded-lg border border-[#252d42] text-xs font-mono space-y-1">
                    <div className="flex justify-between font-bold text-blue-400 text-[11px]">
                      <span>{n.author_name}</span>
                      <span className="text-slate-500 font-normal text-[10px] font-mono">{formatISTTime(n.created_at)}</span>
                    </div>
                    <p className="text-slate-300">{n.note_text}</p>
                  </div>
                ))
              ) : (
                <div className="text-xs text-slate-500 font-mono py-6 text-center">NO OPERATOR NOTES RECORDED</div>
              )}
            </div>
          </div>

          <form onSubmit={handleAddNote} className="space-y-2 pt-3 border-t border-[#252d42]">
            <textarea
              value={newNote}
              onChange={(e) => setNewNote(e.target.value)}
              placeholder="Add investigation note..."
              className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg p-2.5 text-xs text-slate-100 focus:outline-none focus:border-blue-500 font-mono resize-none h-20"
            />
            <button
              type="submit"
              className="w-full py-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg text-xs font-mono uppercase transition-colors"
            >
              ADD OPERATOR NOTE
            </button>
          </form>
        </div>
      </div>

      {/* Delete Incident Modal */}
      {showDeleteModal && (
        <div className="fixed inset-0 z-[150] bg-slate-950/85 backdrop-blur-sm flex items-center justify-center p-4 font-mono">
          <div className="bg-[#111622] border border-red-500/40 rounded-2xl max-w-md w-full overflow-hidden shadow-2xl space-y-0 animate-in fade-in zoom-in duration-150">
            <div className="bg-red-950/40 px-6 py-4 border-b border-red-500/30 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 bg-red-500/20 rounded-lg text-red-400 border border-red-500/30">
                  <Trash2 className="w-5 h-5" />
                </div>
                <div>
                  <h3 className="font-bold text-slate-100 text-sm tracking-wide uppercase">DELETE INCIDENT?</h3>
                  <p className="text-[11px] text-red-400/80 font-mono">{incident.incident_number}</p>
                </div>
              </div>
              <button
                onClick={() => setShowDeleteModal(false)}
                disabled={isDeleting}
                className="p-1.5 rounded-lg bg-[#0a0d14] text-slate-400 hover:text-white border border-[#252d42]"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-6 space-y-4 text-xs">
              <p className="text-slate-300">
                Are you sure you want to permanently delete incident <strong className="text-blue-400">{incident.incident_number}</strong>?
              </p>
              <div className="p-3 bg-red-950/20 border border-red-500/20 rounded-lg text-red-300 text-[11px]">
                ⚠ This action is permanent and creates an immutable audit trail.
              </div>
            </div>
            <div className="bg-[#0a0d14] px-6 py-3.5 border-t border-[#252d42] flex items-center justify-end gap-3">
              <button
                onClick={() => setShowDeleteModal(false)}
                disabled={isDeleting}
                className="px-4 py-2 bg-[#1a2030] hover:bg-slate-700 text-slate-300 rounded-lg text-xs font-bold uppercase transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleDeleteIncident}
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
    </div>
  );
};

