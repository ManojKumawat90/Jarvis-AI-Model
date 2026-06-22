"""
Uses the `claude` CLI (claude.ai login) with full Bash tool access.
No ANTHROPIC_API_KEY needed.
"""
import datetime
import shutil
import subprocess
import threading
import time
from typing import Callable, List, Optional

from config import SYSTEM_PROMPT

_CLAUDE = shutil.which("claude") or "claude"


def _now() -> str:
    return datetime.datetime.now().strftime("%A %d %B %Y, %I:%M %p")


class JarvisBrain:
    def __init__(self):
        self._history: List[dict] = []

    def think(
        self,
        user_input: str,
        on_chunk: Optional[Callable[[str], None]] = None,
        interrupt_event: Optional[threading.Event] = None,
    ) -> str:
        self._history.append({"role": "user", "content": user_input})
        prompt = self._build_prompt()

        proc = subprocess.Popen(
            [
                _CLAUDE, "-p",
                "--output-format", "text",
                "--system-prompt", SYSTEM_PROMPT,
                "--allowedTools", "Bash",
                "--dangerously-skip-permissions",
            ],
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

        # Read stdout/stderr on background threads so the main loop stays free
        stdout_buf: List[str] = []
        stderr_buf: List[str] = []

        def _read(stream, buf):
            for line in stream:
                buf.append(line)

        t_out = threading.Thread(target=_read, args=(proc.stdout, stdout_buf), daemon=True)
        t_err = threading.Thread(target=_read, args=(proc.stderr, stderr_buf), daemon=True)
        t_out.start()
        t_err.start()

        # Poll for completion or interrupt
        while proc.poll() is None:
            if interrupt_event and interrupt_event.is_set():
                proc.kill()
                proc.wait()
                self._history.pop()   # discard unanswered user turn
                raise InterruptedError("cancelled by user")
            time.sleep(0.05)

        t_out.join()
        t_err.join()

        if proc.returncode != 0:
            raise RuntimeError("".join(stderr_buf).strip()[:400])

        response = "".join(stdout_buf).strip()
        self._history.append({"role": "assistant", "content": response})

        if on_chunk:
            on_chunk(response)

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
