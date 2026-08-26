import React, { createContext, useContext, useState, useEffect } from 'react';

interface User {
  id: string;
  username: string;
  email: string;
  full_name: string;
  role: string;
}

interface AuthContextType {
  token: string | null;
  user: User | null;
  login: (username: string, password: string) => Promise<{ success: boolean; error?: string }>;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(localStorage.getItem('ibvap_token'));
  const [user, setUser] = useState<User | null>(() => {
    const saved = localStorage.getItem('ibvap_user');
    return saved ? JSON.parse(saved) : null;
  });

  const login = async (username: string, password: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const formData = new URLSearchParams();
      formData.append('username', username);
      formData.append('password', password);

      const res = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: formData
      });

      if (res.ok) {
        const data = await res.json();
        setToken(data.access_token);
        setUser(data.user);
        localStorage.setItem('ibvap_token', data.access_token);
        localStorage.setItem('ibvap_user', JSON.stringify(data.user));
        return { success: true };
      }

      if (res.status === 401) {
        return { success: false, error: 'Invalid username or password.' };
      }

      const errText = await res.text();
      return { success: false, error: `Server error (${res.status}): ${errText || res.statusText}` };
    } catch (e) {
      console.error("Login failed:", e);
      return { success: false, error: 'Cannot connect to backend server (port 8000). Please ensure python backend is running.' };
    }
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('ibvap_token');
    localStorage.removeItem('ibvap_user');
  };

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isAuthenticated: !!token }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
};
