import React, { useEffect, useState } from 'react';
import { FileText, Search, Car } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const ANPRView: React.FC = () => {
  const [plates, setPlates] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const { token } = useAuth();

  const fetchANPR = async (q: string = '') => {
    try {
      const url = q ? `/api/anpr?plate_query=${encodeURIComponent(q)}` : '/api/anpr';
      const res = await fetch(url, {
        headers: { 'Authorization': `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setPlates(data);
      }
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
    fetchANPR();
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchANPR(query);
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 bg-[#111622] p-4 rounded-xl border border-[#252d42]">
        <div>
          <h2 className="text-lg font-bold tracking-wider text-slate-100 uppercase">ANPR AUTOMATIC NUMBER PLATE RECOGNITION</h2>
          <p className="text-xs text-slate-400 font-mono">Vehicle License Plate OCR Extraction & Search Database</p>
        </div>

        <form onSubmit={handleSearch} className="flex items-center gap-2">
          <div className="relative">
            <Search className="w-4 h-4 text-slate-500 absolute left-3 top-2.5" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search plate (e.g. RJ19)"
              className="bg-[#0a0d14] border border-[#252d42] rounded-lg pl-9 pr-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-blue-500 font-mono"
            />
          </div>
          <button type="submit" className="px-3 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-xs font-mono uppercase">
            SEARCH
          </button>
        </form>
      </div>

      <div className="bg-[#111622] rounded-xl border border-[#252d42] overflow-hidden">
        <table className="w-full text-left text-xs font-mono">
          <thead className="bg-[#0a0d14] text-slate-400 uppercase border-b border-[#252d42]">
            <tr>
              <th className="p-3">Plate Number</th>
              <th className="p-3">Plate Confidence</th>
              <th className="p-3">OCR Confidence</th>
              <th className="p-3">Vehicle Type</th>
              <th className="p-3">Camera</th>
              <th className="p-3">Timestamp</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#252d42]">
            {plates.length === 0 ? (
              <tr>
                <td colSpan={6} className="p-6 text-center text-slate-500">NO ANPR RECORDS FOUND</td>
              </tr>
            ) : (
              plates.map((p) => (
                <tr key={p.id} className="hover:bg-[#1a2030] transition-colors">
                  <td className="p-3">
                    <span className="px-2.5 py-1 bg-amber-500/10 border border-amber-500/30 text-amber-300 rounded font-bold font-mono text-xs">
                      {p.plate_text}
                    </span>
                  </td>
                  <td className="p-3 text-emerald-400 font-bold">{(p.plate_confidence * 100).toFixed(0)}%</td>
                  <td className="p-3 text-blue-400 font-bold">{(p.ocr_confidence * 100).toFixed(0)}%</td>
                  <td className="p-3 text-slate-300 uppercase">{p.vehicle_type}</td>
                  <td className="p-3 text-slate-400">{p.camera_id}</td>
                  <td className="p-3 text-slate-400">{new Date(p.timestamp).toLocaleString()}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
