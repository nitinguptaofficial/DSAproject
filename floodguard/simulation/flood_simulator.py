"""Flood simulator.

Builds a synthetic city grid (intersections as vertices, roads as weighted
edges) over a randomly generated terrain (a winding river valley, low-lying
basins and a tilt), then simulates random storms moving across the city (see
weather.py). Every simulation has a seed: the same seed always reproduces the
same city and the same weather.

Each tick is split into short sub-steps. In every sub-step:
  1. rain falls, heaviest under each active storm cell;
  2. water flows across roads from higher to lower water surfaces, so it
     drains out of the hills and collects in the valley and the basin;
  3. sewers and soil drain water everywhere (faster where it is deeper), and
     water leaves the map at the city edge.

Water depth therefore builds up during a storm, collects in low ground and
recedes afterwards. A road's flood depth is
the average water depth at its two intersections; that depth sets its
severity and its travel weight in the graph. Flood status per road is stored
in a HashTable and a depth-ordered AVLTree for fast "most dangerous roads"
queries.
"""

import math
import random
from floodguard.structures import Graph, HashTable, AVLTree
from floodguard.simulation.weather import Weather

# Severity thresholds on water depth (metres)
SEVERITY = [
    (0.05, "safe"),
    (0.25, "caution"),
    (0.50, "warning"),
    (float("inf"), "danger"),
]

STEPS_PER_HOUR = 4    # physics sub-steps per simulated hour
TERRAIN_M = 6.0       # elevation 0..1 maps to 0..6 m of terrain height
TERRAIN_NOISE = 0.003 # random bumpiness of the terrain (fraction of 0..1)
PEAK_RAIN_M = 0.14    # rain per hour at the storm centre at peak intensity
BACKGROUND_RAIN = 0.2 # fraction of storm rain falling far from its centre
SEWER_M = 0.03        # water each intersection's sewer removes per hour
SOAK_RATE = 0.06      # fraction of standing water drained per hour (deeper
                      # water pushes harder into sewers and soil)
OUTLET_M = 0.2        # extra removal per hour at the city edge (outflow)
FLOW_RATE = 0.2       # fraction of a surface difference that flows per step
FLOOD_PENALTY = 6.0   # weight = base * (1 + FLOOD_PENALTY * depth)


def severity_of(depth):
    for limit, label in SEVERITY:
        if depth < limit:
            return label
    return SEVERITY[-1][1]


def edge_key(u, v):
    return tuple(sorted((u, v)))


def new_seed():
    """A fresh random seed (shown in the UI as the city number)."""
    return random.SystemRandom().randrange(1, 1_000_000)


