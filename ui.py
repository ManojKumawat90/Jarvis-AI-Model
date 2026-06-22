"""
JARVIS HUD v6 — Full-screen pygame UI
Layout:  LEFT: Sys Monitor  |  CENTER: JARVIS HUD  |  RIGHT: Mission Log + Command
"""
import math, os, queue, subprocess, threading, time, sys
from datetime import datetime
from typing import Callable, Optional, List, Tuple
import pygame

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = (3,   12,  24)
PANEL   = (7,   17,  30)
PANEL2  = (10,  26,  46)
PANEL3  = (5,   14,  26)
ACCENT  = (0,   212, 255)
CYAN2   = (0,   85,  119)
CYAN3   = (3,   18,  28)
GOLD    = (255, 194, 0)
GREEN   = (0,   232, 122)
RED     = (255, 64,  64)
ORANGE  = (255, 140, 0)
TEXT    = (184, 216, 240)
DIM     = (18,  48,  74)
DIM2    = (30,  64,  96)
WHITE   = (232, 244, 255)
PURPLE  = (160, 80,  255)

STATE_COLOR = {"IDLE": DIM2, "LISTENING": GREEN, "THINKING": GOLD, "SPEAKING": ACCENT}
STATE_LABEL = {"IDLE": "●  IDLE", "LISTENING": "◎  LISTENING",
               "THINKING": "⟳  THINKING", "SPEAKING": "▶  SPEAKING"}

TOP_H = 52
BOT_H = 52
LEFT_W  = 300
RIGHT_W = 430

QUICK_CMDS = [
    ("System Status",   "what is my system status right now"),
    ("What time?",      "what time is it"),
    ("Battery",         "how is my battery"),
    ("Running Apps",    "what apps are currently running"),
    ("CPU & RAM",       "show me cpu and ram usage"),
    ("Open Browser",    "open safari"),
]


# ── System Stats (background thread) ─────────────────────────────────────────

class _SysStats:
    def __init__(self):
        self.cpu_pct   = 0.0
        self.cpu_hist: List[float] = [0.0] * 60
        self.ram_pct   = 0.0
        self.ram_used  = 0.0
        self.ram_total = 0.0
        self.disk_pct  = 0.0
        self.disk_used = 0.0
        self.disk_total = 0.0
        self.bat_pct    = 100.0
        self.bat_charging = False
        self.net_rx    = 0.0   # KB/s
        self.net_tx    = 0.0
        self.procs: List[Tuple[str, float]] = []
        self._lock     = threading.Lock()
        self._net_prev = None
        self._net_t    = 0.0

    def snapshot(self):
        """Return a shallow copy of stats for the draw thread."""
        with self._lock:
            d = self.__dict__.copy()
            d['cpu_hist'] = list(self.cpu_hist)
            d['procs']    = list(self.procs)
        return d

    def _update(self):
        if not HAS_PSUTIL:
            return
        try:
            cpu  = psutil.cpu_percent(interval=None)
            ram  = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            bat  = psutil.sensors_battery()
            net  = psutil.net_io_counters()
            now  = time.time()

            rx = tx = 0.0
            if self._net_prev is not None and now > self._net_t:
                dt = now - self._net_t
                rx = (net.bytes_recv - self._net_prev.bytes_recv) / dt / 1024
                tx = (net.bytes_sent - self._net_prev.bytes_sent) / dt / 1024
            self._net_prev = net
            self._net_t    = now

            procs = []
            for p in psutil.process_iter(['name', 'cpu_percent']):
                try:
                    c = p.info['cpu_percent'] or 0.0
                    if c > 0.5:
                        procs.append((p.info['name'][:18], c))
                except Exception:
                    pass
            procs.sort(key=lambda x: x[1], reverse=True)

            with self._lock:
                self.cpu_pct   = cpu
                self.cpu_hist.pop(0)
                self.cpu_hist.append(cpu)
                self.ram_pct   = ram.percent
                self.ram_used  = ram.used  / 1024**3
                self.ram_total = ram.total / 1024**3
                self.disk_pct  = disk.percent
                self.disk_used  = disk.used  / 1024**3
                self.disk_total = disk.total / 1024**3
                if bat:
                    self.bat_pct      = bat.percent
                    self.bat_charging = bool(bat.power_plugged)
                self.net_rx = max(0.0, rx)
                self.net_tx = max(0.0, tx)
                self.procs  = procs[:6]
        except Exception:
            pass

    def start(self):
        def _loop():
            while True:
                self._update()
                time.sleep(1)
        threading.Thread(target=_loop, daemon=True).start()


# ── Main UI class ─────────────────────────────────────────────────────────────

