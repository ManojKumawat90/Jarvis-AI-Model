"""
J.A.R.V.I.S — Personal AI Assistant
=====================================
Activation:  double-clap  OR  click ACTIVATE
Deactivation: "goodbye JARVIS" / "that will be all"  OR  click SLEEP
Interrupt:   double-clap / click STOP / press ESC while JARVIS is thinking or speaking
Exit: Ctrl-C
"""
import queue
import re
import sys
import threading
import time
from datetime import datetime
from typing import Optional

from config import SLEEP_PHRASES, HINDI_SLEEP_PHRASES
from clap_detector import ClapDetector, WakeWordDetector
from voice import VoiceEngine
from brain import JarvisBrain
from ui import JarvisUI


_ALL_SLEEP = SLEEP_PHRASES | HINDI_SLEEP_PHRASES


def _is_sleep_command(text: str) -> bool:
    """True only when the utterance is genuinely a goodbye.

    Plain substring matching made "shut down Chrome" or "check my sleep
    settings" deactivate JARVIS. Now: an exact match, or a short utterance
    that begins/ends with a JARVIS-specific farewell ("goodbye jarvis",
    "that will be all").
    """
    norm = re.sub(r"[^\w\s]", " ", text.lower())
    norm = " ".join(norm.split())
    if not norm:
        return False
    phrases = {" ".join(re.sub(r"[^\w\s]", " ", p).split()) for p in _ALL_SLEEP}
    if norm in phrases:
        return True
    if len(norm.split()) > 6:
        return False
    for p in phrases:
        specific = "jarvis" in p or "जार्विस" in p or p.startswith("that will be all") \
            or p == "बस इतना काफी है"
        if specific and (norm.startswith(p) or norm.endswith(p)):
            return True
    return False


def _time_period(lang: str = "en") -> str:
    h = datetime.now().hour
    if lang == "hi":
        return "सुबह" if h < 12 else ("दोपहर" if h < 17 else "शाम")
    return "morning" if h < 12 else ("afternoon" if h < 17 else "evening")


def _greeting(lang: str = "en") -> str:
    if lang == "hi":
        return (
            f"शुभ {_time_period('hi')}, Manu sir। "
            "सभी सिस्टम तैयार हैं। "
            "बताइए, मैं आपकी क्या मदद कर सकता हूँ?"
        )
    return (
        f"Good {_time_period()}, Manu. "
        "All systems are online. "
        "How may I assist you today, Sir?"
    )


def _farewell(lang: str = "en") -> str:
    if lang == "hi":
        return "ठीक है, Manu sir। जब भी जरूरत हो, मैं हाजिर हूँ।"
    return "Very good, Sir. I shall be here when you need me. Good day."


