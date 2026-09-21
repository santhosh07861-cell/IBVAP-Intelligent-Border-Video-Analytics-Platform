/**
 * Independent Browser Multi-Camera Session Manager
 * 
 * Manages isolated MediaStream instances, hidden video capture elements,
 * and frame transmission loops per camera. Ensures each camera has its own
 * lifecycle: connecting or disconnecting one camera never affects any other.
 */

export interface CameraApiDiagnostic {
  supported: boolean;
  code: 'READY' | 'INSECURE_CONTEXT' | 'UNSUPPORTED_BROWSER';
  title: string;
  message: string;
  remedies: string[];
}

export function checkCameraApiSupport(): CameraApiDiagnostic {
  if (typeof window === 'undefined') {
    return {
      supported: false,
      code: 'UNSUPPORTED_BROWSER',
      title: 'ENVIRONMENT UNSUPPORTED',
      message: 'Running in a non-browser environment.',
      remedies: []
    };
  }

  // 1. Check for Secure Context (W3C Requirement for navigator.mediaDevices)
  if (!window.isSecureContext) {
    const isLanHttp =
      window.location.protocol === 'http:' &&
      window.location.hostname !== 'localhost' &&
      window.location.hostname !== '127.0.0.1';

    return {
      supported: false,
      code: 'INSECURE_CONTEXT',
      title: 'INSECURE HTTP CONTEXT (BROWSER RESTRICTION)',
      message: isLanHttp
        ? `Browser blocks camera hardware access over plain HTTP on LAN address (${window.location.origin}). This is an enforced browser security policy, not a missing camera.`
        : 'The browser mediaDevices API is disabled because this page is not served in a Secure Context.',
      remedies: [
        `Access via HTTPS: https://${window.location.hostname}:5173${window.location.pathname}`,
        `Access directly on the host computer: http://localhost:5173${window.location.pathname}`,
        `In Google Chrome: open chrome://flags/#unsafely-treat-insecure-origin-as-secure, add ${window.location.origin}, enable and relaunch.`,
        `Select "Host Server Camera (OpenCV Device Index)" below if capturing the server's local camera hardware.`
      ]
    };
  }

  // 2. Check for navigator.mediaDevices support
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    return {
      supported: false,
      code: 'UNSUPPORTED_BROWSER',
      title: 'BROWSER MEDIA API NOT SUPPORTED',
      message: 'This web browser does not implement the modern navigator.mediaDevices.getUserMedia specification.',
      remedies: [
        'Please upgrade to a modern version of Chrome, Firefox, Edge, or Safari.',
        'Select "Host Server Camera" or "RTSP / IP CAM" to stream directly to the backend without browser capture.'
      ]
    };
  }

  return {
    supported: true,
    code: 'READY',
    title: 'BROWSER CAMERA API READY',
    message: 'Browser mediaDevices API is supported in this secure context.',
    remedies: []
  };
}

export function classifyCameraError(err: any): { title: string; message: string; category: 'PERMISSION_DENIED' | 'NO_DEVICE' | 'CONNECTION_FAILED' | 'UNKNOWN' } {
  const errName = err?.name || '';
  const errMsg = err?.message || '';

  if (errName === 'NotAllowedError' || errName === 'PermissionDeniedError') {
    return {
      title: 'CAMERA PERMISSION DENIED (STATE B)',
      message: 'Camera access was blocked by browser or system permission settings. Please grant camera permission in your browser URL bar / site settings.',
      category: 'PERMISSION_DENIED'
    };
  }

  if (errName === 'NotFoundError' || errName === 'DevicesNotFoundError') {
    return {
      title: 'NO CAMERA DEVICE FOUND (STATE C)',
      message: 'No video input hardware was detected on this physical device. Please verify camera hardware is plugged in.',
      category: 'NO_DEVICE'
    };
  }

  if (errName === 'NotReadableError' || errName === 'TrackStartError') {
    return {
      title: 'CAMERA HARDWARE IN USE / CONNECTION FAILED (STATE D)',
      message: 'The selected camera hardware is already locked or in use by another application (e.g. Zoom, FaceTime, or another tab).',
      category: 'CONNECTION_FAILED'
    };
  }

  if (errName === 'OverconstrainedError') {
    return {
      title: 'CAMERA CONSTRAINTS FAILED (STATE D)',
      message: `The selected camera device does not satisfy requested constraints (${(err as any).constraint || 'unknown constraint'}).`,
      category: 'CONNECTION_FAILED'
    };
  }

  return {
    title: 'CAMERA CONNECTION FAILED (STATE D)',
    message: errMsg || 'Unable to start camera stream.',
    category: 'UNKNOWN'
  };
}

