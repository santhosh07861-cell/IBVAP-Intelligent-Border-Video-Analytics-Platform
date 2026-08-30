import React, { useState, useEffect } from 'react';
import {
  Shield, Cpu, Volume2, VolumeX, LogOut, Clock, User, BellRing, Sparkles, Video
} from 'lucide-react';
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
      const datePart = new Intl.DateTimeFormat('en-GB', {
        weekday: 'short',
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        timeZone: 'Asia/Kolkata'
      }).format(now);
      const timePart = new Intl.DateTimeFormat('en-GB', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
        timeZone: 'Asia/Kolkata'
      }).format(now);
      setTimeStr(`${datePart} • ${timePart}`);
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  const handleToggleMute = async () => {
    if (!armed) {
      const ok = await unlockAudioContext();
      setArmed(ok);
    }
    const newMuted = toggleAlarmMute();
    setMuted(newMuted);
  };

  const handleArmAlarm = async () => {
    const ok = await unlockAudioContext();
    if (muted) {
      const newMuted = toggleAlarmMute();
      setMuted(newMuted);
    }
    setArmed(ok);
  };

  const inferenceMode = lastMessage?.inference_mode || (isConnected ? "REAL AI | ACTIVE" : "OFFLINE");

  return (
    <header className="h-16 bg-[#111622] border-b border-[#252d42] px-2.5 sm:px-4 lg:px-6 grid grid-cols-[auto_1fr_auto] items-center sticky top-0 z-50 select-none shadow-md w-full gap-1.5 sm:gap-2.5 xl:gap-4 box-border overflow-hidden">
      {/* ── LEFT: Brand Identity (Column 1) ─────────────────────────────── */}
      <div className="justify-self-start flex items-center gap-1.5 sm:gap-2 shrink-0 min-w-0">
        <div className="w-7 h-7 sm:w-8 sm:h-8 rounded-lg bg-blue-600/15 border border-blue-500/30 flex items-center justify-center text-blue-400 shrink-0 shadow-sm">
          <Shield className="w-4 h-4 animate-pulse" />
        </div>
        <div className="flex flex-col justify-center min-w-0">
          <div className="flex items-center gap-1.5">
            <h1 className="font-bold tracking-tight sm:tracking-wider text-slate-100 text-[11px] sm:text-xs xl:text-sm uppercase leading-none font-mono whitespace-nowrap">
              IBVAP COMMAND CENTER
            </h1>
            <span className="hidden 2xl:inline-block bg-blue-500/10 border border-blue-500/30 text-blue-400 text-[9px] font-semibold px-1.5 py-0.5 rounded leading-none font-mono shrink-0">
              SMART SURVEILLANCE
            </span>
          </div>
          <p className="hidden 2xl:block text-[9.5px] text-slate-400 font-mono tracking-tight leading-tight mt-0.5 whitespace-nowrap">
            REAL-TIME MULTI-CAMERA AI SURVEILLANCE
          </p>
        </div>
      </div>

      {/* ── CENTER: Telemetry Status & Real Date/Time (Column 2) ────────── */}
      <div className="justify-self-center flex items-center justify-center min-w-0 max-w-full px-0.5 sm:px-1">
        <div className="flex items-center gap-1 sm:gap-1.5 xl:gap-2 bg-[#0a0d14]/90 px-1.5 sm:px-2.5 py-1 rounded-xl border border-[#252d42] text-xs font-mono shadow-inner shrink-0 whitespace-nowrap">
          {/* Connection Status */}
          <div className="flex items-center gap-1 shrink-0" title="WebSocket Connection Status">
            <span className="relative flex h-2 w-2">
              {isConnected && (
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
              )}
              <span className={`relative inline-flex rounded-full h-2 w-2 ${isConnected ? 'bg-emerald-500' : 'bg-red-500'}`}></span>
            </span>
            <span className={`text-[10px] font-bold tracking-wide ${isConnected ? 'text-emerald-400' : 'text-red-400'}`}>
              {isConnected ? 'ONLINE' : 'OFFLINE'}
            </span>
          </div>

          <div className="h-3 w-px bg-[#252d42] shrink-0" />

          {/* Inference Mode Indicator */}
          <div className="flex items-center gap-1 shrink-0" title="Inference Engine Pipeline Status">
            <Cpu className="w-3 h-3 text-blue-400 shrink-0" />
            <span className={`text-[10px] font-bold tracking-wide ${inferenceMode.includes('REAL') || inferenceMode.includes('ACTIVE') ? 'text-emerald-400' : 'text-amber-400'}`}>
              {inferenceMode}
            </span>
          </div>

          <div className="h-3 w-px bg-[#252d42] shrink-0" />

          {/* Alarm Controls */}
          <div className="flex items-center gap-1 shrink-0">
            <button
              onClick={handleArmAlarm}
              title={armed && !muted ? "Security Alarm is ARMED and ready to sound on threat detection" : "Click to Enable Security Alarm Audio"}
              className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-[9.5px] font-mono transition-all border font-semibold cursor-pointer ${
                muted
                  ? 'bg-slate-800/80 text-slate-400 border-slate-700 hover:bg-slate-800'
                  : armed
                  ? 'bg-emerald-950/60 text-emerald-300 border-emerald-500/40 hover:bg-emerald-900/40'
                  : 'bg-amber-950/70 text-amber-300 border-amber-500/50 hover:bg-amber-900/50 animate-pulse'
              }`}
            >
              <BellRing className="w-2.5 h-2.5 sm:w-3 sm:h-3 shrink-0" />
              <span className="whitespace-nowrap">
                {muted ? 'ALARM MUTED' : armed ? 'ALARM ARMED' : 'ENABLE ALARM'}
              </span>
            </button>

            <button
              onClick={handleToggleMute}
              title={muted ? "Unmute Alarm Sound" : "Mute Alarm Sound"}
              className="p-1 rounded bg-[#1a2030] hover:bg-slate-800 text-slate-400 hover:text-slate-200 border border-[#252d42] shrink-0 cursor-pointer"
            >
              {muted ? <VolumeX className="w-3 h-3 text-red-400" /> : <Volume2 className="w-3 h-3 text-emerald-400" />}
            </button>

            <button
              onClick={async () => {
                const res = await playTestAlarm();
                if (res.success) {
                  setArmed(true);
                  setMuted(false);
                } else {
                  alert(res.message);
                }
              }}
              title="Test Security Alarm Audio Output"
              className="hidden 2xl:inline-block px-1.5 py-0.5 bg-red-950/40 hover:bg-red-900/60 text-red-300 border border-red-800/50 rounded text-[9px] font-mono font-bold uppercase transition-colors shrink-0 whitespace-nowrap cursor-pointer"
            >
              TEST SIREN
            </button>
          </div>

          <div className="h-3 w-px bg-[#252d42] shrink-0" />

          {/* Real-Time Indian Standard Time (IST) Clock — ALWAYS FULLY VISIBLE */}
          <div className="flex items-center gap-1 sm:gap-1.5 text-slate-200 text-[10px] sm:text-[10.5px] font-mono tabular-nums tracking-tight shrink-0 font-semibold" title="Current Indian Standard Time (IST)">
            <Clock className="w-3 h-3 sm:w-3.5 sm:h-3.5 text-blue-400 shrink-0" />
            <span className="whitespace-nowrap">{timeStr}</span>
          </div>
        </div>
      </div>

      {/* ── RIGHT: Demo, Live Grid, User Profile & Logout (Column 3) ─────── */}
      <div className="justify-self-end flex items-center gap-1.5 sm:gap-2 shrink-0">
        {/* SIH DEMO CENTER */}
        <Link
          to="/demo"
          className="hidden 2xl:flex items-center gap-1 bg-amber-500/10 border border-amber-500/30 text-amber-300 hover:bg-amber-500/20 px-1.5 py-0.5 rounded-lg text-[9.5px] font-bold tracking-wide font-mono transition-colors shrink-0 whitespace-nowrap"
          title="Open SIH Surveillance Simulation & Demo Center"
        >
          <Sparkles className="w-3 h-3 text-amber-400" />
          <span>SIH DEMO CENTER</span>
        </Link>

        {/* LIVE GRID */}
        <Link
          to="/surveillance"
          className="flex items-center gap-1 bg-blue-950/50 border border-blue-500/30 text-blue-300 hover:bg-blue-900/50 px-2 py-0.5 rounded-lg text-[9.5px] sm:text-[10px] font-bold tracking-wide font-mono transition-colors shadow-sm shrink-0 whitespace-nowrap"
          title="Open Live Multi-Camera Grid"
        >
          <Video className="w-3 h-3 text-blue-400" />
          <span>LIVE GRID</span>
        </Link>

        {/* User Profile & Logout */}
        <div className="flex items-center gap-1 sm:gap-1.5 border-l border-[#252d42] pl-1.5 sm:pl-2 shrink-0">
          <div className="flex items-center gap-1.5 shrink-0">
            <div className="w-6 h-6 sm:w-7 sm:h-7 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400 shrink-0">
              <User className="w-3.5 h-3.5" />
            </div>
            <div className="text-right leading-tight shrink-0">
              <div className="text-[10.5px] font-bold text-slate-200 truncate max-w-[70px] sm:max-w-[90px] xl:max-w-[130px]">
                {user?.full_name || user?.username || 'Commander'}
              </div>
              <div className="text-[8px] sm:text-[8.5px] text-blue-400 uppercase font-mono font-bold tracking-wider">
                {user?.role || 'ADMINISTRATOR'}
              </div>
            </div>
          </div>
          <button
            onClick={() => { logout(); navigate('/login'); }}
            title="Sign Out"
            className="p-1 sm:p-1.5 rounded-lg bg-[#1a2030] hover:bg-red-900/30 text-slate-400 hover:text-red-400 transition-colors border border-[#252d42] shrink-0 flex items-center justify-center cursor-pointer"
          >
            <LogOut className="w-3 h-3 sm:w-3.5 sm:h-3.5" />
          </button>
        </div>
      </div>
    </header>
  );
};

export const Navbar = React.memo(NavbarComponent);
