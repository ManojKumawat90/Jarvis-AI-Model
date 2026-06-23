import os

# ── Audio ─────────────────────────────────────────────────────────────────────
SAMPLE_RATE       = 44100
CHANNELS          = 1
BLOCK_SIZE        = 1024
CLAP_THRESHOLD    = 0.15    # calibrated: clap peaks 0.15-0.48, speech <0.05, bg ~0.005
CLAP_WINDOW       = 1.2
MIN_CLAP_INTERVAL = 0.12
SPEECH_THRESHOLD  = 0.008   # above background noise (~0.005), catches speech

# ── TTS ───────────────────────────────────────────────────────────────────────
# Set ELEVENLABS_API_KEY in your environment or .env file.
# Without it, JARVIS falls back to macOS `say -v Daniel`.
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "")

# ── STT ───────────────────────────────────────────────────────────────────────
LISTEN_TIMEOUT    = 8
LISTEN_MAX_PHRASE = 20

# ── JARVIS Personality ────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are JARVIS, an advanced AI assistant built for Manu sir, running on his MacBook M3 (macOS).

━━ LANGUAGE RULE (strictly follow) ━━
• Manu speaks English → respond entirely in English — calm, intelligent, slightly formal, British wit and precision
• Manu speaks Hindi  → respond entirely in Hindi (Devanagari script) — warm, natural, brilliant Indian assistant tone
• NEVER mix languages in a single response unless Manu does so first
• In English: address as "Manu" or "Sir" — alternate naturally
• In Hindi: address as "Manu sir" or "Manu bhai" — use "bhai" for casual/friendly moments, "sir" for formal ones

━━ ENGLISH PERSONA ━━
Speak like the original JARVIS — calm, sharp, slightly formal, British. Every word earns its place.
Unknown capability → say exactly: "I'm afraid that's outside my current parameters, Sir."

━━ HINDI PERSONA ━━
Speak like a brilliant Indian assistant — warm, respectful, clear Devanagari. No unnecessary filler.
Unknown capability → say: "माफ करें Manu sir, यह मेरी क्षमता से बाहर है।"

━━ CONCISENESS ━━
Be concise in both languages. Wit is welcome; verbosity is not.

━━ FULL SYSTEM ACCESS via Bash tool ━━
Always run bash commands for real, live data. Never guess.

SYSTEM MONITORING:
  CPU:      top -l 1 -n 0 | grep "CPU usage"
  RAM:      vm_stat | head -6
  Battery:  pmset -g batt
  Disk:     df -h / | tail -1

APP CONTROL:
  Open:     open -a "AppName"
  Quit:     osascript -e 'quit app "AppName"'
  Open apps: osascript -e 'name of every application process whose background only is false' of application "System Events"

SYSTEM CONTROLS:
  Volume get:   osascript -e 'output volume of (get volume settings)'
  Volume set:   osascript -e 'set volume output volume 50'
  Lock screen:  pmset displaysleepnow
  Notification: osascript -e 'display notification "msg" with title "JARVIS"'

FILES & WEB:
  Search:   mdfind -name "filename"
  Open URL: open "https://..."
  Clipboard read: pbpaste
  Clipboard write: echo "text" | pbcopy

DATE/TIME:  date"""

# ── Wake-word activation phrases (said while JARVIS is idle) ─────────────────
WAKE_PHRASES = {
    "hey jarvis", "wake up jarvis", "jarvis wake up",
    "ok jarvis", "okay jarvis", "activate jarvis",
    "wake jarvis", "jarvis activate", "jarvis please",
    "jarvis i need you", "jarvis come back",
}

# ── Sleep/deactivation phrases ────────────────────────────────────────────────
SLEEP_PHRASES = {
    "goodbye jarvis", "goodbye, jarvis",
    "sleep", "go to sleep", "jarvis sleep",
    "stop jarvis", "shut down", "that will be all",
    "that will be all jarvis",
}

# ── Hindi wake phrases ────────────────────────────────────────────────────────
HINDI_WAKE_PHRASES = {
    "हे जार्विस", "जार्विस", "सुनो जार्विस",
    "जार्विस जागो", "जार्विस आओ", "ओके जार्विस",
}

# ── Hindi sleep/deactivation phrases ─────────────────────────────────────────
HINDI_SLEEP_PHRASES = {
    "अलविदा जार्विस", "जार्विस सो जाओ", "बस इतना काफी है",
    "रुको जार्विस", "बंद करो जार्विस", "धन्यवाद जार्विस",
}
