/**
 * authFetch — authenticated fetch wrapper.
 * Reads the JWT from localStorage and attaches it as a Bearer token.
 * Also sets Content-Type: application/json for non-GET requests with a body.
 */
export function authFetch(url: string, options: RequestInit = {}): Promise<Response> {
  const token = localStorage.getItem('token') || sessionStorage.getItem('token') || '';

  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string> || {}),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  if (options.body && !headers['Content-Type']) {
    headers['Content-Type'] = 'application/json';
  }

  return fetch(url, { ...options, headers });
}
