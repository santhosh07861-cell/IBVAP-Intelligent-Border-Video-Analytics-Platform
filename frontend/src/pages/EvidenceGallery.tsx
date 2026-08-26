import React, { useEffect, useState } from 'react';
import {
  Camera, ShieldAlert, Search, Filter, LayoutGrid, Table,
  Eye, Calendar, ArrowUpDown, RefreshCw, Cpu, Layers
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { EvidenceDetailModal } from '../components/EvidenceDetailModal';

export const EvidenceGallery: React.FC = () => {
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [viewMode, setViewMode] = useState<'grid' | 'table'>('grid');
  const [selectedItem, setSelectedItem] = useState<any | null>(null);

  // Filters & Search
  const [search, setSearch] = useState<string>('');
  const [objectFilter, setObjectFilter] = useState<string>('all');
  const [cameraFilter, setCameraFilter] = useState<string>('all');
  const [severityFilter, setSeverityFilter] = useState<string>('all');
  const [eventFilter, setEventFilter] = useState<string>('all');
  const [sortOrder, setSortOrder] = useState<'newest' | 'oldest'>('newest');

  const { token } = useAuth();

  const fetchEvidence = async () => {
    setLoading(true);
    try {
      const headers: any = {};
      const authToken = token || localStorage.getItem('ibvap_token');
      if (authToken) headers['Authorization'] = `Bearer ${authToken}`;

      const params = new URLSearchParams();
      if (objectFilter !== 'all') params.append('object_class', objectFilter);
      if (cameraFilter !== 'all') params.append('camera_id', cameraFilter);
      if (severityFilter !== 'all') params.append('severity', severityFilter);
      if (eventFilter !== 'all') params.append('event_type', eventFilter);
      if (search) params.append('search', search);
      params.append('limit', '100');

      const res = await fetch(`/api/evidence?${params.toString()}`, { headers });
      if (res.ok) {
        const data = await res.json();
        const fetchedItems = data.items || [];
        setItems(fetchedItems);
      }
    } catch (err) {
      console.error('Failed to fetch evidence history:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvidence();
  }, [objectFilter, cameraFilter, severityFilter, eventFilter, search, token]);

  const sortedItems = [...items].sort((a, b) => {
    const timeA = new Date(a.captured_at).getTime();
    const timeB = new Date(b.captured_at).getTime();
    return sortOrder === 'newest' ? timeB - timeA : timeA - timeB;
  });

  return (
    <div className="p-6 space-y-6 font-mono">
      {/* Top Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase flex items-center gap-2">
            <Cpu className="w-5 h-5 text-blue-400" /> AI DETECTION HISTORY & EVIDENCE GALLERY
          </h2>
          <p className="text-xs text-slate-400">REAL AI DETECTED OBJECTS & AUTOMATIC EVIDENCE SNAPSHOTS</p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={fetchEvidence}
            className="px-3 py-2 bg-[#1a2030] hover:bg-[#252d42] text-slate-300 rounded-lg text-xs font-semibold uppercase tracking-wider flex items-center gap-1.5 border border-[#252d42] transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> REFRESH
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
              <Table className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="bg-[#111622] p-4 rounded-xl border border-[#252d42] space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3 text-xs">
          {/* Search Input */}
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
            <option value="van">Van</option>
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
            <option value="INTRUSION">General Intrusion</option>
          </select>

          {/* Sort Order */}
          <button
            onClick={() => setSortOrder(prev => prev === 'newest' ? 'oldest' : 'newest')}
            className="bg-[#0a0d14] border border-[#252d42] rounded-lg px-3 py-2 text-slate-300 flex items-center justify-between text-xs hover:border-blue-500 transition-colors"
          >
            <span>Sort: <strong>{sortOrder === 'newest' ? 'Newest First' : 'Oldest First'}</strong></span>
            <ArrowUpDown className="w-3.5 h-3.5 text-blue-400" />
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      {loading ? (
        <div className="p-16 text-center text-slate-400 font-mono text-xs">
          Loading evidence snapshots from database...
        </div>
      ) : sortedItems.length === 0 ? (
        <div className="bg-[#111622] p-16 rounded-xl border border-[#252d42] text-center text-slate-500 space-y-2">
          <Camera className="w-8 h-8 text-slate-600 mx-auto" />
          <p className="font-bold text-slate-400 text-sm">NO AI EVIDENCE SNAPSHOTS FOUND</p>
          <p className="text-xs text-slate-500 max-w-md mx-auto">
            Connect a live camera or trigger the SIH Demo Intrusion Workflow to automatically generate real AI evidence snapshots.
          </p>
        </div>
      ) : viewMode === 'grid' ? (
        /* GRID CARDS VIEW */
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-6">
          {sortedItems.map((item) => {
            const severityColor =
              item.severity === 'CRITICAL' ? 'bg-red-500/20 text-red-400 border-red-500/40' :
              item.severity === 'HIGH' ? 'bg-amber-500/20 text-amber-400 border-amber-500/40' :
              'bg-blue-500/20 text-blue-400 border-blue-500/40';

            return (
              <div
                key={item.id}
                className="bg-[#111622] rounded-xl border border-[#252d42] hover:border-blue-500/50 transition-all overflow-hidden flex flex-col justify-between group shadow-xl"
              >
                {/* Snapshot Image Box */}
                <div className="relative aspect-video bg-slate-950 overflow-hidden cursor-pointer" onClick={() => setSelectedItem(item)}>
                  {item.file_url ? (
                    <img
                      src={item.file_url}
                      alt="AI Detection Snapshot"
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  ) : (
                    <div className="w-full h-full flex items-center justify-center text-slate-600 text-xs">
                      No Image Preview
                    </div>
                  )}

                  {/* Badges Overlays */}
                  <div className="absolute top-2 left-2 bg-blue-600/90 text-white font-bold text-[10px] px-2 py-0.5 rounded shadow uppercase">
                    {(item.object_class || 'person').toUpperCase()} {(item.confidence ? (item.confidence * 100).toFixed(0) : '90')}%
                  </div>
                  <div className="absolute top-2 right-2 bg-slate-950/90 text-amber-400 font-bold text-[10px] px-2 py-0.5 rounded border border-amber-500/40 font-mono">
                    {item.track_id || 'P-101'}
                  </div>
                </div>

                {/* Card Information Body */}
                <div className="p-4 space-y-3 flex-1 flex flex-col justify-between text-xs">
                  <div>
                    <div className="flex items-center justify-between font-bold text-slate-200 mb-1">
                      <span className="text-amber-400">{item.event_type}</span>
                      <span className={`px-2 py-0.5 rounded border text-[10px] ${severityColor}`}>
                        {item.risk_score}/100 {item.severity}
                      </span>
                    </div>

                    <div className="text-[11px] text-slate-400 space-y-1 font-mono pt-1">
                      <div>Camera: <strong className="text-blue-400">{item.camera_number || item.camera_id}</strong></div>
                      <div className="truncate">Location: <strong className="text-slate-300">{item.location}</strong></div>
                      <div>Date & Time: <strong className="text-slate-400">{new Date(item.captured_at).toLocaleString()}</strong></div>
                    </div>
                  </div>

                  <button
                    onClick={() => setSelectedItem(item)}
                    className="w-full py-2 bg-[#1a2030] hover:bg-blue-600 text-slate-300 hover:text-white rounded-lg text-xs font-bold uppercase tracking-wider flex items-center justify-center gap-1.5 border border-[#252d42] hover:border-blue-500 transition-colors"
                  >
                    <Eye className="w-3.5 h-3.5" /> VIEW DETAILS
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        /* TABLE LIST VIEW */
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
                  <th className="p-3">Date & Time</th>
                  <th className="p-3">Event</th>
                  <th className="p-3">Risk</th>
                  <th className="p-3">Track ID</th>
                  <th className="p-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#252d42] text-slate-300 font-mono">
                {sortedItems.map((item) => (
                  <tr key={item.id} className="hover:bg-[#1a2030]/60 transition-colors">
                    <td className="p-3">
                      <div className="w-14 h-10 bg-slate-950 rounded overflow-hidden cursor-pointer" onClick={() => setSelectedItem(item)}>
                        {item.file_url ? (
                          <img src={item.file_url} alt="Snapshot" className="w-full h-full object-cover" />
                        ) : (
                          <div className="w-full h-full flex items-center justify-center text-[9px] text-slate-600">N/A</div>
                        )}
                      </div>
                    </td>
                    <td className="p-3 font-bold text-blue-400 uppercase">{item.object_class}</td>
                    <td className="p-3 text-emerald-400 font-bold">{(item.confidence * 100).toFixed(0)}%</td>
                    <td className="p-3 text-blue-400 font-bold">{item.camera_number || item.camera_id}</td>
                    <td className="p-3 text-slate-400 truncate max-w-xs">{item.location}</td>
                    <td className="p-3 text-slate-400">{new Date(item.captured_at).toLocaleString()}</td>
                    <td className="p-3 text-amber-400 font-bold">{item.event_type}</td>
                    <td className="p-3 font-bold text-red-400">{item.risk_score}/100</td>
                    <td className="p-3 text-emerald-400 font-bold">{item.track_id}</td>
                    <td className="p-3 text-right">
                      <button
                        onClick={() => setSelectedItem(item)}
                        className="px-3 py-1.5 bg-blue-600/20 hover:bg-blue-600 text-blue-400 hover:text-white rounded border border-blue-500/30 text-[11px] font-bold uppercase transition-colors"
                      >
                        DETAILS
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Detailed Evidence Viewer Modal */}
      {selectedItem && (
        <EvidenceDetailModal item={selectedItem} onClose={() => setSelectedItem(null)} />
      )}
    </div>
  );
};
