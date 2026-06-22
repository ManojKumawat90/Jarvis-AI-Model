"""
ClapDetector — sounddevice-based double-clap and wake-word detector.
Wake-word STT runs inside the same stream (no dual-stream conflict).
WakeWordDetector is kept as a no-op stub so main.py import doesn't break.
"""
import threading
import time
import numpy as np
import sounddevice as sd
import speech_recognition as sr
from typing import Callable, Optional

from config import (
    SAMPLE_RATE, CHANNELS, BLOCK_SIZE,
    CLAP_THRESHOLD, CLAP_WINDOW, MIN_CLAP_INTERVAL,
    SPEECH_THRESHOLD, WAKE_PHRASES,
)

# Frames-per-second for the audio stream
_FPS = SAMPLE_RATE / BLOCK_SIZE              # ≈ 43

_SILENCE_FRAMES  = int(_FPS * 0.45)          # silence this long → end utterance
_MIN_SPK_FRAMES  = int(_FPS * 0.15)          # discard clips shorter than this
_MAX_SPK_FRAMES  = int(_FPS * 3.5)           # cap at 3.5 s


class ClapDetector:
    def __init__(
        self,
        on_double_clap: Callable,
        on_wake_word:   Optional[Callable] = None,
        on_level:       Optional[Callable[[float], None]] = None,
    ):
        self._clap_cb  = on_double_clap
        self._wake_cb  = on_wake_word
        self._lvl_cb   = on_level

        self._clap_times: list  = []
        self._lock = threading.Lock()
        self._stream   = None
        self._paused   = False
        self._wake_busy = False

        # Speech buffer for wake-word detection
        self._spk_buf:   list  = []
        self._in_speech  = False
        self._sil_count  = 0

    # ── sounddevice callback ──────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        rms = float(np.sqrt(np.mean(indata ** 2)))

        if self._lvl_cb:
            self._lvl_cb(rms)

        if self._paused:
            return

        # ── Clap detection ────────────────────────────────────────────────────
        if rms >= CLAP_THRESHOLD:
            now = time.monotonic()
            with self._lock:
                self._clap_times = [t for t in self._clap_times
                                    if now - t < CLAP_WINDOW]
                if self._clap_times and (now - self._clap_times[-1]) < MIN_CLAP_INTERVAL:
                    return
                self._clap_times.append(now)
                if len(self._clap_times) >= 2:
                    self._clap_times.clear()
                    print("[Clap] Double-clap detected!")
                    threading.Thread(target=self._clap_cb, daemon=True).start()

        # ── Wake-word speech buffering ────────────────────────────────────────
        if not self._wake_cb or self._wake_busy:
            return

        if rms >= SPEECH_THRESHOLD:
            self._in_speech  = True
            self._sil_count  = 0
            if len(self._spk_buf) < _MAX_SPK_FRAMES:
                self._spk_buf.append(indata.copy())
        elif self._in_speech:
            self._spk_buf.append(indata.copy())
            self._sil_count += 1
            if self._sil_count >= _SILENCE_FRAMES:
                # End of utterance — run STT
                self._in_speech = False
                self._sil_count = 0
                if len(self._spk_buf) >= _MIN_SPK_FRAMES:
                    buf = list(self._spk_buf)
                    threading.Thread(
                        target=self._check_wake, args=(buf,), daemon=True
                    ).start()
                self._spk_buf.clear()
            elif len(self._spk_buf) >= _MAX_SPK_FRAMES:
                # Utterance too long — flush
                self._spk_buf.clear()
                self._in_speech = False
                self._sil_count = 0

    def _check_wake(self, buf: list):
        """Convert buffered audio to PCM and run Google STT."""
        try:
            audio_np  = np.concatenate(buf, axis=0).flatten()
            pcm_bytes = (audio_np * 32767).astype(np.int16).tobytes()
            audio_data = sr.AudioData(pcm_bytes, SAMPLE_RATE, 2)
            rec  = sr.Recognizer()
            text = rec.recognize_google(audio_data).lower().strip()
            print(f"[WakeWord] heard: '{text}'")
            if any(phrase in text for phrase in WAKE_PHRASES):
                self._wake_busy = True
                threading.Thread(target=self._wake_cb, daemon=True).start()
        except sr.UnknownValueError:
            pass
        except sr.RequestError as exc:
            print(f"[WakeWord] STT network error: {exc}")
        except Exception as exc:
            print(f"[WakeWord] error: {exc}")

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def start(self):
        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
        )
        self._stream.start()
        print(f"[Clap] Listening  (threshold={CLAP_THRESHOLD})")
        if self._wake_cb:
            print(f"[WakeWord] Listening  (speech threshold={SPEECH_THRESHOLD})")

    def stop(self):
        if self._stream:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def pause(self):
        self._paused    = True
        self._spk_buf.clear()
        self._in_speech = False

    def resume(self):
        with self._lock:
            self._clap_times.clear()
        self._spk_buf.clear()
        self._in_speech = False
        self._wake_busy = False
        self._paused    = False


# ── No-op stub so existing main.py import keeps working ──────────────────────

class WakeWordDetector:
    """No-op — wake word is now handled inside ClapDetector."""
    def __init__(self, on_wake: Callable): pass
    def start(self):  pass
    def stop(self):   pass
    def pause(self):  pass
    def resume(self): pass
