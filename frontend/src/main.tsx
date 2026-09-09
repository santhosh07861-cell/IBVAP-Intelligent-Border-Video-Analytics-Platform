import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

// Direct production backend URL on Render
const BACKEND_PROD_URL = 'https://ibvap-intelligent-border-video-analytics-3tr5.onrender.com';

// Automatically route API and static requests directly to Render backend when deployed on Netlify
if (typeof window !== 'undefined') {
  const originalFetch = window.fetch;
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const isNetlify = window.location.hostname.endsWith('netlify.app');
    if (isNetlify) {
      let url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
      if (url.startsWith('/api') || url.startsWith('/static')) {
        url = `${BACKEND_PROD_URL}${url}`;
        if (typeof input === 'string' || input instanceof URL) {
          input = url;
        } else {
          input = new Request(url, input);
        }
      }
    }
    return originalFetch(input, init);
  };
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

