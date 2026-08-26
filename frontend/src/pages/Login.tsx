import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Lock, User, AlertCircle, CheckCircle2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export const Login: React.FC = () => {
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('Admin Pass123!');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    const res = await login(username, password);
    setLoading(false);
    if (res.success) {
      navigate('/dashboard');
    } else {
      setError(res.error || 'Invalid credentials or inactive account.');
    }
  };

  const handleQuickLogin = (uname: string, pwd: string) => {
    setUsername(uname);
    setPassword(pwd);
  };

  return (
    <div className="min-h-screen bg-[#0a0d14] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-[#111622] border border-[#252d42] rounded-xl p-8 shadow-2xl relative overflow-hidden">
        <div className="absolute top-0 left-0 right-0 h-1 bg-gradient-to-r from-blue-600 via-amber-500 to-red-600" />

        <div className="flex flex-col items-center text-center mb-6">
          <div className="w-14 h-14 rounded-xl bg-blue-600/20 border border-blue-500/40 flex items-center justify-center text-blue-400 mb-3">
            <Shield className="w-8 h-8 animate-pulse" />
          </div>
          <h2 className="text-xl font-bold tracking-wider text-slate-100">IBVAP COMMAND LOGIN</h2>
          <p className="text-xs text-slate-400 font-mono mt-1">SIH 2026 INTELLIGENT SURVEILLANCE PLATFORM</p>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-950/50 border border-red-500/40 rounded-lg flex items-center gap-2 text-xs text-red-300">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1">USERNAME</label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="text"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg pl-9 pr-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-blue-500 font-mono"
                placeholder="Enter username"
                required
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-mono text-slate-300 mb-1">PASSWORD</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-3" />
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full bg-[#0a0d14] border border-[#252d42] rounded-lg pl-9 pr-3 py-2 text-xs text-slate-100 focus:outline-none focus:border-blue-500 font-mono"
                placeholder="Enter password"
                required
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg text-xs tracking-wider uppercase transition-colors shadow-lg shadow-blue-600/20 disabled:opacity-50"
          >
            {loading ? 'AUTHENTICATING...' : 'AUTHENTICATE & ACCESS'}
          </button>
        </form>

        {/* Demo Roles Quick Login Buttons */}
        <div className="mt-6 pt-6 border-t border-[#252d42]">
          <p className="text-[11px] font-mono text-slate-400 mb-2 uppercase text-center">QUICK DEMO CREDENTIALS (SIH EVALUATION)</p>
          <div className="grid grid-cols-2 gap-2 text-xs">
            <button
              onClick={() => handleQuickLogin('admin', 'Admin Pass123!')}
              className="p-2 bg-[#1a2030] hover:bg-blue-900/30 border border-[#252d42] rounded text-left transition-colors"
            >
              <div className="font-semibold text-blue-400">Administrator</div>
              <div className="text-[10px] text-slate-400 font-mono">admin / Admin Pass123!</div>
            </button>

            <button
              onClick={() => handleQuickLogin('operator', 'Operator Pass123!')}
              className="p-2 bg-[#1a2030] hover:bg-emerald-900/30 border border-[#252d42] rounded text-left transition-colors"
            >
              <div className="font-semibold text-emerald-400">Security Operator</div>
              <div className="text-[10px] text-slate-400 font-mono">operator / Operator Pass123!</div>
            </button>

            <button
              onClick={() => handleQuickLogin('analyst', 'Analyst Pass123!')}
              className="p-2 bg-[#1a2030] hover:bg-purple-900/30 border border-[#252d42] rounded text-left transition-colors"
            >
              <div className="font-semibold text-purple-400">Analyst</div>
              <div className="text-[10px] text-slate-400 font-mono">analyst / Analyst Pass123!</div>
            </button>

            <button
              onClick={() => handleQuickLogin('viewer', 'Viewer Pass123!')}
              className="p-2 bg-[#1a2030] hover:bg-amber-900/30 border border-[#252d42] rounded text-left transition-colors"
            >
              <div className="font-semibold text-amber-400">Viewer</div>
              <div className="text-[10px] text-slate-400 font-mono">viewer / Viewer Pass123!</div>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
