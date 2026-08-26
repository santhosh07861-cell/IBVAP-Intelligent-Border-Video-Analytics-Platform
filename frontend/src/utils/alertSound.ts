// Professional Security Alarm Sound Synthesizer via Web Audio API

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext {
  if (!audioCtx) {
    const AudioCtxClass = window.AudioContext || (window as any).webkitAudioContext;
    audioCtx = new AudioCtxClass();
  }
  return audioCtx;
}

export function isAlarmMuted(): boolean {
  return localStorage.getItem('ibvap_alarm_muted') === 'true';
}

export function setAlarmMuted(muted: boolean): void {
  localStorage.setItem('ibvap_alarm_muted', muted ? 'true' : 'false');
}

export function toggleAlarmMute(): boolean {
  const current = isAlarmMuted();
  const next = !current;
  setAlarmMuted(next);
  return next;
}

export async function playDangerAlarmSound(): Promise<boolean> {
  if (isAlarmMuted()) {
    return true;
  }

  try {
    const ctx = getAudioContext();
    if (ctx.state === 'suspended') {
      await ctx.resume();
    }

    const now = ctx.currentTime;

    // Dual-tone sweeping security alarm pulse
    const osc1 = ctx.createOscillator();
    const osc2 = ctx.createOscillator();
    const gain = ctx.createGain();

    osc1.type = 'sawtooth';
    osc2.type = 'sine';

    // Frequency sweep: 880Hz -> 1760Hz -> 880Hz over 1.2s
    osc1.frequency.setValueAtTime(880, now);
    osc1.frequency.linearRampToValueAtTime(1760, now + 0.3);
    osc1.frequency.linearRampToValueAtTime(880, now + 0.6);
    osc1.frequency.linearRampToValueAtTime(1760, now + 0.9);
    osc1.frequency.linearRampToValueAtTime(880, now + 1.2);

    osc2.frequency.setValueAtTime(440, now);
    osc2.frequency.linearRampToValueAtTime(880, now + 0.6);
    osc2.frequency.linearRampToValueAtTime(440, now + 1.2);

    // Envelope
    gain.gain.setValueAtTime(0.01, now);
    gain.gain.exponentialRampToValueAtTime(0.3, now + 0.05);
    gain.gain.setValueAtTime(0.3, now + 1.1);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 1.25);

    osc1.connect(gain);
    osc2.connect(gain);
    gain.connect(ctx.destination);

    osc1.start(now);
    osc2.start(now);

    osc1.stop(now + 1.25);
    osc2.stop(now + 1.25);

    return true;
  } catch (err) {
    console.warn('Audio alarm playback restricted by browser autoplay policy:', err);
    return false;
  }
}
