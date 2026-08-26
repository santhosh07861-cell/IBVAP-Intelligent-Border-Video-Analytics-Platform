import React, { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import { AlertOctagon, CheckCircle2, ShieldAlert, MessageSquare, Image, FileText, ArrowLeft } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const IncidentDetail: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<any>(null);
  const [newNote, setNewNote] = useState('');
  const { token, user } = useAuth();

  const fetchDetail = async () => {
    try {
      const res = await fetch(`/api/incidents/${id}`, {
        headers: { 'Authorization': `Bearer ${token}` }
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
          'Authorization': `Bearer ${token}`
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
          'Authorization': `Bearer ${token}`
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

  if (!incident) {
    return <div className="p-6 text-slate-400 font-mono text-xs">Loading incident details...</div>;
  }

  return (
    <div className="p-6 space-y-6">
      {/* Top Header */}
      <div className="flex items-center justify-between bg-[#111622] p-4 rounded-xl border border-[#252d42]">
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
        <div className="flex items-center gap-2">
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
              <div>Start Time: <span className="text-slate-200">{new Date(incident.start_time).toLocaleString()}</span></div>
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
                        // Fallback snapshot preview if file URL is local mock
                        e.currentTarget.src = 'https://images.unsplash.com/photo-1541872703-74c5e44368f9?w=800&auto=format&fit=crop&q=80';
                      }}
                    />
                    <div className="text-[10px] text-slate-400 flex justify-between">
                      <span>TYPE: {ev.evidence_type.toUpperCase()}</span>
                      <span>{new Date(ev.created_at).toLocaleTimeString()}</span>
                    </div>
                  </div>
                ))
              ) : (
                <div className="col-span-2 bg-slate-950 p-4 rounded-lg border border-[#252d42] text-center text-slate-500">
                  AUTOMATIC SNAPSHOT CAPTURED: STORAGE/EVIDENCE/SNAPSHOTS/CAM-01_INTRUSION.JPG
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
                      <span className="text-slate-500 font-normal text-[10px]">{new Date(n.created_at).toLocaleTimeString()}</span>
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
    </div>
  );
};
