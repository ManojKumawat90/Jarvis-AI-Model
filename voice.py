"""
VoiceEngine
  English TTS : ElevenLabs Daniel  →  macOS Daniel/Samantha  (fallback)
  Hindi TTS   : edge-tts MadhurNeural (Indian male, neural, free)
                →  macOS Lekha  (offline fallback)
  STT         : Google Speech Recognition (en-IN / hi-IN)
  Activation  : Iron Man beep
"""
import asyncio
import os
import subprocess
import tempfile
import threading
import time
from typing import Optional

import numpy as np
import sounddevice as sd
import speech_recognition as sr

from config import ELEVENLABS_API_KEY, LISTEN_TIMEOUT, LISTEN_MAX_PHRASE

# ── ElevenLabs (English) ──────────────────────────────────────────────────────
_DANIEL_VOICE_ID_FALLBACK = "onwK4e9ZLuTAKqWW03F9"
_EL_MODEL      = "eleven_turbo_v2_5"
_EL_STABILITY  = 0.75
_EL_SIMILARITY = 0.85

# ── edge-tts (Hindi) ──────────────────────────────────────────────────────────
# hi-IN-MadhurNeural: Indian male, deep, warm, authoritative — Microsoft Neural TTS
_EDGE_HINDI_VOICE = "hi-IN-MadhurNeural"
_EDGE_HINDI_RATE  = "-3%"   # slight slow-down for natural cadence
_EDGE_HINDI_PITCH = "-5Hz"  # slightly deeper

# ── Beep ──────────────────────────────────────────────────────────────────────
_BEEP_FREQS = [(440, 0.09), (880, 0.09), (1318, 0.13)]
_BEEP_SR    = 44100


def _build_beep() -> np.ndarray:
    segments = []
    for freq, dur in _BEEP_FREQS:
        t = np.linspace(0, dur, int(_BEEP_SR * dur), endpoint=False)
        wave = 0.22 * np.sin(2 * np.pi * freq * t)
        attack = int(0.004 * _BEEP_SR)
        wave[:attack] *= np.linspace(0, 1, attack)
        wave *= np.exp(-t * 7)
        segments.append(wave)
        segments.append(np.zeros(int(_BEEP_SR * 0.022)))
    audio = np.concatenate(segments).astype(np.float32)
    fade = int(_BEEP_SR * 0.015)
    audio[-fade:] *= np.linspace(1, 0, fade)
    return audio


_BEEP_AUDIO = _build_beep()


