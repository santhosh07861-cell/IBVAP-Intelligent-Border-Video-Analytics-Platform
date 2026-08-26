import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { WebSocketProvider } from './context/WebSocketContext';
import { CameraProvider } from './context/CameraContext';
import { Navbar } from './components/Navbar';
import { Sidebar } from './components/Sidebar';

import { Login } from './pages/Login';
import { Dashboard } from './pages/Dashboard';
import { Surveillance } from './pages/Surveillance';
import { CameraList } from './pages/CameraList';
import { ZoneEditor } from './pages/ZoneEditor';
import { AlertList } from './pages/AlertList';
import { IncidentList } from './pages/IncidentList';
import { IncidentDetail } from './pages/IncidentDetail';
import { ANPRView } from './pages/ANPRView';
import { FaceView } from './pages/FaceView';
import { Analytics } from './pages/Analytics';
import { HealthView } from './pages/HealthView';
import { ModelRegistryView } from './pages/ModelRegistryView';
import { AuditView } from './pages/AuditView';
import { DemoControl } from './pages/DemoControl';
import { EvidenceGallery } from './pages/EvidenceGallery';
import { TacticalGISMap } from './pages/TacticalGISMap';

const ProtectedLayout: React.FC = () => {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return (
    <div className="min-h-screen bg-[#0a0d14] flex flex-col font-sans">
      <Navbar />
      <div className="flex flex-1">
        <Sidebar />
        <main className="flex-1 overflow-y-auto bg-[#0a0d14]">
          <Routes>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/surveillance" element={<Surveillance />} />
            <Route path="/gis-map" element={<TacticalGISMap />} />
            <Route path="/cameras" element={<CameraList />} />
            <Route path="/zones" element={<ZoneEditor />} />
            <Route path="/alerts" element={<AlertList />} />
            <Route path="/incidents" element={<IncidentList />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/evidence" element={<EvidenceGallery />} />
            <Route path="/detections" element={<EvidenceGallery />} />
            <Route path="/anpr" element={<ANPRView />} />
            <Route path="/faces" element={<FaceView />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/camera-health" element={<HealthView />} />
            <Route path="/system-health" element={<HealthView />} />
            <Route path="/models" element={<ModelRegistryView />} />
            <Route path="/audit" element={<AuditView />} />
            <Route path="/demo" element={<DemoControl />} />
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  );
};

export const App: React.FC = () => {
  return (
    <AuthProvider>
      <CameraProvider>
        <WebSocketProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/*" element={<ProtectedLayout />} />
            </Routes>
          </BrowserRouter>
        </WebSocketProvider>
      </CameraProvider>
    </AuthProvider>
  );
};

export default App;
