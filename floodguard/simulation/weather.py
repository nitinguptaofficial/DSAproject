"""Random storm generator.

Storms arrive one after another with dry spells in between (and sometimes
overlap). Each storm has its own:
  - start time and duration,
  - peak strength (with an occasional extreme storm),
  - size (radius of heavy rain),
  - straight-ish path across the city in a random direction, with a bend,
    and a random speed (slow storms linger over one area).

Everything comes from the `rng` passed in, so a given seed always produces
the same weather, and storms are generated lazily as time advances.
"""

import math

COMPASS = ["east", "south-east", "south", "south-west",
           "west", "north-west", "north", "north-east"]


class Storm:
    __slots__ = ("start", "duration", "peak", "radius",
                 "r0", "c0", "r1", "c1", "bend", "heading")

    def __init__(self, start, duration, peak, radius, r0, c0, r1, c1, bend):
        self.start = start
        self.duration = duration
        self.peak = peak
        self.radius = radius
        self.r0, self.c0, self.r1, self.c1 = r0, c0, r1, c1
        self.bend = bend
        # rows grow southwards, so angle 90deg (dr > 0) is "south"
        angle = math.degrees(math.atan2(r1 - r0, c1 - c0)) % 360
        self.heading = COMPASS[int((angle + 22.5) // 45) % 8]

    @property
    def end(self):
        return self.start + self.duration

    def progress(self, t):
        return (t - self.start) / self.duration

    def is_active(self, t):
        return 0.0 <= self.progress(t) < 1.0

    def intensity(self, t):
        """0 outside the storm; rises and falls smoothly to `peak`."""
        p = self.progress(t)
        if not 0.0 <= p < 1.0:
            return 0.0
        return self.peak * math.sin(math.pi * p) ** 1.5

    def center(self, t):
        p = min(1.0, max(0.0, self.progress(t)))
        row = self.r0 + (self.r1 - self.r0) * p
        col = self.c0 + (self.c1 - self.c0) * p
        # bend sideways (perpendicular to travel), most in the middle
        dr, dc = self.r1 - self.r0, self.c1 - self.c0
        length = math.hypot(dr, dc) or 1.0
        off = self.bend * math.sin(math.pi * p)
        return row + off * dc / length, col - off * dr / length

    def to_dict(self, t):
        row, col = self.center(t)
        return {
            "row": round(row, 2), "col": round(col, 2),
            "radius": round(self.radius, 2),
            "intensity": round(self.intensity(t), 3),
            "progress": round(self.progress(t), 3),
            "heading": self.heading,
        }


class Weather:
    def __init__(self, rows, cols, rng):
        self.rows = rows
        self.cols = cols
        self.rng = rng
        self.storms = []                          # generated, not yet over
        self._next_start = rng.uniform(0.5, 2.0)  # first storm comes soon

    def _new_storm(self, start):
        rng = self.rng
        size = max(self.rows, self.cols)
        extreme = rng.random() < 0.12
        duration = rng.uniform(10, 16) if extreme else rng.uniform(5, 13)
        peak = rng.uniform(1.15, 1.5) if extreme else rng.uniform(0.4, 1.0)
        radius = rng.uniform(0.15, 0.35) * size

        # travel direction and distance (short distance = slow, lingering storm)
        angle = rng.uniform(0, 2 * math.pi)
        travel = rng.uniform(0.4, 1.6) * size
        dr, dc = math.sin(angle), math.cos(angle)
        # aim the path at a random point near the middle of the city
        mid_r = self.rows * rng.uniform(0.25, 0.75)
        mid_c = self.cols * rng.uniform(0.25, 0.75)
        r0, c0 = mid_r - dr * travel / 2, mid_c - dc * travel / 2
        r1, c1 = mid_r + dr * travel / 2, mid_c + dc * travel / 2
        bend = rng.uniform(-0.2, 0.2) * size
        return Storm(start, duration, peak, radius, r0, c0, r1, c1, bend)

    def _generate_until(self, t):
        rng = self.rng
        while self._next_start <= t:
            storm = self._new_storm(self._next_start)
            self.storms.append(storm)
            if rng.random() < 0.2:
                # a second storm rolls in before this one is over
                self._next_start = storm.start + storm.duration * rng.uniform(0.4, 0.8)
            else:
                self._next_start = storm.end + rng.uniform(2.0, 10.0)

    def active(self, t):
        """Storms raining at time t (also forgets storms that are over)."""
        self._generate_until(t)
        self.storms = [s for s in self.storms if s.end > t]
        return [s for s in self.storms if s.is_active(t)]

    def next_start(self, t):
        """Start time of the next storm after t (generates it if needed)."""
        self._generate_until(t)
        upcoming = [s.start for s in self.storms if s.start > t]
        return min(upcoming) if upcoming else self._next_start
