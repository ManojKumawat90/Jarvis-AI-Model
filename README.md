# J.A.R.V.I.S

**Just A Rather Very Intelligent System** — a personal AI assistant for macOS, inspired by the Iron Man HUD.  
Activate with a double-clap or voice, speak in English or Hindi, and get spoken responses powered by Claude.

---

## What's New in v1.1.0 — Bilingual Hindi/English

- **Hindi voice** — `hi-IN-MadhurNeural` via `edge-tts`: Indian male, deep, warm, authoritative North Indian tone
- **Hindi STT** — Google Speech Recognition switches to `hi-IN` locale in Hindi mode
- **EN / HI toggle** — one-click language switch in the bottom bar; language persists for the whole session
- **Smart language prompt** — Claude automatically matches the user's language:
  - English → British JARVIS persona ("Sir", "Manu")
  - Hindi → warm Indian assistant persona ("Manu sir", "Manu bhai")
- **Hindi wake & sleep phrases** — JARVIS responds to Hindi voice commands natively

---

## Features

- **Hands-free activation** — double-clap detection or wake phrases ("Hey JARVIS", "जार्विस जागो")
- **Bilingual voice I/O** — Hindi: `edge-tts MadhurNeural` (Indian male, neural) | English: ElevenLabs Daniel
- **Automatic language matching** — Claude responds in the same language the user speaks, no manual switching needed beyond the STT toggle
- **Claude AI backend** — uses the `claude` CLI with Bash tool access; no Anthropic API key required
- **Full-screen pygame HUD** — live system monitor, rotating arcs, EQ visualiser, conversation log, command input
- **Typed commands** — type in the command box and press Enter; supports drag-and-drop file context
- **Quick Intel buttons** — one-click shortcuts for system status, battery, CPU/RAM, running apps, and more
- **Persistent conversation** — multi-turn memory within a session; resets on sleep or via the Reset button
- **Interrupt support** — double-clap, click STOP, or press ESC to cancel any in-progress response

---

## Project Structure

```
JARVIS/
├── main.py           # Orchestrator: session loop, activation/sleep/language handlers
├── brain.py          # JarvisBrain — builds prompts, calls the claude CLI, tracks history
├── voice.py          # VoiceEngine — STT (Google hi-IN/en-IN), TTS (edge-tts / ElevenLabs / macOS say), beep
├── clap_detector.py  # ClapDetector — double-clap + wake-word detection via sounddevice
├── ui.py             # JarvisUI — full-screen pygame HUD, sys stats, log, input, EN/HI button
├── config.py         # All tuneable constants, system prompt, wake/sleep phrase sets
└── requirements.txt  # Python dependencies
```

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS | Tested on MacBook M3; any modern macOS should work |
| Python 3.9+ | Uses `Optional[X]` typing; do **not** use `X \| None` syntax |
| Claude Code CLI | `claude` must be on `PATH`; login once with `claude auth login` |
| PortAudio | Required by PyAudio — `brew install portaudio` |
| ElevenLabs account | Optional; English falls back to macOS `say -v Daniel` without it |
| edge-tts | Free — used for Hindi TTS (`hi-IN-MadhurNeural`), no API key required |
| Microphone access | Grant in System Settings > Privacy & Security > Microphone |

---

## Installation

```bash
# 1. Install PortAudio (required for PyAudio)
brew install portaudio

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. (Optional) Set ElevenLabs API key for the English Daniel voice
export ELEVENLABS_API_KEY="your_key_here"

# 4. Make sure the claude CLI is logged in
claude auth login
```

> **Hindi voice works out of the box** — `edge-tts` is installed via `requirements.txt` and requires no API key or account.

---

## Running

```bash
python main.py
```

The full-screen HUD launches immediately in standby mode.

---

## Activation & Control

| Action | How |
|---|---|
| Activate | Double-clap, say a wake phrase, or click **ACTIVATE** |
| Sleep | Say a sleep phrase or click **SLEEP** |
| Reset memory | Click **RESET** to clear conversation history |
| Switch language | Click **EN / HI** in the bottom bar |
| Typed command | Type in the command box (bottom-right) and press **Enter** |
| Drop a file | Drag any file onto the HUD; its contents are appended to your next command |
| Interrupt | Double-clap, click **STOP**, or press **ESC** while JARVIS is thinking/speaking |
| Exit | Press **ESC** on the idle screen or **Ctrl-C** in the terminal |

### English wake phrases

> "Hey JARVIS", "wake up JARVIS", "OK JARVIS", "activate JARVIS", "JARVIS I need you" …

### Hindi wake phrases

> "जार्विस", "हे जार्विस", "सुनो जार्विस", "जार्विस जागो", "ओके जार्विस" …

### English sleep phrases

> "goodbye JARVIS", "sleep", "go to sleep", "that will be all", "shut down" …

### Hindi sleep phrases

> "अलविदा जार्विस", "जार्विस सो जाओ", "बस इतना काफी है", "बंद करो जार्विस" …

---

## Voice System

| Language | Primary TTS | Fallback |
|---|---|---|
| English | ElevenLabs Daniel (`eleven_turbo_v2_5`) | macOS `say -v Daniel` |
| Hindi | `edge-tts` — `hi-IN-MadhurNeural` | macOS `say -v Lekha` |

