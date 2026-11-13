"""Built-in HTTP server + JSON API (Python standard library only).

Serves the static dashboard and exposes REST endpoints backed by the DSA
core (graph, Dijkstra, A*, BFS/DFS, hash table, AVL tree).
"""

import json
import math
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from floodguard.simulation import FloodSimulator
from floodguard.simulation.flood_simulator import edge_key
from floodguard.algorithms import astar, shortest_path, connected_components

STATIC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))

MIME = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}

sim = FloodSimulator()
# One simulation is shared by all request threads: serialise access so a tick
# (which mutates water, weights and indexes) never interleaves with a read.
LOCK = threading.Lock()


def build_route(from_v, to_v, strategy="safest", algo="dijkstra"):
    """Compute route. strategy: 'safest' (flood-weighted) or 'shortest' (base)."""
    if not sim.graph.has_vertex(from_v):
        return {"error": "unknown start %r" % from_v}
    if not sim.graph.has_vertex(to_v):
        return {"error": "unknown destination %r" % to_v}

    weight_fn = None
    label = "flood-adjusted safety cost"
    if strategy == "shortest":
        weight_fn = lambda u, v: sim.base_length(u, v)
        label = "base distance"

    if algo == "astar":
        goal = sim.graph.vertex_meta(to_v)

        # Straight-line grid distance to the goal. Admissible because every
        # road costs at least 1.0 (flooding only raises weights).
        def heuristic(v):
            meta = sim.graph.vertex_meta(v)
            return math.hypot(goal["row"] - meta["row"], goal["col"] - meta["col"])

        path, cost = astar(sim.graph, from_v, to_v, heuristic=heuristic, weight_fn=weight_fn)
    else:
        path, cost = shortest_path(sim.graph, from_v, to_v, weight_fn=weight_fn)

    if path is None:
        return {"error": "no route found (are start/destination in the same component?)"}

    # annotate each hop with its flood state
    hops = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        w = weight_fn(u, v) if weight_fn else sim.graph.get_weight(u, v)
        rec = sim.flood_table.get(edge_key(u, v), {})
        hops.append({
            "from": u, "to": v,
            "weight": round(w, 3),
            "depth": rec.get("depth", 0.0),
            "severity": rec.get("severity", "safe"),
        })

    return {"path": path, "cost": round(cost, 3), "label": label, "hops": hops,
            "algo": algo, "strategy": strategy}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return  # quiet

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path):
        rel = os.path.normpath(path)
        if rel.startswith("..") or os.path.isabs(rel):
            self._send_json({"error": "forbidden"}, 403)
            return
        full = os.path.join(STATIC_DIR, rel)
        if not os.path.isfile(full):
            self._send_json({"error": "not found"}, 404)
            return
        ext = os.path.splitext(full)[1].lower()
        ctype = MIME.get(ext, "application/octet-stream")
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        with LOCK:
            self._get()

    def do_POST(self):
        with LOCK:
            self._post()

    def _get(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send_file("index.html")
            return
        if path.startswith("/static/"):
            self._send_file(path[len("/static/"):])
            return
        if path == "/api/network":
            self._send_json(sim.network())
            return
        if path == "/api/history":
            self._send_json({"history": sim.history})
            return
        if path == "/api/stats":
            self._send_json(sim.area_stats())
            return
        if path == "/api/dangerous":
            try:
                limit = int(qs.get("limit", ["10"])[0])
            except ValueError:
                self._send_json({"error": "limit must be an integer"}, 400)
                return
            self._send_json({"roads": sim.dangerous_roads(limit)})
            return
        if path == "/api/flooded":
            minsev = qs.get("severity", ["caution"])[0]
            self._send_json({"roads": sim.flooded_roads(minsev)})
            return
        if path == "/api/components":
            self._send_json({"components": connected_components(sim.graph)})
            return
        if path == "/api/route":
            from_v = qs.get("from", [None])[0]
            to_v = qs.get("to", [None])[0]
            strategy = qs.get("strategy", ["safest"])[0]
            algo = qs.get("algo", ["dijkstra"])[0]
            if not from_v or not to_v:
                self._send_json({"error": "from/to required"}, 400)
                return
            result = build_route(from_v, to_v, strategy, algo)
            self._send_json(result, 400 if "error" in result else 200)
            return
        self._send_json({"error": "unknown endpoint"}, 404)

    def _post(self):
        global sim
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        if parsed.path == "/api/reset":
            # no seed -> a brand-new random city and weather; seed -> replay it
            seed = qs.get("seed", [None])[0]
            if seed is not None and not seed.isdigit():
                self._send_json({"error": "seed must be a whole number"}, 400)
                return
            sim = FloodSimulator(seed=seed)
            self._send_json(sim.snapshot())
            return
        if parsed.path == "/api/tick":
            try:
                hours = float(qs.get("hours", ["1"])[0])
            except ValueError:
                self._send_json({"error": "hours must be a number"}, 400)
                return
            if not 0 < hours <= 24:
                self._send_json({"error": "hours must be between 0 and 24"}, 400)
                return
            self._send_json(sim.tick(hours))
            return
        self._send_json({"error": "unknown endpoint"}, 404)


def create_server(host="127.0.0.1", port=8000):
    return ThreadingHTTPServer((host, port), Handler)