interface CameraSession {
  cameraId: string;
  deviceId: string;
  stream: MediaStream;
  video: HTMLVideoElement;
  canvas: HTMLCanvasElement;
  ctx: CanvasRenderingContext2D | null;
  intervalId: any;
  isPushing: boolean;
}

class BrowserCameraStreamManager {
  private sessions: Map<string, CameraSession> = new Map();

  /**
   * Starts an independent browser webcam session for a specific camera ID.
   * If a session already exists for this camera, it is cleanly replaced without touching any other cameras.
   */
  public async startCameraStream(cameraId: string, deviceId: string): Promise<boolean> {
    if (!cameraId) return false;

    // Check support
    const diag = checkCameraApiSupport();
    if (!diag.supported) {
      console.warn(`[BrowserCameraStreamManager] Cannot start ${cameraId}: ${diag.message}`);
      return false;
    }

    // Stop existing session for this camera only if running
    this.stopCameraStream(cameraId);

    try {
      let stream: MediaStream;
      let hasSpecificDevId = deviceId && deviceId !== 'default' && deviceId !== '0' && !deviceId.startsWith('http') && deviceId.length > 3;
      let cleanDevId = hasSpecificDevId && deviceId.startsWith('browser:') ? deviceId.slice(8) : deviceId;

      // If no specific deviceId was provided, pick an unused video device among active sessions
      if (!hasSpecificDevId) {
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const videoDevices = devices.filter(d => d.kind === 'videoinput');
          const activeDevIds = new Set(Array.from(this.sessions.values()).map(s => s.deviceId));
          const unused = videoDevices.find(d => d.deviceId && !activeDevIds.has(d.deviceId)) || videoDevices[0];
          if (unused && unused.deviceId) {
            cleanDevId = unused.deviceId;
            hasSpecificDevId = true;
          }
        } catch (e) {
          // fallback to default
        }
      }

      try {
        const constraints: MediaStreamConstraints = {
          video: hasSpecificDevId
            ? { deviceId: { exact: cleanDevId }, width: { ideal: 640 }, height: { ideal: 360 } }
            : { width: { ideal: 640 }, height: { ideal: 360 } },
          audio: false
        };
        stream = await navigator.mediaDevices.getUserMedia(constraints);
      } catch (err: any) {
        // If exact deviceId fails (e.g. OverconstrainedError or system device index changed), try ideal or fallback
        if (hasSpecificDevId) {
          console.warn(`[BrowserCameraStreamManager] Exact deviceId failed for ${cameraId}, falling back to ideal:`, cleanDevId);
          try {
            stream = await navigator.mediaDevices.getUserMedia({
              video: { deviceId: { ideal: cleanDevId }, width: { ideal: 640 }, height: { ideal: 360 } },
              audio: false
            });
          } catch (e2) {
            stream = await navigator.mediaDevices.getUserMedia({
              video: { width: { ideal: 640 }, height: { ideal: 360 } },
              audio: false
            });
          }
        } else {
          throw err;
        }
      }

      // Create isolated hidden video element attached to DOM to prevent browser background throttling
      const video = document.createElement('video');
      video.muted = true;
      video.playsInline = true;
      video.autoplay = true;
      video.style.position = 'fixed';
      video.style.top = '-9999px';
      video.style.left = '-9999px';
      video.style.width = '1px';
      video.style.height = '1px';
      video.style.opacity = '0';
      video.style.pointerEvents = 'none';
      document.body.appendChild(video);

      video.srcObject = stream;
      await new Promise<void>((resolve) => {
        if (video.readyState >= 2) {
          resolve();
        } else {
          video.onloadedmetadata = () => {
            resolve();
          };
          setTimeout(resolve, 800);
        }
      });

      try {
        await video.play();
      } catch (playErr) {
        console.warn(`[BrowserCameraStreamManager] video.play() notice on ${cameraId}:`, playErr);
      }

      // Extract the real hardware deviceId and label from the active track
      const track = stream.getVideoTracks()[0];
      const realDeviceId = track?.getSettings()?.deviceId || cleanDevId || 'webcam';
      const realLabel = track?.label || 'Built-in Webcam';

      // If camera previously had generic '0' or default in database, update it to the real hardware deviceId
      if (realDeviceId && (deviceId === '0' || !hasSpecificDevId || deviceId === 'default')) {
        try {
          const token = localStorage.getItem('ibvap_token');
          const headers: Record<string, string> = { 'Content-Type': 'application/json' };
          if (token) headers['Authorization'] = `Bearer ${token}`;
          fetch(`/api/cameras/${encodeURIComponent(cameraId)}/hardware-info`, {
            method: 'PUT',
            headers,
            body: JSON.stringify({
              device_id: realDeviceId,
              hardware_label: realLabel
            })
          }).catch(() => {});
        } catch (_) {}
      }

      // Create isolated offscreen canvas
      const canvas = document.createElement('canvas');
      canvas.width = 640;
      canvas.height = 360;
      const ctx = canvas.getContext('2d');

      const session: CameraSession = {
        cameraId,
        deviceId: realDeviceId,
        stream,
        video,
        canvas,
        ctx,
        intervalId: null,
        isPushing: false
      };

      // Frame push loop (~10 FPS to balance network transfer and smooth real AI processing)
      session.intervalId = setInterval(async () => {
        if (!session.isPushing && video.readyState >= 2 && session.ctx) {
          session.isPushing = true;
          try {
            session.ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
            canvas.toBlob(
              async (blob) => {
                if (blob) {
                  try {
                    await fetch(`/api/cameras/${encodeURIComponent(cameraId)}/frame`, {
                      method: 'POST',
                      headers: { 'Content-Type': 'image/jpeg' },
                      body: blob
                    });
                  } catch (e) {
                    // silent frame drop
                  }
                }
                session.isPushing = false;
              },
              'image/jpeg',
              0.80
            );
          } catch (e) {
            session.isPushing = false;
          }
        }
      }, 100);

      this.sessions.set(cameraId, session);
      console.info(`[BrowserCameraStreamManager] Independent stream started for ${cameraId}`);
      return true;
    } catch (err) {
      console.error(`[BrowserCameraStreamManager] Failed to start stream for ${cameraId}:`, err);
      throw err;
    }
  }

  /**
   * Stops and releases ONLY the specified camera's stream and resources.
   * All other cameras continue running uninterrupted.
   */
  public stopCameraStream(cameraId: string): void {
    const session = this.sessions.get(cameraId);
    if (!session) return;

    if (session.intervalId) {
      clearInterval(session.intervalId);
      session.intervalId = null;
    }

    try {
      if (session.stream) {
        session.stream.getTracks().forEach((track) => {
          track.stop();
        });
      }
      if (session.video) {
        session.video.pause();
        session.video.srcObject = null;
        if (session.video.parentNode) {
          session.video.parentNode.removeChild(session.video);
        }
      }
    } catch (e) {
      console.warn(`[BrowserCameraStreamManager] Error cleaning up ${cameraId}:`, e);
    }

    this.sessions.delete(cameraId);
    console.info(`[BrowserCameraStreamManager] Independent stream stopped for ${cameraId}`);
  }

  /**
   * Checks if an independent browser stream is active for the camera ID.
   */
  public isStreaming(cameraId: string): boolean {
    return this.sessions.has(cameraId);
  }

  /**
   * Cleans up all active sessions on page unmount.
   */
  public stopAll(): void {
    Array.from(this.sessions.keys()).forEach((cid) => {
      this.stopCameraStream(cid);
    });
  }
}

export const browserCameraStreamManager = new BrowserCameraStreamManager();
