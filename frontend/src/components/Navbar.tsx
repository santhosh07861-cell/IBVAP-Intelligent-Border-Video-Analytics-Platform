import React, { useState, useEffect } from 'react';
import { Shield, Radio, Activity, User, LogOut, Cpu, AlertTriangle, Volume2, VolumeX } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { useWebSocket } from '../context/WebSocketContext';
import { Link, useNavigate } from 'react-router-dom';
import { isAlarmMuted, toggleAlarmMute, unlockAudioContext, playTestAlarm, isAudioArmed } from '../utils/alertSound';

const NavbarComponent: React.FC = () => {
  const { user, logout } = useAuth();
  const { isConnected, lastMessage } = useWebSocket();
  const navigate = useNavigate();
  const [timeStr, setTimeStr] = useState<string>('');
  const [muted, setMuted] = useState<boolean>(isAlarmMuted());
  const [armed, setArmed] = useState<boolean>(isAudioArmed());

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toUTCString().replace('GMT', 'UTC'));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleToggleMute = () => {
    const newMuted = toggleAlarmMute();
    setMuted(newMuted);
  };

  const inferenceMode = lastMessage?.inference_mode || "REAL AI | INFERENCE RUNNING";

  return (
    <header className="h-16 bg-[#111622] border-b border-[#252d42] px-4 flex items-center justify-between sticky top-0 z-50">
      {/* Brand Identity */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400">
          <Shield className="w-6 h-6 animate-pulse" />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-bold tracking-wider text-slate-100 text-base">IBVAP COMMAND CENTER</h1>
            <span className="bg-amber-500/10 border border-amber-500/30 text-amber-400 text-[10px] font-semibold px-2 py-0.5 rounded">
              SIH 2026 PROTOTYPE
            </span>
          </div>
          <p className="text-xs text-slate-400 font-mono">INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM</p>
        </div>
      </div>

      {/* Live System Telemetry Status */}
      <div className="hidden md:flex items-center gap-4 bg-[#0a0d14] px-4 py-1.5 rounded-lg border border-[#252d42] text-xs font-mono">
        {/* Connection Status */}
        <div className="flex items-center gap-2">
          <div className={`w-2.5 h-2.5 rounded-full ${isConnected ? 'bg-emerald-500 animate-ping' : 'bg-red-500'}`} />
          <span className={isConnected ? 'text-emerald-400' : 'text-red-400'}>
            {isConnected ? 'WEBSOCKET ONLINE' : 'DISCONNECTED'}
          </span>
        </div>

        <div className="h-4 w-px bg-[#252d42]" />

        {/* Inference Mode Indicator */}
        <div className="flex items-center gap-1.5">
          <Cpu className="w-3.5 h-3.5 text-blue-400" />
          <span className={inferenceMode.includes('REAL') ? 'text-emerald-400 font-bold' : 'text-amber-400 font-bold'}>
            {inferenceMode}
          </span>
        </div>

        <div className="h-4 w-px bg-[#252d42]" />

        {/* Alarm Sound Controls & Armed Status */}
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              if (muted) {
                const nextMuted = toggleAlarmMute();
                setMuted(nextMuted);
              }
              const ok = await unlockAudioContext();
              setArmed(ok);
            }}
            title={muted ? "Unmute Security Alarm" : armed ? "Alarm System Armed & Sound Ready" : "Click to Enable Alarm Sound"}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] font-mono transition-all border ${
              muted
                ? 'bg-slate-800 text-slate-400 border-slate-700'
                : armed
                ? 'bg-emerald-950/60 text-emerald-400 border-emerald-500/50 shadow-lg shadow-emerald-950/40'
                : 'bg-amber-950/80 text-amber-300 border-amber-500/60 animate-pulse'
            }`}
          >
            {muted ? <VolumeX className="w-3.5 h-3.5" /> : <Volume2 className="w-3.5 h-3.5" />}
            <span className="font-bold">
              {muted ? 'ALARM MUTED' : armed ? '🔊 ALARM ARMED' : '🔊 ENABLE ALARM SOUND'}
            </span>
          </button>

          <button
            onClick={async () => {
              const res = await playTestAlarm();
              if (res.success) {
                setArmed(true);
              } else {
                alert(res.message);
              }
            }}
            title="Test Alarm Audio Output"
            className="px-2 py-1 bg-red-950/60 hover:bg-red-900/60 text-red-300 border border-red-800/60 rounded text-[10px] font-mono font-bold transition-colors"
          >
            TEST ALARM
          </button>
        </div>

        <div className="h-4 w-px bg-[#252d42]" />

        {/* Time Clock */}
        <div className="text-slate-400">
          {timeStr}
        </div>
      </div>

      {/* User Info & Actions */}
      <div className="flex items-center gap-3">
        <Link
          to="/demo"
          className="hidden sm:flex items-center gap-1.5 bg-red-600/20 border border-red-500/40 text-red-300 hover:bg-red-600/30 px-3 py-1.5 rounded text-xs font-semibold tracking-wide transition-colors"
        >
          <AlertTriangle className="w-4 h-4" />
          SIH DEMO CENTER
        </Link>

        {user && (
          <div className="flex items-center gap-3 border-l border-[#252d42] pl-3">
            <div className="text-right hidden sm:block">
              <div className="text-xs font-semibold text-slate-200">{user.full_name}</div>
              <div className="text-[10px] text-blue-400 uppercase font-mono font-bold tracking-wider">{user.role}</div>
            </div>
            <button
              onClick={() => { logout(); navigate('/login'); }}
              title="Sign Out"
              className="p-2 rounded-lg bg-[#1a2030] hover:bg-red-900/30 text-slate-400 hover:text-red-400 transition-colors border border-[#252d42]"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        )}
      </div>
    </header>
  );
};

export const Navbar = React.memo(NavbarComponent);