class VoiceEngine:
    def __init__(self):
        # ── Language ──────────────────────────────────────────────────────────
        self.language = "en"   # "en" or "hi"

        # ── STT ──────────────────────────────────────────────────────────────
        self._rec = sr.Recognizer()
        self._rec.energy_threshold        = 300
        self._rec.dynamic_energy_threshold = True
        self._rec.pause_threshold         = 0.8

        # ── TTS (English) ─────────────────────────────────────────────────────
        self._tts_proc: Optional[subprocess.Popen] = None
        self._el_client  = None
        self._voice_id   = _DANIEL_VOICE_ID_FALLBACK
        self._el_ready   = False

        # ── TTS (Hindi) ───────────────────────────────────────────────────────
        self._edge_ready      = self._check_edge_tts()
        self._mac_voice       = self._detect_mac_voice()
        self._mac_hindi_voice = self._detect_mac_hindi_voice()

        threading.Thread(target=self._init_elevenlabs, daemon=True).start()

    # ─────────────────────────── detection ───────────────────────────────────

    def _check_edge_tts(self) -> bool:
        try:
            import edge_tts  # noqa: F401
            print(f"[JARVIS] Hindi TTS: edge-tts ready ({_EDGE_HINDI_VOICE})")
            return True
        except ImportError:
            print("[JARVIS] Hindi TTS: edge-tts not installed (pip install edge-tts)")
            return False

    def _detect_mac_voice(self) -> str:
        try:
            result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
            if "daniel" in result.stdout.lower():
                return "Daniel"
        except Exception:
            pass
        return "Samantha"

    def _detect_mac_hindi_voice(self) -> str:
        """macOS Hindi voice — offline fallback only."""
        try:
            result = subprocess.run(["say", "-v", "?"], capture_output=True, text=True)
            lines = result.stdout.lower().splitlines()
            for name in ("kiran", "arjun"):
                if any(name in line for line in lines):
                    return name.title()
            if any("lekha" in line for line in lines):
                return "Lekha"
        except Exception:
            pass
        return ""

    def set_language(self, lang: str):
        """Switch STT/TTS language: 'en' or 'hi'."""
        self.language = lang
        print(f"[JARVIS] Language → {'Hindi' if lang == 'hi' else 'English'}")

    @staticmethod
    def _is_hindi(text: str) -> bool:
        return any('ऀ' <= c <= 'ॿ' for c in text)

    # ─────────────────────────── ElevenLabs init ─────────────────────────────

    def _init_elevenlabs(self):
        if not ELEVENLABS_API_KEY:
            print(f"[JARVIS] English TTS: no API key — using macOS {self._mac_voice}")
            return
        try:
            from elevenlabs.client import ElevenLabs
            from elevenlabs import VoiceSettings  # noqa: F401
            self._el_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)
            resp = self._el_client.voices.get_all()
            daniel = next((v for v in resp.voices if v.name.lower().startswith("daniel")), None)
            if daniel:
                self._voice_id = daniel.voice_id
            self._el_ready = True
            print(f"[JARVIS] English TTS: ElevenLabs Daniel ready (id={self._voice_id[:12]}…)")
        except Exception as exc:
            print(f"[JARVIS] English TTS: ElevenLabs unavailable ({exc}) — using macOS")

    # ─────────────────────────── activation beep ─────────────────────────────

    def play_activation_sound(self):
        try:
            sd.play(_BEEP_AUDIO, _BEEP_SR, blocking=False)
        except Exception as exc:
            print(f"[JARVIS] Beep error: {exc}")

    # ─────────────────────────── TTS dispatcher ──────────────────────────────

    def speak_sync(self, text: str, interrupt_event: Optional[threading.Event] = None):
        """Speak text; raises InterruptedError if interrupted."""
        self.stop_speaking()

        if self._is_hindi(text):
            # Hindi: edge-tts MadhurNeural → macOS Hindi → macOS default
            if self._edge_ready:
                self._speak_edge(text, interrupt_event=interrupt_event)
            elif self._mac_hindi_voice:
                self._speak_macos(text, voice=self._mac_hindi_voice,
                                  rate="145", interrupt_event=interrupt_event)
            else:
                self._speak_macos(text, interrupt_event=interrupt_event)
        else:
            # English: ElevenLabs Daniel → macOS Daniel/Samantha
            if self._el_ready and self._el_client:
                self._speak_elevenlabs(text, interrupt_event=interrupt_event)
            else:
                self._speak_macos(text, interrupt_event=interrupt_event)

    def stop_speaking(self):
        if self._tts_proc and self._tts_proc.poll() is None:
            self._tts_proc.terminate()
            self._tts_proc = None

    # ─────────────────────────── edge-tts (Hindi) ────────────────────────────

    def _speak_edge(self, text: str, interrupt_event: Optional[threading.Event] = None):
        """edge-tts → hi-IN-MadhurNeural (Indian male, neural)."""
        try:
            import edge_tts

            tmp_path: list = [None]
            dl_error: list = [None]
            dl_done = threading.Event()

            def _generate():
                try:
                    communicate = edge_tts.Communicate(
                        text=text,
                        voice=_EDGE_HINDI_VOICE,
                        rate=_EDGE_HINDI_RATE,
                        pitch=_EDGE_HINDI_PITCH,
                    )
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                        tmp_path[0] = f.name

                    loop = asyncio.new_event_loop()
                    loop.run_until_complete(communicate.save(tmp_path[0]))
                    loop.close()
                except Exception as exc:
                    dl_error[0] = exc
                finally:
                    dl_done.set()

            threading.Thread(target=_generate, daemon=True).start()

            while not dl_done.wait(timeout=0.1):
                if interrupt_event and interrupt_event.is_set():
                    raise InterruptedError

            if dl_error[0]:
                raise dl_error[0]

            self._tts_proc = subprocess.Popen(
                ["afplay", tmp_path[0]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                self._wait_proc(self._tts_proc, interrupt_event)
            finally:
                try:
                    os.unlink(tmp_path[0])
                except OSError:
                    pass

        except InterruptedError:
            raise
        except Exception as exc:
            print(f"[JARVIS] edge-tts error: {exc} — falling back to macOS")
            voice = self._mac_hindi_voice or self._mac_voice
            self._speak_macos(text, voice=voice, interrupt_event=interrupt_event)

    # ─────────────────────────── macOS say ───────────────────────────────────

    def _speak_macos(self, text: str, voice: Optional[str] = None,
                     rate: str = "175", interrupt_event: Optional[threading.Event] = None):
        v = voice or self._mac_voice
        self._tts_proc = subprocess.Popen(
            ["say", "-v", v, "-r", rate, text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._wait_proc(self._tts_proc, interrupt_event)

    def _wait_proc(self, proc: subprocess.Popen, interrupt_event: Optional[threading.Event] = None):
        while proc.poll() is None:
            if interrupt_event and interrupt_event.is_set():
                proc.kill()
                proc.wait()
                raise InterruptedError
            time.sleep(0.05)

    # ─────────────────────────── ElevenLabs (English) ────────────────────────

    def _speak_elevenlabs(self, text: str, interrupt_event: Optional[threading.Event] = None):
        from elevenlabs import VoiceSettings
        try:
            tmp_path: list = [None]
            dl_error: list = [None]
            dl_done = threading.Event()

            def _download():
                try:
                    audio_gen = self._el_client.text_to_speech.convert(
                        voice_id=self._voice_id,
                        text=text,
                        model_id=_EL_MODEL,
                        output_format="mp3_44100_128",
                        voice_settings=VoiceSettings(
                            stability=_EL_STABILITY,
                            similarity_boost=_EL_SIMILARITY,
                        ),
                    )
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                        for chunk in audio_gen:
                            if chunk:
                                f.write(chunk)
                        tmp_path[0] = f.name
                except Exception as exc:
                    dl_error[0] = exc
                finally:
                    dl_done.set()

            threading.Thread(target=_download, daemon=True).start()

            while not dl_done.wait(timeout=0.1):
                if interrupt_event and interrupt_event.is_set():
                    raise InterruptedError

            if dl_error[0]:
                raise dl_error[0]

            self._tts_proc = subprocess.Popen(
                ["afplay", tmp_path[0]],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                self._wait_proc(self._tts_proc, interrupt_event)
            finally:
                try:
                    os.unlink(tmp_path[0])
                except OSError:
                    pass

        except InterruptedError:
            raise
        except Exception as exc:
            print(f"[JARVIS] ElevenLabs error: {exc} — falling back to macOS")
            self._speak_macos(text, interrupt_event=interrupt_event)

    # ─────────────────────────── STT ─────────────────────────────────────────

    def listen(
        self,
        stop_event: Optional[threading.Event] = None,
        interrupt_event: Optional[threading.Event] = None,
    ) -> Optional[str]:
        result: list = [None]
        done = threading.Event()

        def _do_listen():
            with sr.Microphone() as source:
                self._rec.adjust_for_ambient_noise(source, duration=0.4)
                try:
                    audio = self._rec.listen(
                        source,
                        timeout=LISTEN_TIMEOUT,
                        phrase_time_limit=LISTEN_MAX_PHRASE,
                    )
                    lang_code = "hi-IN" if self.language == "hi" else "en-IN"
                    recognized = self._rec.recognize_google(audio, language=lang_code)
                    result[0] = recognized if self.language == "hi" else recognized.lower()
                except (sr.WaitTimeoutError, sr.UnknownValueError, sr.RequestError):
                    pass
                finally:
                    done.set()

        threading.Thread(target=_do_listen, daemon=True).start()

        while not done.wait(timeout=0.1):
            if stop_event and stop_event.is_set():
                return None
            if interrupt_event and interrupt_event.is_set():
                return None

        return result[0]
