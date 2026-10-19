"""Persistent Pomodoro timing, independent of the desktop UI."""
import calendar
import json
import math
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

DEFAULTS = dict(focus=90, short=15, long=30, every=3, goal=0, volume=70,
                auto_break=False, auto_focus=False, sound=True, notify=True)
# goal: daily focus target in minutes (0 = off); volume: chime loudness in percent.
RANGES = dict(focus=(1, 240), short=(1, 240), long=(1, 240), every=(1, 12), goal=(0, 720), volume=(0, 100))

def valid_number(value, default, low, high):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high else default

def period(days, view, offset, today):
    """[(date, seconds, sessions)] for the calendar week (Mon-Sun) or month `offset` steps from today's."""
    if view == "week":
        start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
        count = 7
    else:
        year, month = divmod(today.year*12 + today.month-1 + offset, 12)
        start = date(year, month+1, 1)
        count = calendar.monthrange(year, month+1)[1]
    rows = []
    for i in range(count):
        day = start + timedelta(days=i)
        entry = days.get(day.isoformat(), {})
        rows.append((day, entry.get("seconds", 0), entry.get("sessions", 0)))
    return rows

def streak(days, today, minimum=60):
    """Consecutive days with at least `minimum` focus seconds; an unstarted today does not break it."""
    day = today if days.get(today.isoformat(), {}).get("seconds", 0) >= minimum else today - timedelta(days=1)
    count = 0
    while days.get(day.isoformat(), {}).get("seconds", 0) >= minimum:
        count += 1
        day -= timedelta(days=1)
    return count

class FocusTimer:
    def __init__(self, path):
        self.path = Path(path)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if not isinstance(raw, dict): raw = {}
        cfg = raw.get("settings", {})
        if not isinstance(cfg, dict): cfg = {}
        self.settings = {k: (cfg.get(k) if isinstance(cfg.get(k), bool) else v) if isinstance(v, bool)
                         else int(valid_number(cfg.get(k), v, *RANGES[k])) for k,v in DEFAULTS.items()}
        self.mode = raw.get("mode") if raw.get("mode") in ("focus", "short", "long") else "focus"
        self.remaining = valid_number(raw.get("remaining"), self.duration, 0, 14400)
        self.cycle = int(valid_number(raw.get("cycle"), 0, 0, 100000))
        self.days = {}
        for date, entry in (raw.get("days", {}) if isinstance(raw.get("days"), dict) else {}).items():
            try: datetime.strptime(date, "%Y-%m-%d")
            except (ValueError, TypeError): continue
            if isinstance(entry, dict):
                self.days[date] = dict(seconds=valid_number(entry.get("seconds"),0,0,86400),
                                       sessions=int(valid_number(entry.get("sessions"),0,0,1440)))
        self.position = raw.get("position")
        self.running = False  # Never count time while the app was not running.
        self.last = time.monotonic()
        self.notice = "Ready when you are"

    @property
    def duration(self): return self.settings[self.mode] * 60

    def start_pause(self):
        self.running = not self.running
        self.last = time.monotonic()
        self.notice = "Stay with one task" if self.running else "Paused"

    def reset(self):
        self.running = False
        self.remaining = self.duration
        self.notice = "Timer reset · today's work kept"

    def switch(self, mode):
        self.running = False
        self.mode = mode
        self.remaining = self.duration
        self.notice = "Ready when you are"

    def extend(self, seconds=300):
        self.remaining = min(14400, self.remaining+seconds)
        self.notice = f"+{seconds//60} min added"

    def skip(self):
        """Jump to the next phase. A skipped focus advances the round but is not a completed session."""
        self.running = False
        if self.mode == "focus":
            self.cycle += 1
            self.mode = "long" if self.cycle % self.settings["every"] == 0 else "short"
        else:
            self.mode = "focus"
        self.remaining = self.duration
        self.notice = "Skipped · ready when you are"

    def add_work(self, seconds, end):
        start = end - seconds
        while start < end:
            dt = datetime.fromtimestamp(start)
            boundary = datetime.combine(dt.date() + timedelta(days=1), datetime.min.time()).timestamp()
            stop = min(end, boundary)
            entry = self.days.setdefault(dt.date().isoformat(), dict(seconds=0, sessions=0))
            entry["seconds"] += stop-start
            start = stop

    def tick(self, now=None, wall=None):
        now = time.monotonic() if now is None else now
        wall = time.time() if wall is None else wall
        elapsed = now-self.last
        self.last = now
        if not self.running: return False
        if elapsed < 0 or elapsed > 5:
            self.running = False
            self.notice = "Paused after sleep or interruption"
            return False
        used = min(elapsed, self.remaining)
        if self.mode == "focus": self.add_work(used, wall)
        self.remaining = max(0, self.remaining-used)
        if self.remaining > 0: return False
        if self.mode == "focus":
            self.cycle += 1
            self.days.setdefault(datetime.fromtimestamp(wall).date().isoformat(), dict(seconds=0,sessions=0))["sessions"] += 1
            self.mode = "long" if self.cycle % self.settings["every"] == 0 else "short"
            self.running = self.settings["auto_break"]
            self.notice = "Focus complete · time for a break"
        else:
            self.mode = "focus"
            self.running = self.settings["auto_focus"]
            self.notice = "Break complete · ready to focus"
        self.remaining = self.duration
        return True

    def save(self):
        self.path.parent.mkdir(exist_ok=True, parents=True)
        temp = self.path.with_suffix(".tmp")
        payload = dict(settings=self.settings, mode=self.mode, remaining=self.remaining,
                       cycle=self.cycle, days=self.days, position=self.position)
        with temp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, self.path)