class JARVIS:
    def __init__(self):
        self._voice  = VoiceEngine()
        self._brain  = JarvisBrain()
        self._ui     = JarvisUI()
        self._active = False
        self._busy   = False
        self._stop        = threading.Event()   # full deactivation (sleep)
        self._interrupt   = threading.Event()   # cancel current think/speak, stay in session
        self._cmd_interrupt = threading.Event() # typed command arrived during voice listen
        self._typed_queue: queue.Queue = queue.Queue()

        self._clap = ClapDetector(
            on_double_clap=self._on_activate,
            on_wake_word=self._on_activate,
            on_level=self._ui.update_level,
        )
        self._wake = WakeWordDetector(on_wake=self._on_activate)  # no-op stub
        self._ui.on_activate    = self._on_activate
        self._ui.on_sleep       = self._on_sleep
        self._ui.on_reset       = self._on_reset
        self._ui.on_cmd         = self._on_typed_cmd
        self._ui.on_interrupt   = self._on_interrupt
        self._ui.on_lang_toggle = self._on_lang_toggle
        self._pending_cmd: Optional[str] = None

    # ─────────────────────── handlers ────────────────────────────────────────

    def _on_activate(self):
        if self._active and self._busy:
            # Double-clap while thinking/speaking → interrupt current op
            self._on_interrupt()
            return
        if self._active or self._busy:
            return
        print("[JARVIS] ◉  Activating…")
        self._active = True
        self._stop.clear()
        self._interrupt.clear()
        self._wake.pause()
        # Clap is managed by the session loop (paused during listen, live during think/speak)
        threading.Thread(target=self._session, daemon=True).start()

    def _on_interrupt(self):
        """Cancel the current think/speak operation and return to listening."""
        if not (self._active and self._busy):
            return
        self._ui.set_status("Interrupted, Sir. Ready for your next command.")
        self._interrupt.set()

    def _on_sleep(self):
        if self._busy:
            # Currently thinking/speaking: interrupt first, then deactivate
            self._interrupt.set()
        if self._active:
            print("[JARVIS] ◌  Sleep requested")
            self._stop.set()
            self._cmd_interrupt.set()   # unblock any waiting listen()

    def _on_reset(self):
        self._brain.reset()
        print("[JARVIS] ↺  Memory cleared")
        self._ui.set_status("Conversation memory cleared, Sir.")

    def _on_lang_toggle(self):
        new_lang = "hi" if self._voice.language == "en" else "en"
        self._voice.set_language(new_lang)
        self._ui.set_lang("HI" if new_lang == "hi" else "EN")
        if new_lang == "hi":
            self._ui.set_status("हिंदी मोड सक्रिय, Manu sir।")
            print("[JARVIS] 🇮🇳  Hindi mode active")
        else:
            self._ui.set_status("English mode active, Sir.")
            print("[JARVIS] 🇬🇧  English mode active")

    def _on_typed_cmd(self, text: str):
        """Handle a command typed in the UI input box."""
        if self._busy:
            return
        if self._active:
            # Session is active and listening — inject into session loop
            self._typed_queue.put(text)
            self._cmd_interrupt.set()
            return
        # JARVIS is idle — activate and process directly
        self._active = True
        self._busy   = True
        self._stop.clear()
        self._interrupt.clear()
        self._wake.pause()
        self._ui.set_state("THINKING")
        self._ui.show("Processing typed command…")
        self._ui.set_status("Processing, Sir…")
        self._ui.set_response("")
        print(f"[JARVIS] Typed cmd: '{text[:60]}'")
        try:
            response = self._brain.think(
                text,
                on_chunk=self._ui.append_response,
                interrupt_event=self._interrupt,
            )
            self._ui.set_response(response)
            self._ui.add_to_log("jarvis", response)
            self._ui.set_state("SPEAKING")
            self._clap.pause()
            try:
                self._voice.speak_sync(response, interrupt_event=self._interrupt)
            finally:
                self._clap.resume()
        except InterruptedError:
            self._voice.stop_speaking()
            print("[JARVIS] ⊘  Cancelled — awaiting next command")
            self._ui.set_status("Cancelled, Sir.")
        except Exception as exc:
            print(f"[JARVIS] ERROR: {exc}")
            self._ui.set_response(f"Error — {exc}")
        finally:
            self._interrupt.clear()
            self._busy   = False
            self._active = False
            self._ui.set_state("LISTENING")
            self._ui.show("JARVIS  ONLINE")
            self._clap.resume()
            self._wake.resume()

    # ─────────────────────── Iron Man startup ────────────────────────────────

    def _startup_sequence(self):
        self._voice.play_activation_sound()
        self._ui.set_state("LISTENING")
        self._ui.show("JARVIS  ONLINE")
        time.sleep(0.55)
        welcome = _greeting(self._voice.language)
        self._ui.set_state("SPEAKING")
        self._ui.set_status(welcome)
        print(f"[JARVIS] Greeting: {welcome}")
        self._voice.speak_sync(welcome, interrupt_event=self._interrupt)
        self._ui.set_state("LISTENING")

    # ─────────────────────── session loop ────────────────────────────────────

    def _session(self):
        self._startup_sequence()

        while self._active and not self._stop.is_set():
            self._interrupt.clear()
            self._ui.set_state("LISTENING")
            self._ui.set_status("Awaiting your command, Sir…")
            self._ui.set_transcript("")
            self._ui.set_response("")
            print("[JARVIS] Listening…")

            # Pause clap during voice listen — both use the microphone
            self._clap.pause()
            text = self._voice.listen(
                stop_event=self._stop,
                interrupt_event=self._cmd_interrupt,
            )
            # Resume clap so a double-clap can interrupt think/speak below
            self._clap.resume()

            # Pick up any typed command that interrupted the listen
            typed = False
            if self._cmd_interrupt.is_set():
                self._cmd_interrupt.clear()
                try:
                    text = self._typed_queue.get_nowait()
                    typed = True
                except queue.Empty:
                    text = None

            if self._stop.is_set():
                break
            if self._interrupt.is_set():
                continue
            if text is None:
                if self._voice.language == "hi":
                    self._ui.set_status("समझ नहीं आया, Manu sir। कृपया दोबारा कहें।")
                else:
                    self._ui.set_status("I didn't catch that, Sir. Please try again.")
                continue

            print(f"[JARVIS] {'Typed' if typed else 'Heard'}: '{text}'")
            self._ui.set_transcript(f'"{text}"')
            if not typed:
                # typed commands are already logged by _submit_command in ui.py
                self._ui.add_to_log("user", text)

            if _is_sleep_command(text):
                break

            # ── think ─────────────────────────────────────────────────────────
            self._busy = True
            self._ui.set_state("THINKING")
            self._ui.set_status("Processing, Sir…")
            self._ui.set_response("")
            print("[JARVIS] Thinking…")

            try:
                response = self._brain.think(
                    text,
                    on_chunk=self._ui.append_response,
                    interrupt_event=self._interrupt,
                )
                print(f"[JARVIS] Response ({len(response)} chars)")

                if self._interrupt.is_set():
                    raise InterruptedError

                self._ui.set_response(response)
                self._ui.add_to_log("jarvis", response)
                self._ui.set_state("SPEAKING")
                self._ui.set_status("Speaking…")
                # Pause clap during TTS — prevents speaker audio feeding back into
                # the microphone and triggering a false double-clap interrupt.
                # STOP button and ESC still work as interrupt paths during speech.
                self._clap.pause()
                try:
                    self._voice.speak_sync(response, interrupt_event=self._interrupt)
                finally:
                    self._clap.resume()

            except InterruptedError:
                self._voice.stop_speaking()
                print("[JARVIS] ⊘  Cancelled — awaiting next command")
                self._ui.set_status("Cancelled. Ready for your next command, Sir.")
            except Exception as exc:
                print(f"[JARVIS] ERROR: {exc}")
                if self._voice.language == "hi":
                    err_msg = "माफ करें Manu sir, एक त्रुटि आ गई। क्या मैं दोबारा कोशिश करूँ?"
                else:
                    err_msg = "I'm afraid I encountered an error, Sir. Shall I try again?"
                self._ui.set_status(f"Error — {exc}")
                self._ui.set_response(err_msg)
                try:
                    self._voice.speak_sync(err_msg, interrupt_event=self._interrupt)
                except InterruptedError:
                    self._voice.stop_speaking()
            finally:
                self._busy = False

        # ── farewell ──────────────────────────────────────────────────────────
        print("[JARVIS] ◌  Deactivating…")
        farewell = _farewell(self._voice.language)
        self._ui.set_state("IDLE")
        self._ui.set_status(farewell)
        self._voice.speak_sync(farewell)
        self._active = False
        self._brain.reset()
        self._ui.hide()
        self._clap.resume()
        self._wake.resume()
        print("[JARVIS] Idle — double-clap OR say 'hey JARVIS' to activate")

    # ─────────────────────── run ──────────────────────────────────────────────

    def run(self):
        print("═" * 52)
        print("  J.A.R.V.I.S  —  Personal AI Assistant")
        print("  Double-clap or click ACTIVATE to engage")
        print("  STOP/ESC/double-clap to cancel current operation")
        print("  Say 'goodbye JARVIS' or click SLEEP to rest")
        print("  Ctrl-C to shut down")
        print("═" * 52)

        self._clap.start()
        self._wake.start()
        print("[JARVIS] Idle — double-clap OR say 'hey JARVIS' to activate")

        try:
            self._ui.run()
        except KeyboardInterrupt:
            pass
        finally:
            print("\n[JARVIS] Shutting down…")
            self._clap.stop()
            self._wake.stop()
            sys.exit(0)


if __name__ == "__main__":
    JARVIS().run()
