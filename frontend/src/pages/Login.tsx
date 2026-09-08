import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Shield, Lock, User, AlertCircle } from 'lucide-react';
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
          <div className="w-16 h-16 rounded-2xl bg-[#0a0d14] border border-cyan-500/40 p-1 flex items-center justify-center mb-3 shadow-xl shadow-cyan-950/60 overflow-hidden ring-1 ring-blue-500/20">
            <img src="/logo.jpg" alt="IBVAP Logo" className="w-full h-full object-cover rounded-xl" />
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

        {/* Admin Quick Login */}
        <div className="mt-6 pt-6 border-t border-[#252d42]">
          <p className="text-[11px] font-mono text-slate-400 mb-2 uppercase text-center">DEFAULT ADMIN CREDENTIALS</p>
          <button
            type="button"
            onClick={() => handleQuickLogin('admin', 'Admin Pass123!')}
            className="w-full p-2.5 bg-[#1a2030] hover:bg-blue-900/30 border border-blue-500/30 rounded-lg text-left transition-colors flex items-center justify-between"
          >
            <div>
              <div className="font-semibold text-blue-400 text-xs">Administrator</div>
              <div className="text-[10px] text-slate-400 font-mono">admin / Admin Pass123!</div>
            </div>
            <div className="text-[10px] font-mono text-blue-400 bg-blue-500/10 px-2 py-0.5 rounded border border-blue-500/20">
              AUTO-FILL
            </div>
          </button>
        </div>
      </div>
    </div>
  );
};
