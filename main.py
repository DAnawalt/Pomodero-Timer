"""
╔══════════════════════════════════════════╗
║   POMODORO — Retro-Terminal Timer        ║
║   Linux Mint: Sounds + Notifications     ║
╚══════════════════════════════════════════╝

DEPENDENCIES (all standard on Linux Mint):
  - notify-send   (libnotify-bin)   → desktop popups
  - paplay        (pulseaudio-utils) → audio playback
  - Python stdlib: wave, struct, threading, csv

Install if missing:
  sudo apt install libnotify-bin pulseaudio-utils

CHANGES vs original:
  - Tick sound now only plays during BREAK modes (not during WORK/focus)
  - Each completed session is logged to an in-memory list
  - "💾 EXPORT CSV" button writes ~/pomodoro_log_YYYY-MM-DD.csv
"""

import tkinter as tk
import math
import subprocess
import threading
import wave
import struct
import tempfile
import os
import csv
from datetime import datetime, date

# ── Palette & Config ──────────────────────────────────────────────────────────
BG        = "#0e0e14"
SURFACE   = "#16161f"
RING_BG   = "#1e1e2e"
TOMATO    = "#ff4d5a"   # Work
MINT      = "#3dffc8"   # Short Break
AMBER     = "#ffc94d"   # Long Break
TEXT_HI   = "#f0f0ff"
TEXT_MID  = "#8888aa"
TEXT_LO   = "#3a3a55"
SCAN      = "#1a1a28"
DIM       = "#3a3a55"

MODES = {
    "WORK":        25 * 60,
    "SHORT BREAK": 5  * 60,
    "LONG BREAK":  15 * 60,
}

RING_R, RING_W = 130, 14
CX, CY, SIZE   = 200, 200, 400

# ── System sound paths (freedesktop standard, present on Linux Mint) ──────────
SOUND_DIR    = "/usr/share/sounds/freedesktop/stereo"
SND_COMPLETE = os.path.join(SOUND_DIR, "complete.oga")
SND_BELL     = os.path.join(SOUND_DIR, "bell.oga")
SND_INFO     = os.path.join(SOUND_DIR, "dialog-information.oga")

UBUNTU_DIR   = "/usr/share/sounds/ubuntu/stereo"
SND_U_NOTIFY = os.path.join(UBUNTU_DIR, "message.ogg")


# ── Audio helpers ─────────────────────────────────────────────────────────────