class FloodSimulator:
    def __init__(self, rows=50, cols=50, seed=None):
        """seed=None picks a random city and weather; pass a seed to replay."""
        self.rows = rows
        self.cols = cols
        self.seed = new_seed() if seed is None else int(seed)
        self.rng = random.Random(self.seed)                  # terrain
        self.weather = Weather(rows, cols, random.Random("weather-%d" % self.seed))
        self.storms = []      # storms raining right now
        self.graph = Graph(directed=False)
        self.flood_table = HashTable()
        self.severity_tree = AVLTree()
        self.time = 0
        self.intensity = 0.0
        self._base = {}       # edge_key -> base road length
        self._water = {}      # vertex -> standing water depth (m)
        self._height = {}     # vertex -> terrain height (m)
        self._outlet = set()  # vertices on the city edge
        self._nbrs = None     # vertex -> neighbour list (cached on first step)
        self._rc = None       # vertex -> (row, col)
        self.history = []     # one stats record per tick, for the timeline
        self._build_city()
        self._record()

    # ------------------------------------------------------------------ #
    # City construction
    # ------------------------------------------------------------------ #
    def _random_terrain(self):
        """Pick the random shape of this city's land."""
        rng = self.rng
        size = max(self.rows, self.cols)
        self._terrain = {
            # river runs north-south or east-west, winding as it goes
            "river_vertical": rng.random() < 0.5,
            "river_pos": rng.uniform(0.2, 0.8),
            "river_amp": rng.uniform(0.04, 0.16),
            "river_freq": rng.uniform(0.5, 1.6),
            "river_phase": rng.uniform(0, 2 * math.pi),
            "river_width": rng.uniform(0.05, 0.1),
            "river_depth": rng.uniform(0.25, 0.4),
            # one or two low-lying basins where water pools
            "basins": [
                (self.rows * rng.uniform(0.15, 0.85), self.cols * rng.uniform(0.15, 0.85),
                 size * rng.uniform(0.07, 0.15), rng.uniform(0.15, 0.3))
                for _ in range(rng.choice((1, 1, 2)))
            ],
            # the whole city tilts gently in a random direction
            "tilt_angle": rng.uniform(0, 2 * math.pi),
            "tilt": rng.uniform(0.04, 0.12),
        }

    def _elevation(self, r, c):
        """Terrain in [0, 1]: river valley + basins + tilt + noise."""
        t = self._terrain
        rows, cols = self.rows, self.cols
        # `along` runs down the river, `across` measures distance from it
        if t["river_vertical"]:
            along, across, span, length = r, c, cols, rows
        else:
            along, across, span, length = c, r, rows, cols
        centre = span * (t["river_pos"] + t["river_amp"] * math.sin(
            2 * math.pi * t["river_freq"] * along / length + t["river_phase"]))
        valley = math.exp(-((across - centre) ** 2) / (2 * (t["river_width"] * span) ** 2))
        basins = sum(
            depth * math.exp(-((r - br) ** 2 + (c - bc) ** 2) / (2 * width ** 2))
            for br, bc, width, depth in t["basins"])
        tilt = t["tilt"] * ((r / rows - 0.5) * math.sin(t["tilt_angle"])
                            + (c / cols - 0.5) * math.cos(t["tilt_angle"]))
        e = (0.6 - t["river_depth"] * valley - basins + tilt
             + self.rng.uniform(-TERRAIN_NOISE, TERRAIN_NOISE))
        return max(0.0, min(1.0, e))

    def _build_city(self):
        self._random_terrain()
        for r in range(self.rows):
            for c in range(self.cols):
                v = "n%d_%d" % (r, c)
                elev = self._elevation(r, c)
                self.graph.add_vertex(v, row=r, col=c, elevation=elev)
                self._height[v] = elev * TERRAIN_M
                self._water[v] = 0.0
                if r in (0, self.rows - 1) or c in (0, self.cols - 1):
                    self._outlet.add(v)

        def connect(a, b, base_len):
            u = "n%d_%d" % a
            v = "n%d_%d" % b
            self.graph.add_edge(u, v, base_len)
            self._base[edge_key(u, v)] = base_len

        for r in range(self.rows):
            for c in range(self.cols):
                if c + 1 < self.cols:
                    connect((r, c), (r, c + 1), 1.0)
                if r + 1 < self.rows:
                    connect((r, c), (r + 1, c), 1.05)

        self._update_roads()

    # ------------------------------------------------------------------ #
    # Water model
    # ------------------------------------------------------------------ #
    def _step(self, dt, t):
        storms = self.weather.active(t)
        water, height = self._water, self._height
        if self._nbrs is None:  # neighbour lists never change; cache them
            self._nbrs = {v: self.graph.neighbors(v) for v in water}
            self._rc = {v: (self.graph.vertex_meta(v)["row"],
                            self.graph.vertex_meta(v)["col"]) for v in water}

        # 1. rain, heaviest under each storm cell
        exp = math.exp
        for storm in storms:
            base = PEAK_RAIN_M * storm.intensity(t) * dt
            if base <= 0.0:
                continue
            sr, sc = storm.center(t)
            inv = -1.0 / (2 * storm.radius ** 2)
            for v, (r, c) in self._rc.items():
                d2 = (r - sr) ** 2 + (c - sc) ** 2
                water[v] += base * (BACKGROUND_RAIN + (1 - BACKGROUND_RAIN) * exp(d2 * inv))

        # 2. flow from higher to lower water surface (explicit, mass-conserving)
        delta = dict.fromkeys(water, 0.0)
        surface = {v: height[v] + water[v] for v in water}
        for u, nbrs in self._nbrs.items():
            if water[u] <= 0.0:
                continue
            su = surface[u]
            wants = []
            for v in nbrs:
                diff = su - surface[v]
                if diff > 0:
                    wants.append((v, FLOW_RATE * diff / 2.0))
            total = sum(q for _, q in wants)
            if total <= 0.0:
                continue
            # never move more water than the intersection holds
            scale = min(1.0, water[u] / total)
            for v, q in wants:
                delta[u] -= q * scale
                delta[v] += q * scale

        # 3. sewers and soil everywhere, plus outflow at the city edge
        for v in water:
            drain = SEWER_M + (OUTLET_M if v in self._outlet else 0.0)
            depth = water[v] + delta[v]
            water[v] = max(0.0, depth * (1.0 - SOAK_RATE * dt) - drain * dt)

        self.storms = storms
        self.intensity = max((s.intensity(t) for s in storms), default=0.0)

    def _update_roads(self):
        """Recompute road depth, severity and graph weight from node water."""
        flooded = []
        water = self._water
        for key, base in self._base.items():
            u, v = key
            depth = (water[u] + water[v]) / 2.0
            factor = 1.0 + FLOOD_PENALTY * depth
            # always scale from the base length so penalties never compound
            new_weight = base * factor
            self.graph.update_edge_weight(u, v, new_weight)

            # the road set never changes, so overwrite records in place
            # (no rehashing) rather than rebuilding the table every tick
            self.flood_table[key] = {
                "u": u, "v": v, "depth": round(depth, 3),
                "severity": severity_of(depth), "weight": round(new_weight, 3),
                "base": base, "factor": round(factor, 3),
            }
            # index severity only for nonzero flood; (depth, u, v) keeps keys
            # unique so roads with equal depth don't overwrite each other
            if depth >= 0.01:
                flooded.append(((round(depth, 4), u, v), None))
        flooded.sort()
        self.severity_tree = AVLTree.from_sorted(flooded)

    # ------------------------------------------------------------------ #
    # Simulation control
    # ------------------------------------------------------------------ #
    def tick(self, hours=1.0):
        """Advance the simulation by `hours` of simulated time."""
        steps = max(1, int(round(hours * STEPS_PER_HOUR)))
        dt = hours / steps
        for _ in range(steps):
            self.time += dt
            self._step(dt, self.time)
        self.time = round(self.time, 6)
        self._update_roads()
        self._record()
        return self.snapshot()

    def _record(self, keep=240):
        stats = self.area_stats()
        self.history.append({
            "time": stats["time"],
            "intensity": stats["intensity"],
            "water_m3": round(sum(self._water.values()), 2),
            **stats["severity_counts"],
        })
        del self.history[:-keep]

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def base_length(self, u, v):
        return self._base.get(edge_key(u, v), 1.0)

    def water_depth(self, v):
        return self._water.get(v, 0.0)

    def flooded_roads(self, min_severity="caution"):
        order = {"caution": 1, "warning": 2, "danger": 3}
        min_rank = order.get(min_severity, 1)
        return [rec for rec in self.flood_table.values()
                if order.get(rec["severity"], 0) >= min_rank]

    def dangerous_roads(self, limit=10):
        """Top most-flooded roads via AVL top-k query."""
        return [
            {"u": u, "v": v, "depth": depth, "severity": severity_of(depth)}
            for (depth, u, v), _ in self.severity_tree.top_k(limit)
        ]

    def area_stats(self):
        severities = {"safe": 0, "caution": 0, "warning": 0, "danger": 0}
        for rec in self.flood_table.values():
            severities[rec["severity"]] += 1
        total = len(self.flood_table)
        return {
            "total_roads": total,
            "flooded_roads": total - severities["safe"],
            "severity_counts": severities,
            "intensity": round(self.intensity, 3),
            "time": self.time,
            "seed": self.seed,
        }

    def snapshot(self):
        """Return a concise snapshot of the current simulation state."""
        snap = self.area_stats()
        snap["dangerous_roads"] = self.dangerous_roads(limit=5)
        return snap

    def network(self):
        nodes = []
        for v in self.graph.vertices():
            meta = self.graph.vertex_meta(v)
            nodes.append({"id": v, "row": meta["row"], "col": meta["col"],
                          "elevation": round(meta["elevation"], 3),
                          "water": round(self._water[v], 3)})
        edges = []
        for u, v, w in self.graph.edge_list():
            rec = self.flood_table.get(edge_key(u, v), {})
            edges.append({"u": u, "v": v, "weight": round(w, 2),
                          "base": rec.get("base"), "depth": rec.get("depth", 0.0),
                          "severity": rec.get("severity", "safe")})
        return {"nodes": nodes, "edges": edges, "time": self.time,
                "seed": self.seed,
                "intensity": round(self.intensity, 3),
                "storms": [s.to_dict(self.time) for s in self.storms],
                "next_storm_in": round(self.weather.next_start(self.time) - self.time, 1),
                "dims": {"rows": self.rows, "cols": self.cols}}
