// Real Security Alarm Audio Controller with Web Audio API Siren Synthesizer & WAV Audio Playback

let globalAudio: HTMLAudioElement | null = null;
let audioCtx: AudioContext | null = null;
let isUnlocked = false;
const playedAlertIds = new Set<string>();

function getAudioContext(): AudioContext {
  if (!audioCtx) {
    const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
    audioCtx = new AudioContextClass();
  }
  if (audioCtx.state === 'suspended') {
    audioCtx.resume();
  }
  return audioCtx;
}

function getAudioElement(): HTMLAudioElement {
  if (!globalAudio) {
    globalAudio = new Audio('/sounds/security-alarm.wav');
    globalAudio.preload = 'auto';
  }
  return globalAudio;
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

export function isAudioArmed(): boolean {
  return isUnlocked && !isAlarmMuted();
}

/**
 * Synthesizes a high-urgency dual-tone tactical security siren using the Web Audio API.
 * Guaranteed to play even if the audio file has network delay.
 */
export function playSyntheticSecuritySiren(durationSec: number = 1.8): void {
  try {
    const ctx = getAudioContext();
    const now = ctx.currentTime;

    const osc = ctx.createOscillator();
    const gainNode = ctx.createGain();

    osc.type = 'sawtooth';
    // Frequency modulation: Alternating siren between 880Hz (A5) and 660Hz (E5)
    osc.frequency.setValueAtTime(880, now);
    osc.frequency.linearRampToValueAtTime(660, now + 0.3);
    osc.frequency.linearRampToValueAtTime(880, now + 0.6);
    osc.frequency.linearRampToValueAtTime(660, now + 0.9);
    osc.frequency.linearRampToValueAtTime(880, now + 1.2);
    osc.frequency.linearRampToValueAtTime(660, now + 1.5);
    osc.frequency.linearRampToValueAtTime(880, now + durationSec);

    // Gain envelope with fast attack and fadeout
    gainNode.gain.setValueAtTime(0.01, now);
    gainNode.gain.linearRampToValueAtTime(0.35, now + 0.05);
    gainNode.gain.setValueAtTime(0.35, now + durationSec - 0.2);
    gainNode.gain.linearRampToValueAtTime(0.001, now + durationSec);

    osc.connect(gainNode);
    gainNode.connect(ctx.destination);

    osc.start(now);
    osc.stop(now + durationSec);
    isUnlocked = true;
  } catch (err) {
    console.warn('[ALARM AUDIO] Synthetic siren error:', err);
  }
}

export async function unlockAudioContext(): Promise<boolean> {
  try {
    const ctx = getAudioContext();
    if (ctx.state === 'suspended') {
      await ctx.resume();
    }
    const audio = getAudioElement();
    audio.volume = 0.01;
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      await playPromise;
      audio.pause();
      audio.currentTime = 0;
      audio.volume = 1.0;
    }
    isUnlocked = true;
    console.log('[ALARM AUDIO] AudioContext & Audio element unlocked successfully.');
    return true;
  } catch (err) {
    console.warn('[ALARM AUDIO] Autoplay unlock required user gesture:', err);
    return false;
  }
}

if (typeof window !== 'undefined') {
  const autoUnlock = () => {
    if (!isUnlocked) {
      unlockAudioContext();
    }
  };
  window.addEventListener('click', autoUnlock, { passive: true });
  window.addEventListener('pointerdown', autoUnlock, { passive: true });
  window.addEventListener('keydown', autoUnlock, { passive: true });
  window.addEventListener('touchstart', autoUnlock, { passive: true });
}

export async function playTestAlarm(): Promise<{ success: boolean; message: string }> {
  try {
    await unlockAudioContext();
    playSyntheticSecuritySiren(1.5);
    const audio = getAudioElement();
    audio.volume = 1.0;
    audio.currentTime = 0;
    await audio.play().catch(() => {});
    isUnlocked = true;
    return { success: true, message: '🚨 Security Alarm Siren Tested Successfully!' };
  } catch (err: any) {
    console.error('[ALARM AUDIO ERROR] Test alarm error:', err);
    return {
      success: false,
      message: `Alarm sound blocked by browser autoplay policy. Click "ENABLE ALARM" button first.`
    };
  }
}

/**
 * Plays the Security Alarm sound with deduplication per alert ID.
 * Fires both the synthesized siren and the audio WAV file.
 */
export async function playDangerAlarmSound(alertId?: string): Promise<boolean> {
  if (isAlarmMuted()) {
    console.log('[ALARM AUDIO] Alarm is muted by operator. Skipping playback.');
    return true;
  }

  if (alertId) {
    if (playedAlertIds.has(alertId)) {
      console.log(`[ALARM AUDIO] Alert ${alertId} sound already played. Deduplicating.`);
      return true;
    }
    playedAlertIds.add(alertId);
    if (playedAlertIds.size > 500) {
      const oldest = playedAlertIds.values().next().value;
      if (oldest) playedAlertIds.delete(oldest);
    }
  }

  try {
    // 1. Fire synthesized emergency siren
    playSyntheticSecuritySiren(2.0);

    // 2. Fire wav file audio
    const audio = getAudioElement();
    audio.volume = 1.0;
    audio.currentTime = 0;
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      await playPromise.catch(() => {});
    }
    isUnlocked = true;
    console.log(`[ALARM AUDIO] 🚨 REAL SECURITY ALARM SOUND PLAYED for Alert #${alertId || 'NEW'}`);
    return true;
  } catch (err: any) {
    console.error(`[ALARM AUDIO ERROR] Alarm sound blocked for Alert #${alertId}:`, err);
    return false;
  }
}
