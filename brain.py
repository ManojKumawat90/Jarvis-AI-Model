"""
Uses the `claude` CLI (claude.ai login) with full Bash tool access.
No ANTHROPIC_API_KEY needed.

Responses are streamed (stream-json) so text appears in the UI token-by-token
instead of all at once after the CLI exits.
"""
import datetime
import json
import os
import shutil
import subprocess
import threading
from typing import Callable, List, Optional

from config import SYSTEM_PROMPT

_CLAUDE = shutil.which("claude") or "claude"

# Optional: JARVIS_MODEL=haiku for snappier replies, or sonnet/opus for depth.
_MODEL = os.environ.get("JARVIS_MODEL", "").strip()

# Keep the prompt bounded — oldest turns are dropped beyond this many messages.
_MAX_HISTORY = 20


def _now() -> str:
    return datetime.datetime.now().strftime("%A %d %B %Y, %I:%M %p")


class JarvisBrain:
    def __init__(self):
        self._history: List[dict] = []

    def _cmd(self) -> List[str]:
        cmd = [
            _CLAUDE, "-p",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--system-prompt", SYSTEM_PROMPT,
            "--allowedTools", "Bash",
            "--dangerously-skip-permissions",
        ]
        if _MODEL:
            cmd += ["--model", _MODEL]
        return cmd

    def think(
        self,
        user_input: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        interrupt_event: Optional[threading.Event] = None,
    ) -> str:
        self._history.append({"role": "user", "content": user_input})
        prompt = self._build_prompt()

        proc = subprocess.Popen(
            self._cmd(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except BrokenPipeError:
            pass

        streamed: List[str] = []
        final: List[Optional[str]] = [None]
        error: List[Optional[str]] = [None]
        stderr_buf: List[str] = []

        def _read_stdout():
            for line in proc.stdout:
                try:
                    evt = json.loads(line)
                except ValueError:
                    continue
                etype = evt.get("type")
                if etype == "stream_event":
                    inner = evt.get("event", {})
                    if inner.get("type") == "message_start" and streamed:
                        # New assistant turn after a tool call — separate paragraphs
                        streamed.append("\n")
                        if on_chunk:
                            on_chunk("\n")
                    delta = inner.get("delta", {})
                    if delta.get("type") == "text_delta":
                        text = delta.get("text", "")
                        streamed.append(text)
                        if on_chunk and text:
                            on_chunk(text)
                elif etype == "result":
                    if evt.get("is_error"):
                        error[0] = str(evt.get("result") or evt.get("subtype"))
                    else:
                        final[0] = evt.get("result")

        def _read_stderr():
            for line in proc.stderr:
                stderr_buf.append(line)

        t_out = threading.Thread(target=_read_stdout, daemon=True)
        t_err = threading.Thread(target=_read_stderr, daemon=True)
        t_out.start()
        t_err.start()

        # Poll for completion or interrupt
        while proc.poll() is None:
            if interrupt_event and interrupt_event.wait(timeout=0.05):
                proc.kill()
                proc.wait()
                self._history.pop()   # discard unanswered user turn
                raise InterruptedError("cancelled by user")

        t_out.join()
        t_err.join()

        if error[0] or proc.returncode != 0:
            self._history.pop()
            msg = error[0] or "".join(stderr_buf).strip()
            raise RuntimeError(msg[:400] or f"claude exited with {proc.returncode}")

        # `result` holds only the final answer (no "let me check…" preamble
        # from before tool calls) — that's what gets spoken and remembered.
        response = (final[0] or "".join(streamed)).strip()
        self._history.append({"role": "assistant", "content": response})
        if len(self._history) > _MAX_HISTORY:
            del self._history[: len(self._history) - _MAX_HISTORY]
        return response

    def _build_prompt(self) -> str:
        ctx = f"[Current date/time: {_now()}]"

        if len(self._history) == 1:
            return f"{ctx}\n\n{self._history[0]['content']}"

        lines = [ctx, "", "[Conversation so far]"]
        for msg in self._history[:-1]:
            speaker = "Manu" if msg["role"] == "user" else "JARVIS"
            lines.append(f"{speaker}: {msg['content']}")

        lines += [
            "",
            "[Current message from Manu]",
            self._history[-1]["content"],
            "",
            "Reply as JARVIS. Run bash commands for live system data.",
        ]
        return "\n".join(lines)

    def reset(self):
        self._history.clear()