def _generate_tick_wav(path: str, freq=1200, duration=0.03, volume=0.25, rate=44100):
    n_samples = int(rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        for i in range(n_samples):
            t = i / rate
            env = math.exp(-t / (duration * 0.3))
            sample = int(32767 * volume * env * math.sin(2 * math.pi * freq * t))
            wf.writeframes(struct.pack("<h", sample))


def _generate_done_wav(path: str, rate=44100):
    tones = [(880, 0.12), (1100, 0.18)]
    frames = b""
    for freq, dur in tones:
        n = int(rate * dur)
        for i in range(n):
            t = i / rate
            env = math.sin(math.pi * i / n)
            sample = int(32767 * 0.5 * env * math.sin(2 * math.pi * freq * t))
            frames += struct.pack("<h", sample)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(frames)


class SoundEngine:
    def __init__(self):
        self._muted = False
        self._tick_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._done_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._tick_path = self._tick_file.name
        self._done_path = self._done_file.name
        self._tick_file.close()
        self._done_file.close()
        _generate_tick_wav(self._tick_path)
        _generate_done_wav(self._done_path)

    @property
    def muted(self):
        return self._muted

    def toggle_mute(self):
        self._muted = not self._muted
        return self._muted

    def _play(self, path):
        if self._muted:
            return
        threading.Thread(
            target=lambda: subprocess.run(["aplay", "-q", path], stderr=subprocess.DEVNULL),
            daemon=True,
        ).start()

    def _play_system(self, *candidates):
        if self._muted:
            return
        for path in candidates:
            if os.path.isfile(path):
                threading.Thread(
                    target=lambda p=path: subprocess.run(["paplay", p], stderr=subprocess.DEVNULL),
                    daemon=True,
                ).start()
                return
        self._play(self._done_path)

    def tick(self):
        self._play(self._tick_path)

    def session_complete(self):
        self._play_system(SND_COMPLETE, SND_BELL, SND_U_NOTIFY)

    def break_complete(self):
        self._play_system(SND_INFO, SND_BELL, SND_U_NOTIFY)

    def cleanup(self):
        for p in (self._tick_path, self._done_path):
            try:
                os.unlink(p)
            except OSError:
                pass


# ── Desktop notification helper ───────────────────────────────────────────────

def _notify(title: str, body: str, urgency: str = "normal", icon: str = "appointment"):
    threading.Thread(
        target=lambda: subprocess.run(
            ["notify-send", "-u", urgency, "-i", icon, "-t", "4000", title, body],
            stderr=subprocess.DEVNULL,
        ),
        daemon=True,
    ).start()


# ── Session log entry ─────────────────────────────────────────────────────────

class SessionEntry:
    def __init__(self, mode: str, start: datetime):
        self.mode      = mode
        self.start     = start
        self.end       = None          # filled on completion
        self.completed = False

    def finish(self):
        self.end       = datetime.now()
        self.completed = True

    @property
    def duration_minutes(self):
        if self.end and self.start:
            return round((self.end - self.start).total_seconds() / 60, 2)
        return 0.0


# ── Main App ──────────────────────────────────────────────────────────────────

class PomodoroApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("POMODORO")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── State ──
        self._current_mode        = "WORK"
        self._work_sessions_count = 0
        self._running             = False
        self._after_id            = None
        self._total               = MODES["WORK"]
        self._remaining           = self._total
        self._color               = TOMATO
        self._tick_enabled        = True

        # ── Session log ──
        self._session_log: list[SessionEntry] = []
        self._current_session: SessionEntry | None = None

        self._snd = SoundEngine()
        self._build_ui()
        self._refresh_display()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = tk.Frame(self, bg=BG, padx=28, pady=20)
        outer.pack()

        # Header
        hdr = tk.Frame(outer, bg=BG)
        hdr.pack(fill="x", pady=(0, 6))

        self._lbl_title = tk.Label(
            hdr, text="SYSTEM READY", bg=BG, fg=TOMATO,
            font=("Courier New", 13, "bold"),
        )
        self._lbl_title.pack(side="left")

        self._lbl_counter = tk.Label(
            hdr, text="CYCLE: 0/4", bg=BG, fg=DIM,
            font=("Courier New", 11),
        )
        self._lbl_counter.pack(side="right")

        # Canvas
        self._canvas = tk.Canvas(
            outer, width=SIZE, height=SIZE, bg=BG, highlightthickness=0,
        )
        self._canvas.pack()

        self._canvas.create_oval(
            CX-RING_R-RING_W, CY-RING_R-RING_W,
            CX+RING_R+RING_W, CY+RING_R+RING_W,
            outline=RING_BG, width=RING_W * 2,
        )
        self._arc = self._canvas.create_arc(
            CX-RING_R, CY-RING_R, CX+RING_R, CY+RING_R,
            start=90, extent=-360, outline=TOMATO, width=RING_W, style="arc",
        )
        self._cap_start = self._canvas.create_oval(0, 0, RING_W, RING_W, fill=TOMATO, outline="")
        self._cap_end   = self._canvas.create_oval(0, 0, RING_W, RING_W, fill=TOMATO, outline="")

        self._lbl_time = self._canvas.create_text(
            CX, CY - 16, text="25:00", fill=TEXT_HI,
            font=("Courier New", 46, "bold"),
        )
        self._lbl_status = self._canvas.create_text(
            CX, CY + 38, text="INITIALIZING", fill=TOMATO,
            font=("Courier New", 10, "bold"),
        )

        for y in range(0, SIZE, 4):
            self._canvas.create_line(0, y, SIZE, y, fill=SCAN)

        # Primary controls
        ctrl = tk.Frame(outer, bg=BG)
        ctrl.pack(pady=(14, 4))

        self._btn_start = tk.Button(
            ctrl, text="▶ START", bg=TOMATO, fg=BG,
            font=("Courier New", 10, "bold"), width=12, pady=8,
            command=self._toggle, relief="flat",
        )
        self._btn_start.pack(side="left", padx=5)

        tk.Button(
            ctrl, text="↺ RESET", bg=SURFACE, fg=TEXT_MID,
            font=("Courier New", 10, "bold"), width=12, pady=8,
            command=self._reset, relief="flat",
        ).pack(side="left", padx=5)

        # Secondary controls: tick + mute
        ctrl2 = tk.Frame(outer, bg=BG)
        ctrl2.pack(pady=(4, 0))

        self._btn_tick = tk.Button(
            ctrl2, text="🔔 TICK: ON", bg=SURFACE, fg=MINT,
            font=("Courier New", 9), width=13, pady=5,
            command=self._toggle_tick, relief="flat",
        )
        self._btn_tick.pack(side="left", padx=5)

        self._btn_mute = tk.Button(
            ctrl2, text="🔊 SOUND: ON", bg=SURFACE, fg=MINT,
            font=("Courier New", 9), width=13, pady=5,
            command=self._toggle_mute, relief="flat",
        )
        self._btn_mute.pack(side="left", padx=5)

        # Export button
        ctrl3 = tk.Frame(outer, bg=BG)
        ctrl3.pack(pady=(6, 0))

        self._btn_export = tk.Button(
            ctrl3, text="💾 EXPORT CSV", bg=SURFACE, fg=AMBER,
            font=("Courier New", 9), width=28, pady=5,
            command=self._export_csv, relief="flat",
        )
        self._btn_export.pack()

        # Status bar for export feedback
        self._lbl_export_status = tk.Label(
            outer, text="", bg=BG, fg=MINT,
            font=("Courier New", 8),
        )
        self._lbl_export_status.pack(pady=(3, 0))

    # ── Timer logic ───────────────────────────────────────────────────────────

    def _toggle(self):
        if self._running:
            self._running = False
            if self._after_id:
                self.after_cancel(self._after_id)
            # Pause: mark current session as interrupted (don't log it yet)
        else:
            self._running = True
            # Start a new session entry if we don't have one already
            if self._current_session is None:
                self._current_session = SessionEntry(self._current_mode, datetime.now())
            self._tick()
        self._refresh_display()

    def _tick(self):
        if self._remaining <= 0:
            self._running = False
            self._on_complete()
            return
        self._remaining -= 1

        # FIX: tick sound only during breaks, not during focus/work sessions
        if self._tick_enabled and self._current_mode != "WORK":
            self._snd.tick()

        self._refresh_display()
        self._after_id = self.after(1000, self._tick)

    def _on_complete(self):
        self.bell()

        # Finalise the current session entry
        if self._current_session is not None:
            self._current_session.finish()
            self._session_log.append(self._current_session)
            self._current_session = None

        if self._current_mode == "WORK":
            self._work_sessions_count += 1
            self._snd.session_complete()
            if self._work_sessions_count % 4 == 0:
                next_m = "LONG BREAK"
                _notify(
                    "🍅 Pomodoro — Long Break!",
                    f"Session {self._work_sessions_count} complete.\nTime for a 15-minute rest.",
                    urgency="normal", icon="media-playback-pause",
                )
            else:
                next_m = "SHORT BREAK"
                pos = self._work_sessions_count % 4
                _notify(
                    "🍅 Pomodoro — Short Break!",
                    f"Session {pos}/4 done. Take a 5-minute breather.",
                    urgency="normal", icon="media-playback-pause",
                )
        else:
            next_m = "WORK"
            self._snd.break_complete()
            _notify(
                "🍅 Pomodoro — Back to Work!",
                "Break over. Time to focus.",
                urgency="normal", icon="appointment",
            )

        self._flash(4, color=self._color, callback=lambda: self._set_mode(next_m))

    def _set_mode(self, mode_name):
        self._current_mode = mode_name
        self._total        = MODES[mode_name]
        self._remaining    = self._total
        self._current_session = None   # fresh entry will be created on next start

        if mode_name == "WORK":
            self._color = TOMATO
        elif mode_name == "SHORT BREAK":
            self._color = MINT
        else:
            self._color = AMBER

        self._refresh_display()

    def _reset(self):
        self._running = False
        if self._after_id:
            self.after_cancel(self._after_id)
        self._work_sessions_count = 0
        self._current_session = None
        self._set_mode("WORK")

    def _toggle_tick(self):
        self._tick_enabled = not self._tick_enabled
        label = "🔔 TICK: ON" if self._tick_enabled else "🔕 TICK: OFF"
        color = MINT if self._tick_enabled else DIM
        self._btn_tick.config(text=label, fg=color)

    def _toggle_mute(self):
        muted = self._snd.toggle_mute()
        label = "🔇 SOUND: OFF" if muted else "🔊 SOUND: ON"
        color = DIM if muted else MINT
        self._btn_mute.config(text=label, fg=color)

    # ── CSV Export ────────────────────────────────────────────────────────────

    def _export_csv(self):
        if not self._session_log:
            self._lbl_export_status.config(text="⚠  No completed sessions to export yet.", fg=AMBER)
            return

        filename = f"pomodoro_log_{date.today().isoformat()}.csv"
        path = os.path.join(os.path.expanduser("~"), filename)

        try:
            with open(path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["#", "Mode", "Date", "Start Time", "End Time", "Duration (min)"])
                for i, entry in enumerate(self._session_log, 1):
                    writer.writerow([
                        i,
                        entry.mode,
                        entry.start.strftime("%Y-%m-%d"),
                        entry.start.strftime("%H:%M:%S"),
                        entry.end.strftime("%H:%M:%S") if entry.end else "",
                        entry.duration_minutes,
                    ])

            count = len(self._session_log)
            work_mins = sum(
                e.duration_minutes for e in self._session_log if e.mode == "WORK"
            )
            self._lbl_export_status.config(
                text=f"✓ Saved {count} sessions ({work_mins:.0f} min work) → ~/{filename}",
                fg=MINT,
            )
        except OSError as e:
            self._lbl_export_status.config(text=f"✗ Export failed: {e}", fg=TOMATO)

    # ── Display ───────────────────────────────────────────────────────────────

    def _flash(self, n, on=True, color=None, callback=None):
        if n <= 0:
            if callback:
                callback()
            return
        self._canvas.itemconfig(self._arc, outline=color if on else BG)
        self.after(200, lambda: self._flash(n - 1, not on, color, callback))

    def _refresh_display(self):
        m, s  = divmod(self._remaining, 60)
        frac  = self._remaining / self._total if self._total else 0

        self._canvas.itemconfig(self._lbl_time, text=f"{m:02d}:{s:02d}")
        self._canvas.itemconfig(self._lbl_status, text=self._current_mode, fill=self._color)
        self._canvas.itemconfig(self._arc, extent=-360 * frac, outline=self._color)

        is_work = self._current_mode == "WORK"
        self._lbl_title.config(
            text="FOCUSING..." if (self._running and is_work) else "SYSTEM IDLE",
            fg=self._color,
        )

        cycle_pos = self._work_sessions_count % 4
        self._lbl_counter.config(text=f"CYCLE: {cycle_pos}/4", fg=self._color)

        self._btn_start.config(
            text="⏸ PAUSE" if self._running else "▶ START",
            bg=self._color if not self._running else DIM,
            fg=BG if not self._running else TEXT_HI,
        )

        self._place_cap(self._cap_start, 90)
        self._place_cap(self._cap_end, 90 + 360 * (1 - frac))

    def _place_cap(self, item, deg):
        rad = math.radians(deg)
        x   = CX + RING_R * math.cos(rad) - RING_W / 2
        y   = CY - RING_R * math.sin(rad) - RING_W / 2
        self._canvas.coords(item, x, y, x + RING_W, y + RING_W)
        self._canvas.itemconfig(item, fill=self._color)

    def _on_close(self):
        self._snd.cleanup()
        self.destroy()


if __name__ == "__main__":
    PomodoroApp().mainloop()