| Language | STT locale |
|---|---|
| English | `en-IN` (Google Speech Recognition) |
| Hindi | `hi-IN` (Google Speech Recognition) |

**Hindi voice profile — `hi-IN-MadhurNeural`:**  
Indian male · Deep & warm · Authoritative tone · Natural North Indian intonation and cadence · Slightly formal, approachable · Microsoft Neural TTS · Free, no API key

---

## Configuration

All settings are in `config.py`:

| Constant | Default | Description |
|---|---|---|
| `CLAP_THRESHOLD` | `0.15` | RMS level to register a clap (raise if false triggers) |
| `CLAP_WINDOW` | `1.2` s | Max time between two claps for a double-clap |
| `LISTEN_TIMEOUT` | `8` s | How long to wait for speech before returning `None` |
| `LISTEN_MAX_PHRASE` | `20` s | Maximum phrase duration |
| `ELEVENLABS_API_KEY` | env var | Falls back to macOS `say` if not set |
| `SYSTEM_PROMPT` | — | JARVIS personality, bilingual rules, bash command cheatsheet |
| `WAKE_PHRASES` | set | English wake words |
| `HINDI_WAKE_PHRASES` | set | Hindi wake words |
| `SLEEP_PHRASES` | set | English sleep/deactivation words |
| `HINDI_SLEEP_PHRASES` | set | Hindi sleep/deactivation words |

---

## HUD Layout

```
┌──────────────────────────────────────────────────────────┐
│  J.A.R.V.I.S                [ STATE ]          HH:MM:SS  │  ← Top bar
├───────────────┬──────────────────────┬───────────────────┤
│               │                      │  Quick Intel      │
│  SYS MONITOR  │   Core Intelligence  │  Mission Log      │
│  CPU / RAM    │      Matrix HUD      │  Command input    │
│  Disk / Bat   │   (rotating arcs)    │  File drop        │
│  Network      │    EQ visualiser     │                   │
│  Top procs    │                      │                   │
├───────────────┴──────────────────────┴───────────────────┤
│  [ACTIVATE]  [SLEEP]  [RESET]  [EN/HI]    hints …        │  ← Bottom bar
└──────────────────────────────────────────────────────────┘
```

---

## Architecture Notes

- **No API key for the AI** — `brain.py` shells out to the `claude` CLI with `--dangerously-skip-permissions` so JARVIS can run bash commands (system stats, open apps, etc.) without prompting.
- **Bilingual TTS routing** — `speak_sync()` detects Devanagari Unicode characters in the response text and automatically routes to the Hindi voice (`edge-tts`) or the English voice (ElevenLabs) without any manual flag.
- **edge-tts async in thread** — `edge-tts` uses `asyncio`; a fresh event loop is created per call inside a daemon thread so it doesn't conflict with the main pygame loop.
- **Non-blocking listen** — `voice.listen()` runs the blocking STT call on a daemon thread and polls a `stop_event` every 100 ms, so SLEEP takes effect immediately.
- **Single audio stream** — `ClapDetector` runs one `sounddevice` stream that handles both clap detection and wake-word buffering, avoiding the dual-stream conflict that causes `[Errno -9985]` on macOS.
- **Thread safety in UI** — all state mutations go through a `queue.Queue` (`_cmd_q`) processed on the pygame main thread; `update_level()` uses its own lock for the high-frequency audio callback path.

---

## Troubleshooting

**No audio input / clap not detected**
- Check System Settings > Privacy & Security > Microphone — grant access to Terminal / your IDE.
- Run `python -c "import sounddevice; print(sounddevice.query_devices())"` to verify your mic is listed.
- Adjust `CLAP_THRESHOLD` in `config.py` if background noise causes false triggers.

**PyAudio install fails on Apple Silicon**
```bash
brew install portaudio
CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" pip install pyaudio
```

**Hindi voice not working**
- Confirm `edge-tts` is installed: `pip install edge-tts`
- `edge-tts` requires an internet connection (Microsoft Neural TTS streamed on-demand).
- Check the terminal for `[JARVIS] Hindi TTS: edge-tts ready` on startup.

**ElevenLabs English voice not working**
- JARVIS falls back silently to macOS `say -v Daniel`. Check terminal for `[JARVIS] English TTS:` lines.

**`claude` command not found**
- Install Claude Code from https://claude.ai/code and ensure the binary is on your `PATH`.
- Verify with `which claude`.

---

## Changelog

### v1.1.0 — 2026-06-23
- Added bilingual Hindi/English support
- Hindi TTS: `edge-tts hi-IN-MadhurNeural` — Indian male, deep, warm, authoritative
- Hindi STT: Google Speech Recognition `hi-IN` locale
- EN/HI toggle button in the UI bottom bar
- Bilingual system prompt — Claude matches the user's language automatically
- Hindi greeting, farewell, wake, and sleep phrases
- `edge-tts>=7.2.0` added to requirements

### v1.0.0 — 2026-06-22
- Initial release
- English-only JARVIS assistant
- ElevenLabs Daniel voice, Google STT, Claude CLI backend
- Full-screen pygame HUD with system monitor, EQ visualiser, conversation log
