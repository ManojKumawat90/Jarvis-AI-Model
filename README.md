# J.A.R.V.I.S

**Just A Rather Very Intelligent System** — a personal AI assistant for macOS, inspired by the Iron Man HUD. Activate with a double-clap or voice, ask anything, and get spoken responses powered by Claude.

---

## Features

- **Hands-free activation** — double-clap detection via microphone, or say a wake phrase (e.g. "Hey JARVIS")
- **Voice I/O** — Google Speech Recognition for STT; ElevenLabs Daniel voice for TTS (macOS `say` fallback)
- **Claude AI backend** — uses the `claude` CLI with Bash tool access; no API key required, just a claude.ai login
- **Full-screen pygame HUD** — live system monitor, rotating arcs, EQ visualiser, conversation log, command input
- **Typed commands** — type directly in the UI and press Enter; supports drag-and-drop file context
- **Quick Intel buttons** — one-click shortcuts for system status, battery, CPU/RAM, running apps, and more
- **Persistent conversation** — multi-turn memory within a session; resets on sleep or via the Reset button
- **Immediate sleep response** — SLEEP button cancels listening within ~100 ms (non-blocking listen thread)

---

## Project Structure

```
JARVIS/
├── main.py           # Orchestrator: session loop, activation/sleep handlers
├── brain.py          # JarvisBrain — builds prompts, calls the claude CLI, tracks history
├── voice.py          # VoiceEngine — STT (Google), TTS (ElevenLabs / macOS say), beep
├── clap_detector.py  # ClapDetector — double-clap + wake-word detection via sounddevice
├── ui.py             # JarvisUI — full-screen pygame HUD, sys stats, log, input
├── config.py         # All tuneable constants and the JARVIS system prompt
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
| ElevenLabs account | Optional; falls back to macOS `say -v Daniel` without it |
| Microphone access | Grant in System Settings > Privacy & Security > Microphone |

---

## Installation

```bash
# 1. Install PortAudio (required for PyAudio)
brew install portaudio

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. (Optional) Set ElevenLabs API key for the Daniel voice
export ELEVENLABS_API_KEY="your_key_here"

# 4. Make sure the claude CLI is logged in
claude auth login
```

---

## Running

```bash
python main.py
```

The full-screen HUD launches immediately in standby mode. It remains visible but dim until activated.

---

## Activation & Control

| Action | How |
|---|---|
| Activate | Double-clap, say a wake phrase, or click **ACTIVATE** |
| Sleep | Say a sleep phrase (e.g. "goodbye JARVIS") or click **SLEEP** |
| Reset memory | Click **RESET** to clear conversation history |
| Typed command | Type in the command box (bottom-right) and press **Enter** |
| Drop a file | Drag any file onto the HUD; its contents are appended to your next command |
| Exit | Press **ESC** or **Ctrl-C** in the terminal |

### Wake phrases (while idle)

> "Hey JARVIS", "wake up JARVIS", "OK JARVIS", "activate JARVIS", "JARVIS I need you", …

### Sleep phrases (while active)

> "goodbye JARVIS", "sleep", "go to sleep", "that will be all", "shut down", …

---

## Configuration

All settings are in `config.py`:

| Constant | Default | Description |
|---|---|---|
| `CLAP_THRESHOLD` | `0.15` | RMS level to register a clap (raise if false triggers) |
| `CLAP_WINDOW` | `1.2` s | Max time between two claps for a double-clap |
| `SPEECH_THRESHOLD` | `0.008` | RMS level to detect speech for wake-word STT |
| `LISTEN_TIMEOUT` | `8` s | How long to wait for speech before returning `None` |
| `LISTEN_MAX_PHRASE` | `20` s | Maximum phrase duration |
| `ELEVENLABS_API_KEY` | env var | Falls back to macOS `say` if not set |
| `SYSTEM_PROMPT` | — | JARVIS personality, address rules, and bash command cheatsheet |

---

## HUD Layout

```
┌─────────────────────────────────────────────────────┐
│  J.A.R.V.I.S               [ STATE ]       HH:MM:SS │  ← Top bar
├──────────────┬──────────────────────┬────────────────┤
│              │                      │  Quick Intel   │
│  SYS MONITOR │   Core Intelligence  │  Mission Log   │
│  CPU / RAM   │      Matrix HUD      │  Command input │
│  Disk / Bat  │   (rotating arcs)    │  File drop     │
│  Network     │    EQ visualiser     │                │
│  Top procs   │                      │                │
├──────────────┴──────────────────────┴────────────────┤
│  [ACTIVATE]  [SLEEP]  [RESET]       hints …          │  ← Bottom bar
└─────────────────────────────────────────────────────┘
```

---

## Architecture Notes

- **No API key for the AI** — `brain.py` shells out to the `claude` CLI with `--dangerously-skip-permissions` so JARVIS can run bash commands (system stats, open apps, etc.) without prompting.
- **Non-blocking listen** — `voice.listen()` runs the blocking STT call on a daemon thread and polls a `stop_event` every 100 ms, so SLEEP takes effect immediately rather than waiting for the listen timeout.
- **Single audio stream** — `ClapDetector` runs one `sounddevice` stream that handles both clap detection and wake-word buffering, avoiding the dual-stream conflict that causes `[Errno -9985]` on macOS.
- **Wake-word STT** — utterances are buffered in the clap stream, then sent to Google STT off-thread; `WakeWordDetector` in `main.py` is a no-op stub kept for import compatibility.
- **Thread safety in UI** — all state mutations go through a `queue.Queue` (`_cmd_q`) processed on the pygame main thread; `update_level()` uses its own lock for the high-frequency audio callback path.

---

## Troubleshooting

**No audio input / clap not detected**
- Check System Settings > Privacy & Security > Microphone — grant access to Terminal / your IDE.
- Run `python -c "import sounddevice; print(sounddevice.query_devices())"` to verify your mic is listed.
- Adjust `CLAP_THRESHOLD` in `config.py` if background noise is triggering false activations.

**PyAudio install fails on Apple Silicon**
```bash
brew install portaudio
CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" pip install pyaudio
```

**ElevenLabs not working**
- JARVIS will silently fall back to macOS `say -v Daniel`. Check the terminal for `[JARVIS] TTS:` lines on startup.

**`claude` command not found**
- Install Claude Code from https://claude.ai/code and ensure the binary is on your `PATH`.
- Verify with `which claude`.

**JARVIS stuck on "Listening…" after clicking SLEEP**
- Fixed in current code: `voice.listen()` now accepts a `stop_event` and returns within ~100 ms of sleep being requested.
