import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { useAuth } from './AuthContext';

export interface CameraModel {
  id: string;
  camera_id: string;
  name: string;
  description?: string;
  location?: string;
  latitude?: number;
  longitude?: number;
  protocol: string;
  role: 'primary' | 'secondary';
  status: 'ONLINE' | 'OFFLINE' | 'CONNECTING' | 'DEGRADED' | 'ERROR' | 'STOPPED';
  fps: number;
  resolution?: string;
  analytics_enabled?: boolean;
  is_demo?: boolean;
}

interface CameraContextType {
  cameras: CameraModel[];
  primaryCamera: CameraModel | null;
  secondaryCameras: CameraModel[];
  loading: boolean;
  error: string | null;
  refreshCameras: () => Promise<void>;
  setPrimaryCamera: (cameraId: string) => Promise<boolean>;
  startCameraStream: (cameraId: string) => Promise<boolean>;
  stopCameraStream: (cameraId: string) => Promise<boolean>;
  subscribeCamera: (cameraId: string, clientId?: string) => Promise<string | null>;
  unsubscribeCamera: (cameraId: string, subscriptionId: string) => Promise<boolean>;
}

const CameraContext = createContext<CameraContextType | undefined>(undefined);

export const CameraProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [cameras, setCameras] = useState<CameraModel[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const { token } = useAuth();

  const getHeaders = useCallback(() => {
    const headers: Record<string, string> = {};
    const authToken = token || localStorage.getItem('ibvap_token');
    if (authToken) headers['Authorization'] = `Bearer ${authToken}`;
    return headers;
  }, [token]);

  const refreshCameras = useCallback(async () => {
    try {
      const res = await fetch('/api/cameras', { headers: getHeaders() });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setCameras(data);
          setError(null);
        }
      }
    } catch (e: any) {
      console.error("Failed to fetch cameras:", e);
      setError(e.message || "Error connecting to backend");
    } finally {
      setLoading(false);
    }
  }, [getHeaders]);

  useEffect(() => {
    refreshCameras();
    const timer = setTimeout(() => setLoading(false), 500);
    const interval = setInterval(refreshCameras, 5000); // Silent refresh every 5s
    return () => {
      clearTimeout(timer);
      clearInterval(interval);
    };
  }, [refreshCameras]);

  const primaryCamera = cameras.find(c => c.role === 'primary') || (cameras.length > 0 ? cameras[0] : null);
  const secondaryCameras = cameras.filter(c => c.id !== primaryCamera?.id);

  // Automatically keep primary camera subscribed for Dashboard
  useEffect(() => {
    if (primaryCamera?.camera_id) {
      fetch(`/api/cameras/${primaryCamera.camera_id}/subscribe`, {
        method: 'POST',
        headers: getHeaders()
      }).catch(() => {});
    }
  }, [primaryCamera?.camera_id, getHeaders]);

  const setPrimaryCamera = async (cameraId: string): Promise<boolean> => {
    try {
      const res = await fetch(`/api/cameras/${cameraId}/set-primary`, {
        method: 'POST',
        headers: getHeaders()
      });
      if (res.ok) {
        await refreshCameras();
        return true;
      }
    } catch (e) {
      console.error("Failed to set primary camera:", e);
    }
    return false;
  };

  const startCameraStream = async (cameraId: string): Promise<boolean> => {
    try {
      setCameras(prev => prev.map(c => c.camera_id === cameraId ? { ...c, status: 'CONNECTING' } : c));
      const res = await fetch(`/api/cameras/${cameraId}/start`, {
        method: 'POST',
        headers: getHeaders()
      });
      await refreshCameras();
      return res.ok;
    } catch (e) {
      console.error("Failed to start camera:", e);
      await refreshCameras();
      return false;
    }
  };

  const stopCameraStream = async (cameraId: string): Promise<boolean> => {
    try {
      const res = await fetch(`/api/cameras/${cameraId}/stop`, {
        method: 'POST',
        headers: getHeaders()
      });
      await refreshCameras();
      return res.ok;
    } catch (e) {
      console.error("Failed to stop camera:", e);
      return false;
    }
  };

  const subscribeCamera = async (cameraId: string, clientId: string = "ui_view"): Promise<string | null> => {
    try {
      const res = await fetch(`/api/cameras/${cameraId}/subscribe`, {
        method: 'POST',
        headers: getHeaders()
      });
      if (res.ok) {
        const data = await res.json();
        return data.subscription_id;
      }
    } catch (e) {
      console.error("Failed to subscribe camera:", e);
    }
    return null;
  };

  const unsubscribeCamera = async (cameraId: string, subscriptionId: string): Promise<boolean> => {
    try {
      const res = await fetch(`/api/cameras/${cameraId}/unsubscribe?subscription_id=${encodeURIComponent(subscriptionId)}`, {
        method: 'POST',
        headers: getHeaders()
      });
      return res.ok;
    } catch (e) {
      console.error("Failed to unsubscribe camera:", e);
      return false;
    }
  };

  return (
    <CameraContext.Provider
      value={{
        cameras,
        primaryCamera,
        secondaryCameras,
        loading,
        error,
        refreshCameras,
        setPrimaryCamera,
        startCameraStream,
        stopCameraStream,
        subscribeCamera,
        unsubscribeCamera
      }}
    >
      {children}
    </CameraContext.Provider>
  );
};

export const useCameras = () => {
  const ctx = useContext(CameraContext);
  if (!ctx) throw new Error("useCameras must be used within CameraProvider");
  return ctx;
};
