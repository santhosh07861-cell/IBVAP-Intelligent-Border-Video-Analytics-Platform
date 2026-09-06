import React, { useEffect, useState, useCallback } from 'react';
import {
  Link2, ShieldCheck, AlertTriangle, RefreshCw, CheckCircle2,
  XCircle, Hash, Box, Clock, Cpu, ChevronDown, ChevronUp, Database
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { formatISTDateTime } from '../utils/timeFormat';

interface AuditBlock {
  id: string;
  block_index: number;
  event_type: string;
  event_id: string;
  camera_id: string | null;
  event_data_hash: string;
  previous_hash: string;
  block_hash: string;
  timestamp: string;
  created_at: string;
}

interface ChainVerification {
  valid: boolean;
  total_blocks: number;
  verified_blocks: number;
  first_broken_at: number | null;
  broken_block_id: string | null;
  message: string;
}

interface ChainStats {
  total_blocks: number;
  blocks_by_type: Record<string, number>;
  genesis_block: { block_index: number; block_hash: string; timestamp: string } | null;
  latest_block: { block_index: number; block_hash: string; timestamp: string } | null;
  chain_description: string;
}

const EVENT_TYPE_COLORS: Record<string, string> = {
  ALERT_CREATED: 'text-red-400 bg-red-950/40 border-red-500/40',
  INCIDENT_CREATED: 'text-orange-400 bg-orange-950/40 border-orange-500/40',
  EVIDENCE_CREATED: 'text-purple-400 bg-purple-950/40 border-purple-500/40',
};

const EVENT_TYPE_LABEL: Record<string, string> = {
  ALERT_CREATED: '🚨 ALERT',
  INCIDENT_CREATED: '⚠️ INCIDENT',
  EVIDENCE_CREATED: '📸 EVIDENCE',
};

const truncateHash = (h: string, n = 16) => h ? `${h.slice(0, n)}...` : '—';

const HashBadge: React.FC<{ hash: string; label: string; color?: string }> = ({ hash, label, color = 'text-cyan-400' }) => (
  <div className="flex flex-col gap-0.5">
    <span className="text-[9px] text-slate-500 uppercase font-mono tracking-widest">{label}</span>
    <span
      className={`font-mono text-[10px] ${color} bg-slate-900/60 px-2 py-0.5 rounded border border-slate-700/40 cursor-help`}
      title={hash}
    >
      {truncateHash(hash)}
    </span>
  </div>
);

const BlockCard: React.FC<{ block: AuditBlock; isGenesis: boolean; isLatest: boolean; isBroken: boolean }> = ({
  block, isGenesis, isLatest, isBroken
}) => {
  const [expanded, setExpanded] = useState(false);
  const typeStyle = EVENT_TYPE_COLORS[block.event_type] || 'text-blue-400 bg-blue-950/40 border-blue-500/40';
  const typeLabel = EVENT_TYPE_LABEL[block.event_type] || block.event_type;

  return (
    <div className={`relative rounded-xl border transition-all duration-200 ${
      isBroken
        ? 'border-red-500/60 bg-red-950/20 shadow-lg shadow-red-950/30'
        : isGenesis
        ? 'border-emerald-500/40 bg-emerald-950/10'
        : 'border-[#252d42] bg-[#111622] hover:border-blue-500/30'
    }`}>

      {/* Block header */}
      <div className="flex items-start justify-between p-4 gap-3">
        <div className="flex items-center gap-3 min-w-0">
          {/* Block index badge */}
          <div className={`w-12 h-12 rounded-lg flex flex-col items-center justify-center shrink-0 border font-mono ${
            isBroken ? 'bg-red-900/40 border-red-500/50 text-red-300'
              : isGenesis ? 'bg-emerald-900/30 border-emerald-500/40 text-emerald-300'
              : 'bg-[#0a0d14] border-[#252d42] text-slate-300'
          }`}>
            <Box className="w-3 h-3 mb-0.5 opacity-60" />
            <span className="text-[11px] font-bold">#{block.block_index}</span>
          </div>

          <div className="min-w-0">
            {/* Event type tag */}
            <div className="flex items-center gap-2 mb-1 flex-wrap">
              <span className={`px-2 py-0.5 rounded text-[10px] font-bold border font-mono ${typeStyle}`}>
                {typeLabel}
              </span>
              {isGenesis && (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold border border-emerald-500/40 text-emerald-400 bg-emerald-900/30 font-mono">
                  GENESIS
                </span>
              )}
              {isLatest && !isGenesis && (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold border border-blue-500/40 text-blue-400 bg-blue-900/30 font-mono">
                  LATEST
                </span>
              )}
              {isBroken && (
                <span className="px-2 py-0.5 rounded text-[10px] font-bold border border-red-500/40 text-red-400 bg-red-900/30 font-mono animate-pulse">
                  ⚠ CHAIN BROKEN
                </span>
              )}
            </div>

            {/* Event ID */}
            <p className="text-[10px] font-mono text-slate-500 truncate" title={block.event_id}>
              EVENT: {block.event_id}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right">
            <div className="flex items-center gap-1 text-[10px] text-slate-500 font-mono justify-end">
              <Clock className="w-3 h-3" />
              {formatISTDateTime(block.timestamp)}
            </div>
            {block.camera_id && (
              <div className="text-[10px] text-slate-600 font-mono mt-0.5 text-right">
                CAM: {block.camera_id.slice(0, 12)}...
              </div>
            )}
          </div>
          <button
            onClick={() => setExpanded(v => !v)}
            className="text-slate-500 hover:text-slate-300 transition-colors p-1"
          >
            {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Hash chain mini-view */}
      <div className="px-4 pb-3 flex gap-4 flex-wrap">
        <HashBadge hash={block.previous_hash} label="prev hash" color="text-slate-400" />
        <div className="flex items-center text-slate-600 pt-4">→</div>
        <HashBadge hash={block.event_data_hash} label="event hash" color="text-amber-400" />
        <div className="flex items-center text-slate-600 pt-4">⊕</div>
        <HashBadge hash={block.block_hash} label="block hash" color="text-cyan-400" />
      </div>

      {/* Expanded details */}
      {expanded && (
        <div className="border-t border-[#252d42] px-4 py-3 space-y-2">
          <p className="text-[9px] text-slate-500 uppercase font-mono tracking-widest mb-2">Full Hash Details</p>
          <div className="grid gap-2">
            {[
              { label: 'BLOCK ID', value: block.id, color: 'text-slate-300' },
              { label: 'PREV HASH (chain link)', value: block.previous_hash, color: 'text-slate-400' },
              { label: 'EVENT DATA HASH (SHA-256 of event payload)', value: block.event_data_hash, color: 'text-amber-400' },
              { label: 'BLOCK HASH = SHA-256(event_hash + prev_hash)', value: block.block_hash, color: 'text-cyan-400' },
            ].map(({ label, value, color }) => (
              <div key={label} className="flex flex-col gap-0.5">
                <span className="text-[9px] text-slate-600 font-mono">{label}</span>
                <span className={`text-[11px] font-mono ${color} break-all bg-[#0a0d14] rounded p-2 border border-[#1e2535]`}>
                  {value}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// Connector between blocks visualizing the chain link
const ChainConnector: React.FC<{ isBroken: boolean }> = ({ isBroken }) => (
  <div className="flex items-center justify-center my-1">
    <div className={`flex flex-col items-center gap-0 ${isBroken ? 'text-red-500' : 'text-slate-700'}`}>
      <div className={`w-px h-3 ${isBroken ? 'bg-red-500/60' : 'bg-slate-700'}`} />
      <Link2 className={`w-3.5 h-3.5 ${isBroken ? 'text-red-500 animate-pulse' : 'text-slate-600'}`} />
      <div className={`w-px h-3 ${isBroken ? 'bg-red-500/60' : 'bg-slate-700'}`} />
    </div>
  </div>
);

export const BlockchainAudit: React.FC = () => {
  const [blocks, setBlocks] = useState<AuditBlock[]>([]);
  const [verification, setVerification] = useState<ChainVerification | null>(null);
  const [stats, setStats] = useState<ChainStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [verifying, setVerifying] = useState(false);
  const [filterType, setFilterType] = useState<string>('ALL');
  const { token } = useAuth();

  const headers = useCallback(() => {
    const h: Record<string, string> = {};
    const t = token || localStorage.getItem('ibvap_token');
    if (t) h['Authorization'] = `Bearer ${t}`;
    return h;
  }, [token]);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [chainRes, verifyRes, statsRes] = await Promise.all([
        fetch('/api/blockchain/chain?limit=200', { headers: headers() }),
        fetch('/api/blockchain/verify', { headers: headers() }),
        fetch('/api/blockchain/stats', { headers: headers() }),
      ]);

      if (chainRes.ok) {
        const d = await chainRes.json();
        setBlocks(d.blocks || []);
      }
      if (verifyRes.ok) setVerification(await verifyRes.json());
      if (statsRes.ok) setStats(await statsRes.json());
    } catch (e) {
      console.error('Blockchain fetch error', e);
    } finally {
      setLoading(false);
    }
  }, [headers]);

  const runVerify = async () => {
    setVerifying(true);
    try {
      const res = await fetch('/api/blockchain/verify', { headers: headers() });
      if (res.ok) setVerification(await res.json());
    } finally {
      setVerifying(false);
    }
  };

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const filteredBlocks = filterType === 'ALL'
    ? blocks
    : blocks.filter(b => b.event_type === filterType);

  const brokenAt = verification?.first_broken_at ?? null;

  return (
    <div className="p-6 space-y-6">

      {/* ── Header Banner ── */}
      <div className="bg-[#111622] border border-[#252d42] rounded-xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-xl bg-cyan-600/15 border border-cyan-500/30 flex items-center justify-center shrink-0">
            <Hash className="w-6 h-6 text-cyan-400" />
          </div>
          <div>
            <h2 className="text-base sm:text-lg font-bold tracking-wider text-slate-100 uppercase font-mono flex items-center gap-2">
              BLOCKCHAIN AUDIT TRAIL
              {verification && (
                <span className={`text-xs px-2 py-0.5 rounded-full border font-bold ${
                  verification.valid
                    ? 'text-emerald-400 border-emerald-500/40 bg-emerald-950/30'
                    : 'text-red-400 border-red-500/40 bg-red-950/30 animate-pulse'
                }`}>
                  {verification.valid ? '✓ CHAIN INTACT' : '⚠ CHAIN BROKEN'}
                </span>
              )}
            </h2>
            <p className="text-xs text-slate-400 font-mono mt-0.5">
              SHA-256 Hash Chain · Tamper-Evident Security Event Log · Blockchain & Cybersecurity Theme
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <button
            onClick={runVerify}
            disabled={verifying}
            className="flex items-center gap-2 px-4 py-2 bg-cyan-700 hover:bg-cyan-600 disabled:opacity-50 text-white rounded-lg text-xs font-bold uppercase font-mono tracking-wider transition-all"
          >
            <ShieldCheck className={`w-4 h-4 ${verifying ? 'animate-spin' : ''}`} />
            {verifying ? 'VERIFYING...' : 'VERIFY CHAIN'}
          </button>
          <button
            onClick={fetchAll}
            disabled={loading}
            className="p-2 bg-[#1a2030] hover:bg-[#252d42] text-slate-400 rounded-lg border border-[#252d42] transition-all"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* ── Verification Status Banner ── */}
      {verification && (
        <div className={`rounded-xl border p-4 flex items-start gap-3 ${
          verification.valid
            ? 'border-emerald-500/40 bg-emerald-950/20'
            : 'border-red-500/50 bg-red-950/20'
        }`}>
          {verification.valid
            ? <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
            : <XCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5 animate-pulse" />
          }
          <div>
            <p className={`text-sm font-bold font-mono ${verification.valid ? 'text-emerald-300' : 'text-red-300'}`}>
              {verification.message}
            </p>
            <p className="text-xs text-slate-500 font-mono mt-1">
              Total blocks: {verification.total_blocks} · Verified: {verification.verified_blocks}
              {verification.first_broken_at !== null && ` · TAMPER DETECTED at block #${verification.first_broken_at}`}
            </p>
          </div>
        </div>
      )}

      {/* ── Stats KPI Row ── */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          <div className="bg-[#111622] border border-[#252d42] rounded-xl p-4">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-mono text-slate-400 uppercase">Total Blocks</span>
              <Database className="w-3.5 h-3.5 text-cyan-400" />
            </div>
            <div className="text-2xl font-bold font-mono text-cyan-400">{stats.total_blocks}</div>
          </div>
          {Object.entries(stats.blocks_by_type).map(([type, count]) => (
            <div key={type} className="bg-[#111622] border border-[#252d42] rounded-xl p-4">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] font-mono text-slate-400 uppercase">
                  {EVENT_TYPE_LABEL[type] || type}
                </span>
                <Box className="w-3.5 h-3.5 text-slate-500" />
              </div>
              <div className={`text-2xl font-bold font-mono ${
                type === 'ALERT_CREATED' ? 'text-red-400'
                  : type === 'INCIDENT_CREATED' ? 'text-orange-400'
                  : 'text-purple-400'
              }`}>{count}</div>
            </div>
          ))}
          <div className="bg-[#111622] border border-[#252d42] rounded-xl p-4 sm:col-span-1 col-span-2">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-mono text-slate-400 uppercase">Chain Algorithm</span>
              <Cpu className="w-3.5 h-3.5 text-amber-400" />
            </div>
            <div className="text-sm font-bold font-mono text-amber-400">SHA-256</div>
            <div className="text-[10px] font-mono text-slate-600 mt-0.5">Hash-Chain · Tamper-Evident</div>
          </div>
        </div>
      )}

      {/* ── How It Works Panel ── */}
      <div className="bg-[#111622] border border-cyan-500/20 rounded-xl p-5">
        <h3 className="text-xs font-bold font-mono text-cyan-400 uppercase tracking-widest mb-3 flex items-center gap-2">
          <Hash className="w-4 h-4" /> HOW THE HASH CHAIN WORKS
        </h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs font-mono text-slate-400">
          <div className="space-y-1">
            <div className="text-amber-400 font-bold mb-1">① EVENT DATA HASH</div>
            <code className="block bg-[#0a0d14] rounded p-2 text-[10px] text-amber-300 border border-[#1e2535]">
              event_data_hash =<br/>SHA256(canonical_json(<br/>  event_payload<br/>))
            </code>
            <p className="text-slate-500 text-[10px] leading-relaxed">Fingerprints the exact alert or incident payload. Any change to event data changes this hash.</p>
          </div>
          <div className="space-y-1">
            <div className="text-cyan-400 font-bold mb-1">② BLOCK HASH (CHAIN LINK)</div>
            <code className="block bg-[#0a0d14] rounded p-2 text-[10px] text-cyan-300 border border-[#1e2535]">
              block_hash =<br/>SHA256(<br/>  event_data_hash +<br/>  previous_hash<br/>)
            </code>
            <p className="text-slate-500 text-[10px] leading-relaxed">Each block is chained to the previous. Tampering any block invalidates all subsequent hashes.</p>
          </div>
          <div className="space-y-1">
            <div className="text-emerald-400 font-bold mb-1">③ GENESIS BLOCK</div>
            <code className="block bg-[#0a0d14] rounded p-2 text-[10px] text-emerald-300 border border-[#1e2535]">
              genesis.previous_hash =<br/>'0000...0000'<br/>(64 zeros)
            </code>
            <p className="text-slate-500 text-[10px] leading-relaxed">The first block anchors the chain to a known sentinel value. Every subsequent block links back to genesis.</p>
          </div>
        </div>
      </div>

      {/* ── Filter Bar ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-[10px] font-mono text-slate-500 uppercase">Filter:</span>
        {['ALL', 'ALERT_CREATED', 'INCIDENT_CREATED', 'EVIDENCE_CREATED'].map(f => (
          <button
            key={f}
            onClick={() => setFilterType(f)}
            className={`px-3 py-1 rounded text-[10px] font-bold font-mono border transition-all ${
              filterType === f
                ? 'bg-cyan-700 text-white border-cyan-600'
                : 'bg-[#111622] text-slate-400 border-[#252d42] hover:border-cyan-500/40'
            }`}
          >
            {EVENT_TYPE_LABEL[f] || f}
          </button>
        ))}
        <span className="text-[10px] font-mono text-slate-600 ml-auto">
          {filteredBlocks.length} block{filteredBlocks.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* ── Chain Visualization ── */}
      {loading ? (
        <div className="flex flex-col items-center justify-center py-24 gap-4">
          <RefreshCw className="w-8 h-8 text-cyan-500 animate-spin" />
          <p className="text-slate-500 font-mono text-sm">Loading audit chain...</p>
        </div>
      ) : filteredBlocks.length === 0 ? (
        <div className="bg-[#111622] border border-[#252d42] rounded-xl p-16 text-center">
          <Hash className="w-10 h-10 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500 font-mono text-sm">No audit blocks yet.</p>
          <p className="text-slate-600 font-mono text-xs mt-2">
            Blocks are created automatically when AI detects security events (alerts, incidents).
          </p>
        </div>
      ) : (
        <div className="space-y-0">
          {filteredBlocks.map((block, idx) => {
            const isGenesis = block.block_index === 0;
            const isLatest = idx === 0;
            const isBroken = brokenAt !== null && block.block_index >= brokenAt;
            const showConnector = idx < filteredBlocks.length - 1;

            return (
              <React.Fragment key={block.id}>
                <BlockCard
                  block={block}
                  isGenesis={isGenesis}
                  isLatest={isLatest}
                  isBroken={isBroken}
                />
                {showConnector && (
                  <ChainConnector isBroken={isBroken} />
                )}
              </React.Fragment>
            );
          })}
        </div>
      )}

      {/* ── Genesis anchor note ── */}
      {filteredBlocks.length > 0 && (
        <div className="flex items-center gap-2 text-[10px] font-mono text-slate-600 justify-center pb-4">
          <div className="w-8 h-px bg-slate-700" />
          <span>↑ GENESIS ANCHOR — Chain starts here</span>
          <div className="w-8 h-px bg-slate-700" />
        </div>
      )}
    </div>
  );
};

export default BlockchainAudit;
