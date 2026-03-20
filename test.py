"""
Pomodoro — Windows Sound & Notification Tester
Run this to verify all audio and desktop notifications work before
using the main app.
"""

import tkinter as tk
from tkinter import ttk
import threading
import wave
import struct
import math
import tempfile
import os
import winsound
import subprocess
from datetime import datetime

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = "#0e0e14"
SURFACE = "#16161f"
TOMATO  = "#ff4d5a"
MINT    = "#3dffc8"
AMBER   = "#ffc94d"
DIM     = "#3a3a55"
TEXT_HI = "#f0f0ff"
TEXT_MID= "#8888aa"
SCAN    = "#1a1a28"

# ── WAV generators (copied from main app) ────────────────────────────────────

def _generate_tick_wav(path, freq=1200, duration=0.03, volume=0.25, rate=44100):
    n = int(rate * duration)
    with wave.open(path, "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
        for i in range(n):
            t = i / rate
            env = math.exp(-t / (duration * 0.3))
            wf.writeframes(struct.pack("<h", int(32767 * volume * env * math.sin(2 * math.pi * freq * t))))


def _generate_done_wav(path, rate=44100):
    frames = b""
    for freq, dur in [(880, 0.12), (1100, 0.18)]:
        n = int(rate * dur)
        for i in range(n):
            t = i / rate
            env = math.sin(math.pi * i / n)
            frames += struct.pack("<h", int(32767 * 0.5 * env * math.sin(2 * math.pi * freq * t)))
    with wave.open(path, "w") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
        wf.writeframes(frames)


# ── Notification helper (copied from main app) ────────────────────────────────

_NOTIFY_PS = """\
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = [System.Drawing.SystemIcons]::{icon}
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = $icon
$n.BalloonTipTitle = '{title}'
$n.BalloonTipText  = '{body}'
$n.BalloonTipIcon  = [System.Windows.Forms.ToolTipIcon]::{tipicon}
$n.Visible = $true
$n.ShowBalloonTip(4000)
Start-Sleep -Milliseconds 4500
$n.Dispose()
"""

def _notify(title, body, urgency="normal", icon="appointment"):
    tip_icon_map = {"low": "None", "normal": "Info", "critical": "Warning"}
    sys_icon_map = {"appointment": "Information", "media-playback-pause": "Question"}
    tip_icon = tip_icon_map.get(urgency, "Info")
    sys_icon = sys_icon_map.get(icon, "Information")
    safe_title = title.replace("'", "`'")
    safe_body  = body.replace("'", "`'").replace("\n", " ")
    script = _NOTIFY_PS.format(icon=sys_icon, title=safe_title, body=safe_body, tipicon=tip_icon)
    threading.Thread(
        target=lambda: subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ),
        daemon=True,
    ).start()


# ── Test App ──────────────────────────────────────────────────────────────────

class TestApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Pomodoro — Sound & Notification Tester")
        self.resizable(False, False)
        self.configure(bg=BG)

        # Generate temp WAV files once
        self._tick_f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._done_f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        self._tick_path = self._tick_f.name
        self._done_path = self._done_f.name
        self._tick_f.close(); self._done_f.close()
        _generate_tick_wav(self._tick_path)
        _generate_done_wav(self._done_path)

        self._log_lines = []
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._log("🟢 Tester ready. Click any button to run a test.")

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = tk.Frame(self, bg=BG, padx=30, pady=24)
        root.pack()

        # Title
        tk.Label(root, text="SOUND & NOTIFICATION TESTER",
                 bg=BG, fg=TOMATO, font=("Courier New", 13, "bold")).pack(pady=(0, 18))

        # ── Sound section ──
        self._section(root, "CUSTOM WAV SOUNDS", TOMATO)

        row1 = tk.Frame(root, bg=BG); row1.pack(pady=4)
        self._btn(row1, "🔔  Tick Sound",       SURFACE, MINT,  self._test_tick).pack(side="left", padx=6)
        self._btn(row1, "✅  Session Done",      SURFACE, MINT,  self._test_done).pack(side="left", padx=6)

        # ── Windows system sounds ──
        self._section(root, "WINDOWS SYSTEM SOUNDS", AMBER)

        row2 = tk.Frame(root, bg=BG); row2.pack(pady=4)
        self._btn(row2, "🔔  SystemAsterisk",   SURFACE, AMBER, lambda: self._test_alias("SystemAsterisk")).pack(side="left", padx=6)
        self._btn(row2, "⚠️   SystemExclamation", SURFACE, AMBER, lambda: self._test_alias("SystemExclamation")).pack(side="left", padx=6)

        row3 = tk.Frame(root, bg=BG); row3.pack(pady=4)
        self._btn(row3, "🔔  SystemDefault",    SURFACE, AMBER, lambda: self._test_alias("SystemDefault")).pack(side="left", padx=6)
        self._btn(row3, "❌  SystemHand",        SURFACE, AMBER, lambda: self._test_alias("SystemHand")).pack(side="left", padx=6)

        # ── Notifications ──
        self._section(root, "DESKTOP NOTIFICATIONS", MINT)

        row4 = tk.Frame(root, bg=BG); row4.pack(pady=4)
        self._btn(row4, "🍅  Work Complete",     SURFACE, MINT, self._test_notify_work).pack(side="left", padx=6)
        self._btn(row4, "☕  Short Break",        SURFACE, MINT, self._test_notify_short).pack(side="left", padx=6)

        row5 = tk.Frame(root, bg=BG); row5.pack(pady=4)
        self._btn(row5, "🛋️   Long Break",         SURFACE, MINT, self._test_notify_long).pack(side="left", padx=6)
        self._btn(row5, "💼  Back to Work",       SURFACE, MINT, self._test_notify_back).pack(side="left", padx=6)

        # ── Run all ──
        tk.Frame(root, bg=DIM, height=1).pack(fill="x", pady=(16, 10))
        self._btn(root, "▶▶  RUN ALL TESTS", TOMATO, BG, self._run_all, width=36, bold=True).pack(pady=2)

        # ── Log box ──
        self._section(root, "TEST LOG", DIM)

        log_frame = tk.Frame(root, bg=SURFACE, bd=0)
        log_frame.pack(fill="x", pady=(4, 0))

        self._log_text = tk.Text(
            log_frame, width=52, height=10, bg=SURFACE, fg=TEXT_MID,
            font=("Courier New", 9), relief="flat", state="disabled",
            insertbackground=MINT, selectbackground=DIM,
        )
        sb = tk.Scrollbar(log_frame, command=self._log_text.yview, bg=SURFACE, troughcolor=BG)
        self._log_text.configure(yscrollcommand=sb.set)
        self._log_text.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        sb.pack(side="right", fill="y")

        # scanlines overlay
        for y in range(0, 600, 4):
            self._canvas_scan = None  # cosmetic only in canvas; skip here

    def _section(self, parent, label, color):
        f = tk.Frame(parent, bg=BG); f.pack(fill="x", pady=(12, 2))
        tk.Label(f, text=f"── {label} ", bg=BG, fg=color,
                 font=("Courier New", 8, "bold")).pack(side="left")
        tk.Frame(f, bg=color, height=1).pack(side="left", fill="x", expand=True, pady=6)

    def _btn(self, parent, text, bg, fg, cmd, width=22, bold=False):
        return tk.Button(
            parent, text=text, bg=bg, fg=fg,
            font=("Courier New", 9, "bold" if bold else "normal"),
            width=width, pady=7, relief="flat", cursor="hand2",
            activebackground=DIM, activeforeground=TEXT_HI,
            command=cmd,
        )

    # ── Test actions ──────────────────────────────────────────────────────────

    def _play_wav(self, path, label):
        self._log(f"▶  Playing WAV: {label}…")
        threading.Thread(
            target=lambda: (
                winsound.PlaySound(path, winsound.SND_FILENAME),
                self._log(f"✓  {label} — done")
            ),
            daemon=True,
        ).start()

    def _play_alias(self, alias):
        self._log(f"▶  Playing system alias: {alias}…")
        def _run():
            try:
                winsound.PlaySound(alias, winsound.SND_ALIAS)
                self._log(f"✓  {alias} — done")
            except RuntimeError as e:
                self._log(f"✗  {alias} failed: {e}", error=True)
        threading.Thread(target=_run, daemon=True).start()

    def _test_tick(self):      self._play_wav(self._tick_path, "Tick")
    def _test_done(self):      self._play_wav(self._done_path, "Session Done chime")
    def _test_alias(self, a):  self._play_alias(a)

    def _test_notify_work(self):
        self._log("▶  Sending 'Work Complete' notification…")
        _notify("🍅 Pomodoro — Short Break!", "Session 1/4 done. Take a 5-minute breather.",
                urgency="normal", icon="media-playback-pause")
        self._log("✓  Notification sent (check system tray)")

    def _test_notify_short(self):
        self._log("▶  Sending 'Short Break' notification…")
        _notify("🍅 Pomodoro — Short Break!", "Session 2/4 done. Take a 5-minute breather.",
                urgency="normal", icon="media-playback-pause")
        self._log("✓  Notification sent (check system tray)")

    def _test_notify_long(self):
        self._log("▶  Sending 'Long Break' notification…")
        _notify("🍅 Pomodoro — Long Break!", "Session 4 complete. Time for a 15-minute rest.",
                urgency="normal", icon="media-playback-pause")
        self._log("✓  Notification sent (check system tray)")

    def _test_notify_back(self):
        self._log("▶  Sending 'Back to Work' notification…")
        _notify("🍅 Pomodoro — Back to Work!", "Break over. Time to focus.",
                urgency="normal", icon="appointment")
        self._log("✓  Notification sent (check system tray)")

    def _run_all(self):
        self._log("━━  RUNNING ALL TESTS  ━━")
        delay = 0
        steps = [
            (500,  self._test_tick),
            (1000, self._test_done),
            (2500, lambda: self._test_alias("SystemAsterisk")),
            (4000, lambda: self._test_alias("SystemExclamation")),
            (5500, lambda: self._test_alias("SystemDefault")),
            (7000, lambda: self._test_alias("SystemHand")),
            (8500, self._test_notify_work),
            (10500,self._test_notify_short),
            (12500,self._test_notify_long),
            (14500,self._test_notify_back),
            (16500,lambda: self._log("━━  ALL TESTS COMPLETE  ━━")),
        ]
        for ms, fn in steps:
            self.after(ms, fn)

    # ── Log ───────────────────────────────────────────────────────────────────

    def _log(self, msg, error=False):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}]  {msg}\n"
        # Thread-safe update via `after`
        self.after(0, lambda: self._append_log(line, error))

    def _append_log(self, line, error=False):
        self._log_text.configure(state="normal")
        tag = "err" if error else ""
        self._log_text.insert("end", line, tag)
        self._log_text.tag_config("err", foreground=TOMATO)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    # ── Cleanup ───────────────────────────────────────────────────────────────

    def _on_close(self):
        for p in (self._tick_path, self._done_path):
            try: os.unlink(p)
            except OSError: pass
        self.destroy()


if __name__ == "__main__":
    TestApp().mainloop()