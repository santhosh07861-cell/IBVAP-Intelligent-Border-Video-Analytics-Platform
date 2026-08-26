// Real Security Alarm Audio Controller with Browser Autoplay Unlock & Deduplication

let globalAudio: HTMLAudioElement | null = null;
let isUnlocked = false;
const playedAlertIds = new Set<string>();

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

export async function unlockAudioContext(): Promise<boolean> {
  try {
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
    console.log('[ALARM AUDIO] AudioContext unlocked successfully via user gesture.');
    return true;
  } catch (err) {
    console.warn('[ALARM AUDIO] Autoplay unlock required user gesture:', err);
    return false;
  }
}

export async function playTestAlarm(): Promise<{ success: boolean; message: string }> {
  try {
    const audio = getAudioElement();
    audio.volume = 1.0;
    audio.currentTime = 0;
    await audio.play();
    isUnlocked = true;
    return { success: true, message: 'Test alarm played successfully!' };
  } catch (err: any) {
    console.error('[ALARM AUDIO ERROR] Test alarm blocked by browser:', err);
    return {
      success: false,
      message: `Alarm sound blocked by browser autoplay policy. Click "ENABLE ALARM SOUND" button first. (${err.message || 'Blocked'})`
    };
  }
}

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
    // Keep set bounded
    if (playedAlertIds.size > 500) {
      const oldest = playedAlertIds.values().next().value;
      if (oldest) playedAlertIds.delete(oldest);
    }
  }

  try {
    const audio = getAudioElement();
    audio.volume = 1.0;
    audio.currentTime = 0;
    const playPromise = audio.play();
    if (playPromise !== undefined) {
      await playPromise;
    }
    isUnlocked = true;
    console.log(`[ALARM AUDIO] 🚨 REAL ALARM SOUND PLAYED SUCCESSFULLY for Alert #${alertId || 'NEW'}`);
    return true;
  } catch (err: any) {
    console.error(`[ALARM AUDIO ERROR] Alarm sound blocked by browser for Alert #${alertId}:`, err);
    return false;
  }
}
