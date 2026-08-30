/**
 * IBVAP Centralized Timezone and Date/Time Formatting Utility
 * Enforces authoritative, consistent Indian Standard Time (IST / Asia/Kolkata, UTC+5:30)
 * across Live Alerts, AI Detections, Incidents, Evidence, and Dashboard feeds.
 */

const normalizeDate = (input?: string | number | Date | null): Date | null => {
  if (!input) return null;
  if (input instanceof Date) return isNaN(input.getTime()) ? null : input;

  if (typeof input === 'number') {
    const d = new Date(input);
    return isNaN(d.getTime()) ? null : d;
  }

  if (typeof input === 'string') {
    let s = input.trim();
    if (!s) return null;

    // If string has no timezone offset ('Z', '+', '-'), treat naive UTC timestamp with 'Z'
    if (!s.endsWith('Z') && !s.includes('+') && !s.includes('Z')) {
      if (s.includes('T')) {
        s = `${s}Z`;
      } else if (s.includes(' ')) {
        s = `${s.replace(' ', 'T')}Z`;
      }
    }

    const d = new Date(s);
    return isNaN(d.getTime()) ? null : d;
  }

  return null;
};

export const formatISTDateTime = (input?: string | number | Date | null): string => {
  const d = normalizeDate(input);
  if (!d) return '—';

  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata'
  }).format(d);
};

export const formatISTTime = (input?: string | number | Date | null): string => {
  const d = normalizeDate(input);
  if (!d) return '—';

  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'Asia/Kolkata'
  }).format(d);
};

export const formatISTDate = (input?: string | number | Date | null): string => {
  const d = normalizeDate(input);
  if (!d) return '—';

  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'Asia/Kolkata'
  }).format(d);
};