class JarvisUI:
    on_activate:  Optional[Callable] = None
    on_sleep:     Optional[Callable] = None
    on_reset:     Optional[Callable] = None
    on_cmd:       Optional[Callable] = None   # called with text when user submits cmd
    on_interrupt: Optional[Callable] = None   # cancel current think/speak, stay in session

    def __init__(self):
        self._state       = "IDLE"
        self._angle       = 0.0
        self._visible     = False
        self._audio_level = 0.0
        self._lvl_lock    = threading.Lock()
        self._eq_bars     = [0.0] * 32
        self._cmd_q: queue.Queue = queue.Queue()
        self._running     = False

        self._status_text     = "Double-clap or say  'Hey JARVIS'"
        self._transcript_text = "—"
        self._response_text   = "—"

        # Conversation log  [(role, text, hh:mm)]
        self._log: List[Tuple[str, str, str]] = []
        self._log_scroll  = 0        # pixel scroll offset
        self._log_max_scroll = 0

        # Text input
        self._input_text  = ""
        self._input_blink = 0.0
        self._dropped_file: Optional[str] = None

        # Fade overlay
        self._fade_alpha  = 255
        self._fade_target = 255

        # Drag
        self._dragging   = False
        self._drag_off   = (0, 0)

        # Sys stats
        self._sys = _SysStats()
        self._sys.start()

        self._fonts: dict = {}
        self._screen: Optional[pygame.Surface] = None

        # Layout (computed in run())
        self.SW = self.SH = 0
        self.CENTER_W = 0
        self.HUD_R = 0
        self.HUD_CX = self.HUD_CY = 0
        self.BODY_Y = TOP_H + 2
        self.BODY_H = 0
        self._btn_rects: dict = {}
        self._quick_rects: List[Tuple[pygame.Rect, str]] = []
        self._right_log_rect: Optional[pygame.Rect] = None

    def attach(self, root=None):
        pass  # no-op

    # ── Main loop ─────────────────────────────────────────────────────────────

    def run(self):
        os.environ["SDL_VIDEO_WINDOW_POS"] = "0,0"   # pin to top-left, no centering
        pygame.init()
        pygame.key.set_repeat(400, 40)

        info = pygame.display.Info()
        self.SW = info.current_w
        self.SH = info.current_h

        self._screen = pygame.display.set_mode(
            (self.SW, self.SH), pygame.NOFRAME | pygame.HWSURFACE | pygame.DOUBLEBUF
        )
        pygame.display.set_caption("J.A.R.V.I.S")

        # Allow file drops
        pygame.event.set_allowed(None)
        pygame.event.set_allowed([pygame.QUIT, pygame.KEYDOWN, pygame.MOUSEBUTTONDOWN,
                                   pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION,
                                   pygame.MOUSEWHEEL, pygame.DROPFILE])

        self._load_fonts()
        self._compute_layout()
        self._running = True
        clock = pygame.time.Clock()

        while self._running:
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    self._running = False
                elif ev.type == pygame.KEYDOWN:
                    self._handle_key(ev)
                elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if not self._handle_click(ev.pos):
                        if ev.pos[1] < TOP_H:
                            self._dragging = True
                            wp = self._get_win_pos()
                            self._drag_off = (ev.pos[0]-wp[0], ev.pos[1]-wp[1])
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    self._dragging = False
                elif ev.type == pygame.MOUSEMOTION:
                    if self._dragging:
                        self._set_win_pos(ev.pos[0]-self._drag_off[0],
                                          ev.pos[1]-self._drag_off[1])
                elif ev.type == pygame.MOUSEWHEEL:
                    mp = pygame.mouse.get_pos()
                    if self._right_log_rect and self._right_log_rect.collidepoint(mp):
                        self._log_scroll = max(0, min(
                            self._log_scroll - ev.y * 24,
                            max(0, self._log_max_scroll)
                        ))
                elif ev.type == pygame.DROPFILE:
                    self._dropped_file = ev.file
                    self._cmd_q.put(lambda f=ev.file:
                                    setattr(self, '_dropped_file', f))

            while True:
                try:
                    self._cmd_q.get_nowait()()
                except queue.Empty:
                    break

            # Fade
            if   self._fade_target < self._fade_alpha:
                self._fade_alpha = max(self._fade_target, self._fade_alpha - 20)
            elif self._fade_target > self._fade_alpha:
                self._fade_alpha = min(self._fade_target, self._fade_alpha + 20)

            t   = time.monotonic()
            self._angle = (self._angle + 3) % 360
            self._input_blink = t
            with self._lvl_lock:
                lvl = self._audio_level

            self._screen.fill(BG)
            if self._visible:
                self._draw_full(t, lvl)
            else:
                self._draw_idle(t)

            if self._fade_alpha > 0:
                ov = pygame.Surface((self.SW, self.SH))
                ov.fill((0, 0, 0))
                ov.set_alpha(self._fade_alpha)
                self._screen.blit(ov, (0, 0))

            pygame.display.flip()
            clock.tick(30)

        pygame.quit()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _compute_layout(self):
        SW, SH = self.SW, self.SH
        self.BODY_H   = SH - TOP_H - BOT_H - 4
        self.CENTER_W = SW - LEFT_W - RIGHT_W
        self.HUD_R    = min(self.CENTER_W // 2 - 60, self.BODY_H // 2 - 100)
        self.HUD_CX   = LEFT_W + self.CENTER_W // 2
        self.HUD_CY   = self.BODY_Y + self.HUD_R + 50

        btn_y = SH - BOT_H + 12
        self._btn_rects = {
            "activate": pygame.Rect(16,  btn_y, 148, 28),
            "sleep":    pygame.Rect(172, btn_y, 110, 28),
            "reset":    pygame.Rect(290, btn_y, 100, 28),
        }

        # Quick-command buttons (right panel)
        rx = SW - RIGHT_W + 12
        qy = self.BODY_Y + 20
        self._quick_rects = []
        col_w = (RIGHT_W - 28) // 2
        for i, (label, cmd) in enumerate(QUICK_CMDS):
            c = i % 2; r = i // 2
            rect = pygame.Rect(rx + c*(col_w+4), qy + r*34, col_w, 26)
            self._quick_rects.append((rect, cmd, label))

        # Right log area (for scroll hit-testing)
        log_top = self.BODY_Y + 20 + ((len(QUICK_CMDS)+1)//2)*34 + 50
        self._right_log_rect = pygame.Rect(
            SW - RIGHT_W, log_top, RIGHT_W, SH - BOT_H - 4 - log_top - 120
        )

    def _load_fonts(self):
        def f(name, size, bold=False):
            try:
                return pygame.font.SysFont(name, size, bold=bold)
            except Exception:
                return pygame.font.SysFont("monospace", size, bold=bold)
        self._fonts = {
            "title":  f("Monaco", 20, bold=True),
            "title2": f("Monaco", 15, bold=True),
            "sub":    f("Monaco",  9),
            "state":  f("Monaco", 11, bold=True),
            "label":  f("Monaco",  8, bold=True),
            "label2": f("Monaco",  7, bold=True),
            "panel":  f("Monaco", 11),
            "small":  f("Monaco",  8),
            "small2": f("Monaco",  7),
            "btn":    f("Monaco",  9, bold=True),
            "hud":    f("Monaco",  9, bold=True),
            "input":  f("Monaco", 12),
            "log":    f("Monaco", 10),
            "log2":   f("Monaco",  9),
            "clock":  f("Monaco", 24, bold=True),
            "clock2": f("Monaco", 10),
            "metric": f("Monaco", 13, bold=True),
            "metric2":f("Monaco",  9),
        }

    # ── Idle screen ───────────────────────────────────────────────────────────

    def _draw_idle(self, t: float):
        s = self._screen
        SW, SH = self.SW, self.SH

        # Grid
        for y in range(0, SH, 26): pygame.draw.line(s, CYAN3, (0,y), (SW,y))
        for x in range(0, SW, 44): pygame.draw.line(s, CYAN3, (x,0), (x,SH))

        pygame.draw.rect(s, PANEL, (0, 0, SW, TOP_H))
        self._t(s,"title","J.A.R.V.I.S", ACCENT, 24, 15)
        self._t(s,"sub","STANDBY  ·  Double-clap or say  'Hey JARVIS'  to activate",
                DIM2, 240, 22)
        pygame.draw.rect(s, DIM, (0, TOP_H, SW, 2))

        # Pulsing HUD in centre
        cx, cy = SW//2, SH//2
        for r2, co in [(200,DIM),(160,CYAN3),(80,DIM)]:
            pygame.draw.circle(s, co, (cx,cy), r2, 1)
        a1 = self._angle % 360
        self._arc(s, DIM2, cx, cy, 180, a1,   200, 2)
        self._arc(s, DIM,  cx, cy, 150, -a1+60,140, 1)
        p = 0.5+0.5*math.sin(t*1.2); rc = int(10+p*6)
        pygame.draw.circle(s, DIM2, (cx,cy), rc)
        self._tc(s,"state","STANDBY", DIM2, cx, cy+50)
        self._tc(s,"sub","DOUBLE-CLAP  or  say  'HEY JARVIS'  to activate", DIM2, cx, cy+74)

        # Clock bottom-left
        now = datetime.now()
        self._t(s,"clock2", now.strftime("%H:%M:%S"), DIM2, 20, SH-40)

    # ── Full HUD ──────────────────────────────────────────────────────────────

    def _draw_full(self, t: float, lvl: float):
        s  = self._screen
        SW, SH = self.SW, self.SH

        # Grid
        for y in range(0, SH, 26): pygame.draw.line(s, CYAN3, (0,y), (SW,y))
        for x in range(0, SW, 44): pygame.draw.line(s, CYAN3, (x,0), (x,SH))

        self._draw_top_bar(s, t)
        self._draw_sys_monitor(s, t)
        self._draw_center(s, t, lvl)
        self._draw_right(s, t)
        self._draw_bottom_bar(s)

    # ── Top bar ───────────────────────────────────────────────────────────────

    def _draw_top_bar(self, s, t):
        SW = self.SW
        pygame.draw.rect(s, PANEL, (0, 0, SW, TOP_H))
        self._t(s,"title","J.A.R.V.I.S", ACCENT, 20, 14)
        self._t(s,"sub","Just A Rather Very Intelligent System", DIM2, 210, 22)

        # State chip
        col = STATE_COLOR.get(self._state, DIM2)
        lbl = STATE_LABEL.get(self._state, self._state)
        sw  = self._fonts["state"].size(lbl)[0]
        pygame.draw.rect(s, DIM, (SW//2 - sw//2 - 14, 12, sw+28, 28), border_radius=4)
        pygame.draw.rect(s, col, (SW//2 - sw//2 - 14, 12, sw+28, 28), 1, border_radius=4)
        self._tc(s,"state", lbl, col, SW//2, 26)

        # Clock top-right
        now = datetime.now()
        self._t(s,"clock2", now.strftime("%a %d %b  %H:%M:%S"), TEXT, SW-230, 20)

        # Escape hint
        self._t(s,"small2","[ESC] exit", DIM2, SW-60, 20)

        pygame.draw.rect(s, ACCENT, (0, TOP_H, SW, 2))

    # ── Left panel: Sys Monitor ───────────────────────────────────────────────

    def _draw_sys_monitor(self, s, t):
        x, y = 0, self.BODY_Y
        w, h = LEFT_W, self.BODY_H
        stats = self._sys.snapshot()

        # Background
        pygame.draw.rect(s, PANEL3, (x, y, w, h))
        pygame.draw.rect(s, DIM,    (x+w-1, y, 1, h))  # right border

        # Section header
        self._section_hdr(s, x+10, y+10, w-20, "⬡  SYS MONITOR", ACCENT)
        oy = y + 38

        # ── Clock ──────────────────────────────────────────────────────────
        now = datetime.now()
        self._tc(s,"clock", now.strftime("%H:%M"), TEXT, x+w//2, oy+18)
        self._tc(s,"clock2", now.strftime("%A, %d %B %Y"), DIM2, x+w//2, oy+46)
        oy += 68

        pygame.draw.line(s, DIM, (x+8, oy), (x+w-8, oy))
        oy += 10

        # ── CPU ──────────────────────────────────────────────────────────
        cpu = stats['cpu_pct']
        col = RED if cpu>80 else (GOLD if cpu>50 else GREEN)
        self._label_val(s, x+10, oy, "CPU", f"{cpu:.0f}%", col, w)
        oy += 20
        self._bar(s, x+10, oy, w-20, 8, cpu/100, col)
        oy += 14

        # CPU history graph
        gh = 50; gw = w - 20
        pygame.draw.rect(s, (5,14,26), (x+10, oy, gw, gh))
        pygame.draw.rect(s, DIM, (x+10, oy, gw, gh), 1)
        hist = stats['cpu_hist']
        if len(hist) > 1:
            pts = []
            for i, v in enumerate(hist):
                px = x + 10 + int(i * gw / (len(hist)-1))
                py = oy + gh - 2 - int(v / 100 * (gh-4))
                pts.append((px, py))
            if len(pts) > 1:
                pygame.draw.lines(s, GREEN, False, pts, 1)
                # Fill under graph
                fill_pts = [(x+10, oy+gh-1)] + pts + [(pts[-1][0], oy+gh-1)]
                surf = pygame.Surface((gw, gh), pygame.SRCALPHA)
                fp = [(p[0]-(x+10), p[1]-oy) for p in fill_pts]
                pygame.draw.polygon(surf, (*GREEN, 35), fp)
                s.blit(surf, (x+10, oy))
        self._t(s,"small2","60s", DIM2, x+10, oy+gh-10)
        oy += gh + 10

        # ── RAM ──────────────────────────────────────────────────────────
        ram_pct = stats['ram_pct']
        col = RED if ram_pct>85 else (GOLD if ram_pct>65 else ACCENT)
        used  = stats['ram_used'];  total = stats['ram_total']
        self._label_val(s, x+10, oy, "MEMORY",
                        f"{used:.1f} / {total:.0f} GB  {ram_pct:.0f}%", col, w)
        oy += 18
        self._bar(s, x+10, oy, w-20, 8, ram_pct/100, col)
        oy += 18

        # ── Disk ─────────────────────────────────────────────────────────
        disk_pct = stats['disk_pct']
        col = RED if disk_pct>90 else (GOLD if disk_pct>70 else TEXT)
        du = stats['disk_used']; dt_ = stats['disk_total']
        self._label_val(s, x+10, oy, "DISK",
                        f"{du:.0f} / {dt_:.0f} GB  {disk_pct:.0f}%", col, w)
        oy += 18
        self._bar(s, x+10, oy, w-20, 8, disk_pct/100, col)
        oy += 18

        # ── Battery ──────────────────────────────────────────────────────
        bat = stats['bat_pct']; chg = stats['bat_charging']
        col = GREEN if chg else (RED if bat<20 else (GOLD if bat<40 else TEXT))
        icon = " ⚡" if chg else ""
        self._label_val(s, x+10, oy, "BATTERY", f"{bat:.0f}%{icon}", col, w)
        oy += 18
        self._bar(s, x+10, oy, w-20, 8, bat/100, col)
        oy += 18

        pygame.draw.line(s, DIM, (x+8, oy), (x+w-8, oy))
        oy += 8

        # ── Network ──────────────────────────────────────────────────────
        rx = stats['net_rx']; tx = stats['net_tx']
        def fmt_net(kbps):
            return f"{kbps/1024:.1f} MB/s" if kbps>1024 else f"{kbps:.0f} KB/s"
        self._t(s,"label","NETWORK", DIM2, x+10, oy)
        oy += 14
        self._t(s,"small2", f"↓ {fmt_net(rx)}", GREEN, x+14, oy)
        self._t(s,"small2", f"↑ {fmt_net(tx)}", GOLD,  x+14, oy+12)
        oy += 30

        pygame.draw.line(s, DIM, (x+8, oy), (x+w-8, oy))
        oy += 8

        # ── Top Processes ─────────────────────────────────────────────────
        self._t(s,"label","TOP PROCESSES", DIM2, x+10, oy)
        oy += 14
        for name, cpu_p in stats['procs'][:5]:
            col = RED if cpu_p>50 else (GOLD if cpu_p>20 else TEXT)
            self._t(s,"small2", name[:20], TEXT, x+14, oy)
            self._t(s,"small2", f"{cpu_p:.0f}%", col, x+w-40, oy)
            self._bar(s, x+14, oy+11, w-28, 4,
                      min(cpu_p/100, 1.0), col)
            oy += 22
            if oy > y + h - 20:
                break

    # ── Center: JARVIS HUD ────────────────────────────────────────────────────

    def _draw_center(self, s, t: float, lvl: float):
        cx  = self.HUD_CX
        cy  = self.HUD_CY
        r   = self.HUD_R
        col = STATE_COLOR.get(self._state, DIM2)
        SW, SH = self.SW, self.SH

        # Vertical dividers
        pygame.draw.line(s, DIM, (LEFT_W, self.BODY_Y), (LEFT_W, SH-BOT_H-4))
        pygame.draw.line(s, DIM, (SW-RIGHT_W, self.BODY_Y), (SW-RIGHT_W, SH-BOT_H-4))

        # Title above HUD
        self._tc(s,"title2","CORE INTELLIGENCE MATRIX", DIM2, cx, self.BODY_Y+18)

        # Corner brackets
        for ox, oy_, sx, sy in [
            (LEFT_W+8, self.BODY_Y+4, 1,1),(SW-RIGHT_W-8, self.BODY_Y+4,-1,1),
            (LEFT_W+8, SH-BOT_H-8, 1,-1),(SW-RIGHT_W-8, SH-BOT_H-8,-1,-1),
        ]:
            pygame.draw.line(s, CYAN2, (ox,oy_),(ox+sx*22,oy_))
            pygame.draw.line(s, CYAN2, (ox,oy_),(ox,oy_+sy*22))

        # ── HUD rings ─────────────────────────────────────────────────────────
        # Outer ring + tick marks
        for deg in range(0, 360, 10):
            rad  = math.radians(deg - 90)
            long = deg % 90 == 0
            r1   = r + (4 if long else 8)
            x1 = int(cx + r1*math.cos(rad));      y1 = int(cy + r1*math.sin(rad))
            x2 = int(cx + (r+16)*math.cos(rad));  y2 = int(cy + (r+16)*math.sin(rad))
            pygame.draw.line(s, col if long else DIM, (x1,y1),(x2,y2),
                             2 if long else 1)

        # Static rings
        for r2, co, w2 in [(r, DIM, 1), (r-24, DIM, 1), (r-50, DIM, 1), (44, DIM, 1)]:
            if r2 > 0: pygame.draw.circle(s, co, (cx,cy), r2, w2)

        # Waveform rings
        if self._state == "SPEAKING":
            self._waveform_ring(s, cx, cy, t, int(r*0.48))
        elif self._state == "LISTENING":
            self._listen_ring(s, cx, cy, t, lvl, int(r*0.48))

        # Rotating arcs
        spd = {"IDLE":0.4,"LISTENING":1.4,"THINKING":3.2,"SPEAKING":1.8}
        sp  = spd.get(self._state, 1.0)
        a1  = self._angle * sp % 360
        self._arc(s, col,    cx, cy, r-2,   a1,         220, 3)
        self._arc(s, CYAN2,  cx, cy, r-28,  -a1+80,     160, 2)
        self._arc(s, DIM2,   cx, cy, r-58,  a1*1.3,      90, 1)
        self._arc(s, DIM,    cx, cy, int(r*0.42), -a1*0.7, 70, 1)
        self._arc(s, DIM,    cx, cy, int(r*0.38),  a1*0.5+120, 50, 1)

        # Centre core
        if self._state == "THINKING":
            p  = 0.5+0.5*math.sin(t*6); rc = int(22+p*14)
            pygame.draw.circle(s, GOLD,   (cx,cy), rc)
            pygame.draw.circle(s, (40,30,0), (cx,cy), rc-4)
        elif self._state == "SPEAKING":
            p  = 0.5+0.5*math.sin(t*10); rc = int(14+p*10)
            pygame.draw.circle(s, ACCENT, (cx,cy), rc)
            pygame.draw.circle(s, (0,30,40), (cx,cy), rc-3)
        elif self._state == "LISTENING":
            rc = int(16+lvl*28)
            pygame.draw.circle(s, GREEN, (cx,cy), rc)
            pygame.draw.circle(s, BG,    (cx,cy),  5)
        else:
            pygame.draw.circle(s, DIM, (cx,cy), 14)

        # State label
        self._tc(s,"hud", STATE_LABEL.get(self._state, self._state), col, cx, cy+r+28)

        # ── EQ bars below HUD ──────────────────────────────────────────────────
        eq_x  = LEFT_W + 20
        eq_y  = cy + r + 50
        eq_w  = self.CENTER_W - 40
        eq_h  = 50
        if eq_y + eq_h < SH - BOT_H - 20:
            pygame.draw.rect(s, PANEL2, (eq_x, eq_y, eq_w, eq_h))
            pygame.draw.rect(s, DIM,    (eq_x, eq_y, eq_w, eq_h), 1)
            self._draw_eq(s, eq_x, eq_y, eq_w, eq_h, t, lvl)

        # ── Status text ───────────────────────────────────────────────────────
        st_y = cy - r - 36
        if st_y > self.BODY_Y + 36:
            self._tc(s,"small", self._status_text, DIM2, cx, st_y)

    def _draw_eq(self, s, ex, ey, ew, eh, t, lvl):
        n     = len(self._eq_bars)
        col   = STATE_COLOR.get(self._state, DIM2)
        bw    = (ew - 2) / n

        for i in range(n):
            if   self._state == "LISTENING": tgt = lvl*(0.5+0.5*abs(math.sin(t*3.5+i*0.45)))
            elif self._state == "THINKING":  tgt = 0.10+0.20*abs(math.sin(t*5.0+i*0.38))
            elif self._state == "SPEAKING":  tgt = 0.18+0.36*abs(math.sin(t*7.0+i*0.52))
            else:                            tgt = 0.03+0.07*abs(math.sin(t*1.2+i*0.25))

            prev = self._eq_bars[i]
            self._eq_bars[i] = (tgt*0.65+prev*0.35) if tgt>prev else (tgt*0.08+prev*0.92)
            bh = max(2, int(self._eq_bars[i]*(eh-6)))
            x0 = int(ex+1+i*bw); bwi = max(1,int(bw-1))
            pygame.draw.rect(s, col, (x0, ey+eh-bh-3, bwi, bh))
            if self._eq_bars[i] > 0.7:
                pygame.draw.rect(s, WHITE, (x0, ey+eh-bh-3, bwi, 2))

    # ── Right panel ───────────────────────────────────────────────────────────

    def _draw_right(self, s, t):
        SW, SH = self.SW, self.SH
        rx = SW - RIGHT_W
        ry = self.BODY_Y
        rh = SH - BOT_H - 4 - ry

        pygame.draw.rect(s, PANEL3, (rx, ry, RIGHT_W, rh))

        # ─ Quick Intel ────────────────────────────────────────────────────────
        self._section_hdr(s, rx+10, ry+10, RIGHT_W-20, "⚡  QUICK INTEL", GOLD)
        mp = pygame.mouse.get_pos()
        for rect, cmd, label in self._quick_rects:
            hov = rect.collidepoint(mp)
            pygame.draw.rect(s, GOLD if hov else (12,28,46), rect, border_radius=3)
            pygame.draw.rect(s, GOLD, rect, 1, border_radius=3)
            tc = BG if hov else GOLD
            self._tc(s,"small", label, tc, rect.centerx, rect.centery)

        # ─ Mission Log ────────────────────────────────────────────────────────
        log_y = self._quick_rects[-1][0].bottom + 14 if self._quick_rects else ry+20
        self._section_hdr(s, rx+10, log_y, RIGHT_W-20, "◈  MISSION LOG", ACCENT)
        log_area_y  = log_y + 26
        log_area_h  = rh - (log_area_y - ry) - 136   # leave room for input+file
        self._right_log_rect = pygame.Rect(rx, log_area_y, RIGHT_W, log_area_h)

        # Clip and scroll
        clip = s.get_clip()
        s.set_clip(self._right_log_rect)
        self._draw_log(s, rx+8, log_area_y, RIGHT_W-16, log_area_h, t)
        s.set_clip(clip)
        pygame.draw.rect(s, DIM, self._right_log_rect, 1)

        # ─ Command input ──────────────────────────────────────────────────────
        inp_y = log_area_y + log_area_h + 6
        self._section_hdr(s, rx+10, inp_y, RIGHT_W-20, "▸  COMMAND", TEXT)
        inp_box_y = inp_y + 22
        inp_box_h = 34
        pygame.draw.rect(s, (8,22,38), (rx+8, inp_box_y, RIGHT_W-16, inp_box_h))
        pygame.draw.rect(s, ACCENT,    (rx+8, inp_box_y, RIGHT_W-16, inp_box_h), 1)
        display_text = self._input_text or ""
        cursor = "│" if int(time.monotonic()*2) % 2 == 0 else " "
        self._t(s,"input", display_text + cursor, TEXT, rx+14, inp_box_y+9)
        self._t(s,"small2","Enter to send", DIM2, rx+RIGHT_W-80, inp_box_y+inp_box_h+3)

        # ─ File drop ──────────────────────────────────────────────────────────
        fd_y  = inp_box_y + inp_box_h + 20
        fd_h  = max(30, ry + rh - fd_y - 6)
        fname = os.path.basename(self._dropped_file) if self._dropped_file else None
        col_fd = GREEN if fname else DIM2
        pygame.draw.rect(s, (5,15,8) if fname else (5,12,20),
                         (rx+8, fd_y, RIGHT_W-16, fd_h), border_radius=4)
        pygame.draw.rect(s, col_fd, (rx+8, fd_y, RIGHT_W-16, fd_h), 1, border_radius=4)
        msg = f"📎 {fname}" if fname else "  ⬇  Drag & Drop File Here"
        self._tc(s,"small", msg, col_fd, rx+RIGHT_W//2, fd_y+fd_h//2)

    def _draw_log(self, s, x, y, w, h, t):
        """Render conversation log with scrolling."""
        f  = self._fonts["log"]
        f2 = self._fonts["log2"]
        lh = 16
        total_h = 0

        entries = []
        for role, text, ts in self._log:
            color = ACCENT if role == "jarvis" else GOLD
            prefix = f"[{ts}] {'JARVIS' if role=='jarvis' else 'YOU'}:"
            words  = text.split()
            lines  = [""]
            for word in words:
                test = lines[-1] + (" " if lines[-1] else "") + word
                if f.size(test)[0] <= w - 20:
                    lines[-1] = test
                else:
                    lines.append(word)
            entries.append((prefix, lines, color))
            total_h += (1 + len(lines)) * lh + 6

        self._log_max_scroll = max(0, total_h - h + 20)

        draw_y = y - self._log_scroll + 4
        for prefix, lines, color in entries:
            s.blit(f2.render(prefix, True, DIM2), (x+4, draw_y))
            draw_y += lh
            for line in lines:
                if y <= draw_y < y + h:
                    s.blit(f.render(line, True, color), (x+12, draw_y))
                draw_y += lh
            draw_y += 6

        if not self._log:
            self._tc(s,"small2","No conversation yet", DIM2, x+w//2, y+h//2)

    # ── Bottom bar ────────────────────────────────────────────────────────────

    def _draw_bottom_bar(self, s):
        SW, SH = self.SW, self.SH
        pygame.draw.rect(s, CYAN2,  (0, SH-BOT_H-2, SW, 2))
        pygame.draw.rect(s, PANEL,  (0, SH-BOT_H, SW, BOT_H))

        mp = pygame.mouse.get_pos()
        busy = self._state in ("THINKING", "SPEAKING")
        labels = {
            "activate": ("◉  ACTIVATE", GREEN),
            "sleep":    ("⊘  STOP", RED) if busy else ("◌  SLEEP", GOLD),
            "reset":    ("↺  RESET",    TEXT),
        }
        for action, rect in self._btn_rects.items():
            lbl, fg = labels[action]
            hov = rect.collidepoint(mp)
            pygame.draw.rect(s, fg if hov else (5,17,31), rect, border_radius=3)
            pygame.draw.rect(s, fg, rect, 1, border_radius=3)
            self._tc(s,"btn", lbl, BG if hov else fg, rect.centerx, rect.centery)

        self._t(s,"small2",
                "DOUBLE-CLAP  or  'HEY JARVIS'  to activate  ·  'GOODBYE JARVIS'  to sleep  ·  ESC to exit",
                DIM2, SW-16, SH-BOT_H+BOT_H//2-4, anchor="e")

    # ── Drawing primitives ────────────────────────────────────────────────────

    def _arc(self, s, color, cx, cy, r, start_deg, extent_deg, width=1):
        if r <= 0: return
        rect = pygame.Rect(cx-r, cy-r, r*2, r*2)
        end   = math.pi/2 - math.radians(start_deg)
        start = math.pi/2 - math.radians(start_deg + extent_deg)
        try: pygame.draw.arc(s, color, rect, start, end, max(1,width))
        except Exception: pass

    def _waveform_ring(self, s, cx, cy, t, r0):
        n = 80; pts = []
        for i in range(n):
            a = 2*math.pi*i/n - math.pi/2
            w = (0.50*math.sin(3*a+t*10)+0.22*math.sin(7*a-t*7)
                +0.12*math.sin(13*a+t*4)+0.07*math.sin(19*a-t*2))
            r = r0 + w*22
            pts.append((int(cx+r*math.cos(a)), int(cy+r*math.sin(a))))
        if len(pts)>2: pygame.draw.lines(s, ACCENT, True, pts, 2)

    def _listen_ring(self, s, cx, cy, t, lvl, r0):
        n = 64; pts = []
        for i in range(n):
            a = 2*math.pi*i/n - math.pi/2
            w = (0.5+0.5*abs(math.sin(a*5+t*4))) * max(lvl, 0.05)
            r = r0 + w*36
            pts.append((int(cx+r*math.cos(a)), int(cy+r*math.sin(a))))
        if len(pts)>2: pygame.draw.lines(s, GREEN, True, pts, 2)

    def _bar(self, s, x, y, w, h, frac, col):
        frac = max(0.0, min(1.0, frac))
        pygame.draw.rect(s, DIM, (x, y, w, h), border_radius=2)
        if frac > 0:
            pygame.draw.rect(s, col, (x, y, int(w*frac), h), border_radius=2)

    def _section_hdr(self, s, x, y, w, text, col):
        self._t(s,"label", text, col, x, y)
        pygame.draw.line(s, DIM, (x, y+14), (x+w, y+14))

    def _t(self, s, key, text, color, x, y, anchor="w"):
        f = self._fonts.get(key)
        if not f: return
        surf = f.render(str(text), True, color)
        if anchor == "e": s.blit(surf, (x-surf.get_width(), y))
        else:             s.blit(surf, (x, y))

    def _tc(self, s, key, text, color, cx, cy):
        f = self._fonts.get(key)
        if not f: return
        surf = f.render(str(text), True, color)
        s.blit(surf, (cx-surf.get_width()//2, cy-surf.get_height()//2))

    def _label_val(self, s, x, y, label, val, col, w):
        self._t(s,"label",  label, DIM2, x, y)
        vw = self._fonts["metric2"].size(val)[0]
        self._t(s,"metric2", val, col, x+w-24-vw, y)

    # ── Event handling ────────────────────────────────────────────────────────

    def _handle_key(self, ev):
        if ev.key == pygame.K_ESCAPE:
            # ESC during think/speak = interrupt; otherwise exit app
            if self._state in ("THINKING", "SPEAKING") and self.on_interrupt:
                threading.Thread(target=self.on_interrupt, daemon=True).start()
            else:
                self._running = False
            return
        if ev.key == pygame.K_RETURN or ev.key == pygame.K_KP_ENTER:
            self._submit_command()
            return
        if ev.key == pygame.K_BACKSPACE:
            self._input_text = self._input_text[:-1]
            return
        if ev.key == pygame.K_v and (ev.mod & pygame.KMOD_META):
            # Cmd+V paste on macOS
            try:
                clip = subprocess.run(["pbpaste"], capture_output=True, text=True).stdout
                self._input_text += clip.strip()
            except Exception:
                pass
            return
        if ev.unicode and ev.unicode.isprintable():
            self._input_text += ev.unicode

    def _submit_command(self):
        text = self._input_text.strip()
        if not text:
            return
        self._input_text = ""
        if self._dropped_file:
            try:
                content = open(self._dropped_file).read(4000)
                text = f"{text}\n\n[File: {os.path.basename(self._dropped_file)}]\n{content}"
            except Exception:
                pass
        self.add_to_log("user", text.split("\n")[0])
        if self.on_cmd:
            threading.Thread(target=self.on_cmd, args=(text,), daemon=True).start()
        elif self.on_activate:
            # store typed cmd and trigger activate flow
            self._pending_cmd = text
            threading.Thread(target=self.on_activate, daemon=True).start()

    def _handle_click(self, pos) -> bool:
        if not self._visible:
            return False
        # Bottom buttons
        for action, rect in self._btn_rects.items():
            if rect.collidepoint(pos):
                cb = getattr(self, f"on_{action}", None)
                if cb: threading.Thread(target=cb, daemon=True).start()
                return True
        # Quick intel
        for rect, cmd, _ in self._quick_rects:
            if rect.collidepoint(pos):
                self.add_to_log("user", cmd)
                if self.on_cmd:
                    threading.Thread(target=self.on_cmd, args=(cmd,), daemon=True).start()
                return True
        return False

    # ── Window move ───────────────────────────────────────────────────────────

    def _get_win_pos(self):
        try:
            from pygame._sdl2.video import Window as W
            return W.from_display_module().position
        except Exception: return (0,0)

    def _set_win_pos(self, x, y):
        try:
            from pygame._sdl2.video import Window as W
            W.from_display_module().position = (x, y)
        except Exception: pass

    # ── Public API (thread-safe) ──────────────────────────────────────────────

    def update_level(self, rms: float):
        with self._lvl_lock:
            self._audio_level = rms

    def set_state(self, state: str):
        self._state = state

    def show(self, status: str = "JARVIS ONLINE"):
        def _do():
            self._visible     = True
            self._fade_target = 0
            self._status_text = status
            self._transcript_text = "—"
            self._response_text   = "—"
        self._cmd_q.put(_do)

    def hide(self):
        def _do():
            self._fade_target = 255
        self._cmd_q.put(_do)
        def _later():
            time.sleep(0.45)
            self._cmd_q.put(lambda: setattr(self, '_visible', False))
        threading.Thread(target=_later, daemon=True).start()

    def set_status(self, text: str):
        self._cmd_q.put(lambda: setattr(self, '_status_text', text or "—"))

    def set_transcript(self, text: str):
        self._cmd_q.put(lambda: setattr(self, '_transcript_text', text or "—"))

    def set_response(self, text: str):
        self._cmd_q.put(lambda: setattr(self, '_response_text', text or "—"))

    def append_response(self, chunk: str):
        def _do():
            cur = self._response_text
            self._response_text = ("" if cur == "—" else cur) + chunk
        self._cmd_q.put(_do)

    def add_to_log(self, role: str, text: str):
        ts = datetime.now().strftime("%H:%M")
        def _do():
            self._log.append((role, text.strip(), ts))
            if len(self._log) > 200:
                self._log.pop(0)
            # Auto-scroll to bottom
            self._log_scroll = 999999
        self._cmd_q.put(_do)
