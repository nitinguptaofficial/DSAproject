"""Unit tests for FloodGuard's DSA core. Run: python tests/test_core.py"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from floodguard.structures import Graph, MinHeap, HashTable, AVLTree
from floodguard.algorithms import dijkstra, shortest_path, astar, bfs, dfs, connected_components
from floodguard.simulation import FloodSimulator


def test_min_heap():
    h = MinHeap()
    h.push(5, "a")
    h.push(1, "b")
    h.push(3, "c")
    assert h.peek() == (1, "b")
    h.decrease_key("a", 0)
    assert h.peek() == (0, "a")
    assert h.pop() == (0, "a")
    assert h.pop() == (1, "b")
    assert h.pop() == (3, "c")
    assert h.is_empty()
    print("min_heap ok")


def test_hash_table():
    t = HashTable(capacity=4)
    for i in range(100):
        t["k%d" % i] = i
    assert len(t) == 100
    assert t["k42"] == 42
    assert "k99" in t
    assert t.get("missing", -1) == -1
    del t["k42"]
    assert "k42" not in t
    assert len(t) == 99
    print("hash_table ok")


def test_avl_tree():
    tree = AVLTree()
    import random
    rng = random.Random(0)
    vals = list(range(200))
    rng.shuffle(vals)
    for v in vals:
        tree.insert(v, v * 10)
    assert len(tree) == 200
    # height must be near-logarithmic for a balanced tree
    assert tree.height() <= 3 * max(1, (len(tree)).bit_length())
    assert tree.search(50) == 500
    rng = tree.range_query(10, 20)
    assert [k for k, _ in rng] == list(range(10, 21))
    top = tree.top_k(3)
    assert [k for k, _ in top] == [199, 198, 197]
    tree.delete(50)
    assert tree.search(50) is None
    assert len(tree) == 199
    print("avl_tree ok")


def test_graph_dynamic_updates():
    g = Graph(directed=False)
    for i in range(4):
        g.add_vertex(i)
    g.add_edge(0, 1, 1)
    g.add_edge(1, 2, 1)
    g.add_edge(2, 3, 1)
    g.add_edge(0, 2, 10)
    assert g.get_weight(0, 2) == 10
    g.update_edge_weight(0, 2, 1)
    assert g.get_weight(0, 2) == 1
    assert g.get_weight(2, 0) == 1  # symmetric
    path, cost = shortest_path(g, 0, 3)
    assert path == [0, 2, 3]  # dynamic update re-routes
    assert cost == 2
    print("graph dynamics ok")


def test_dijkstra_vs_astar():
    g = Graph(directed=False)
    # line 0-1-2-3 plus a costly shortcut
    for i in range(5):
        g.add_vertex(i)
    for a, b, w in [(0, 1, 1), (1, 2, 1), (2, 3, 1), (3, 4, 1), (0, 4, 50)]:
        g.add_edge(a, b, w)
    path_d, cost_d = shortest_path(g, 0, 4)
    assert cost_d == 4
    assert path_d == [0, 1, 2, 3, 4]
    path_a, cost_a = astar(g, 0, 4, heuristic=lambda v: abs(4 - v) * 0.9)
    assert cost_a == 4
    assert path_a == [0, 1, 2, 3, 4]
    print("dijkstra/astar ok")


def test_bfs_dfs_components():
    g = Graph(directed=False)
    for i in range(6):
        g.add_vertex(i)
    for a, b in [(0, 1), (1, 2), (2, 0), (3, 4)]:
        g.add_edge(a, b, 1)
    order, _ = bfs(g, 0)
    assert set(order) == {0, 1, 2}
    order_d, _ = dfs(g, 0)
    assert set(order_d) == {0, 1, 2}
    comps = connected_components(g)
    sizes = sorted(len(c) for c in comps)
    assert sizes == [1, 2, 3]  # {0,1,2}, {3,4}, {5}
    # only flooded nodes => only component {3,4}
    comps2 = connected_components(g, predicate=lambda v: v in (3, 4))
    assert comps2 == [[3, 4]]
    print("bfs/dfs/components ok")


def test_simulator():
    sim = FloodSimulator(rows=6, cols=8, seed=3)
    net = sim.network()
    assert len(net["nodes"]) == 48
    assert len(net["edges"]) == 48 * 2 - 6 - 8  # horizontal + vertical roads
    assert len(sim.dangerous_roads()) >= 0
    # the first storm always arrives within 2 hours, so it rains within 12
    peak = max(sim.tick(1.0)["intensity"] for _ in range(12))
    assert peak > 0.2
    assert sim.time == 12.0
    # route between corners
    r = shortest_path(sim.graph, "n0_0", "n5_7", weight_fn=sim.base_length)
    assert r[0] is not None
    r2 = shortest_path(sim.graph, "n0_0", "n5_7")
    assert r2[0] is not None
    print("simulator ok")


def test_avl_from_sorted():
    items = [(k, k * 2) for k in range(1000)]
    tree = AVLTree.from_sorted(items)
    assert len(tree) == 1000
    assert tree.height() == (1000).bit_length()  # perfectly balanced
    assert tree.search(321) == 642
    assert tree.inorder() == items
    assert [k for k, _ in tree.top_k(2)] == [999, 998]
    tree.insert(1000, 0)  # still a valid AVL tree afterwards
    tree.delete(0)
    assert [k for k, _ in tree.range_query(998, 2000)] == [998, 999, 1000]
    assert AVLTree.from_sorted([]).root is None
    print("avl from_sorted ok")


def test_avl_contains_none_value():
    tree = AVLTree()
    tree.insert(5)  # value defaults to None
    assert 5 in tree
    assert 6 not in tree
    print("avl contains ok")


def test_flood_weights_follow_depth():
    sim = FloodSimulator(rows=12, cols=12, seed=3)
    for _ in range(3):  # weights must come from base length, never compound
        sim.tick(4.0)
        for rec in sim.flood_table.values():
            u, v = rec["u"], rec["v"]
            base = sim.base_length(u, v)
            assert rec["base"] == base
            expected = base * (1 + 6.0 * (sim.water_depth(u) + sim.water_depth(v)) / 2)
            assert abs(sim.graph.get_weight(u, v) - expected) < 1e-9
    print("flood weights ok")


def total_water(sim):
    return sum(sim.water_depth(v) for v in sim.graph.vertices())


def test_water_collects_in_low_ground():
    # Once the rain stops, water runs off the hills into low ground. (While a
    # big storm is still raining on a flat plateau, everywhere can be wet.)
    # Seed 17 is a hard case: an extreme storm overlapping a second one.
    for seed in (3, 17, 99):
        sim = FloodSimulator(rows=30, cols=30, seed=seed)
        by_height = sorted(sim.graph.vertices(),
                           key=lambda v: sim.graph.vertex_meta(v)["elevation"])
        q = len(by_height) // 4
        rained = False
        for _ in range(72):
            sim.tick(1.0)
            if sim.storms:
                rained = True
            elif rained:
                break  # first hour of the dry spell after rain
        assert rained and not sim.storms, seed
        sim.tick(1.0)
        low = sum(sim.water_depth(v) for v in by_height[:q]) / q
        high = sum(sim.water_depth(v) for v in by_height[-q:]) / q
        assert low > 2 * high, (seed, low, high)
    print("water collects low ok")


def test_water_recedes_after_storm():
    for seed in (3, 17, 99):
        sim = FloodSimulator(rows=20, cols=20, seed=seed)
        checked = False
        for _ in range(72):
            sim.tick(1.0)
            if sim.storms or total_water(sim) <= 0:
                continue
            # dry spell after a storm: water must drain while no rain falls
            wet = total_water(sim)
            sim.tick(1.0)
            if not sim.storms:
                assert total_water(sim) < wet, seed
                checked = True
                break
        assert checked, "no dry spell after a storm for seed %d" % seed
    print("water recedes ok")


def test_weather_random_but_reproducible():
    a, b = FloodSimulator(rows=15, cols=15, seed=42), FloodSimulator(rows=15, cols=15, seed=42)
    c = FloodSimulator(rows=15, cols=15, seed=43)
    for sim in (a, b, c):
        for _ in range(8):
            sim.tick(1.0)
    assert a.network() == b.network()          # same seed: identical run
    elev = lambda s: [n["elevation"] for n in s.network()["nodes"]]
    assert elev(a) != elev(c)                  # different seed: different city
    assert [h["intensity"] for h in a.history] != [h["intensity"] for h in c.history]
    seeds = {FloodSimulator(rows=4, cols=4).seed for _ in range(5)}
    assert len(seeds) > 1                      # no seed: a new random city
    print("random weather ok")


def test_storm_shape():
    from floodguard.simulation.weather import Storm
    east = Storm(start=10, duration=8, peak=0.8, radius=5, r0=5, c0=0, r1=5, c1=20, bend=0)
    assert east.heading == "east"
    assert east.intensity(9.9) == 0 and east.intensity(18) == 0
    assert abs(east.intensity(14) - 0.8) < 1e-9          # strongest half-way
    assert east.intensity(12) < east.intensity(14)
    assert east.center(14) == (5, 10)
    south = Storm(start=0, duration=4, peak=1, radius=5, r0=0, c0=5, r1=20, c1=5, bend=0)
    assert south.heading == "south"
    print("storm shape ok")


def test_dangerous_roads_keeps_equal_depths():
    sim = FloodSimulator(rows=10, cols=10, seed=3)
    for _ in range(8):
        sim.tick(1.0)
    flooded = [r for r in sim.flood_table.values() if r["depth"] >= 0.01]
    roads = sim.dangerous_roads(limit=len(flooded))
    assert len(roads) == len(flooded)
    depths = [r["depth"] for r in roads]
    assert depths == sorted(depths, reverse=True)
    print("dangerous roads ok")


def test_route_astar_matches_dijkstra():
    from floodguard.server import http_server
    http_server.sim = FloodSimulator(rows=12, cols=12, seed=5)
    http_server.sim.tick(6.0)
    for strategy in ("safest", "shortest"):
        d = http_server.build_route("n0_0", "n11_11", strategy, "dijkstra")
        a = http_server.build_route("n0_0", "n11_11", strategy, "astar")
        assert d["cost"] == a["cost"], (strategy, d["cost"], a["cost"])
    print("route astar/dijkstra ok")


def test_history_and_reset_api():
    import json
    import threading
    import urllib.request
    import urllib.error
    from floodguard.server import create_server, http_server

    http_server.sim = FloodSimulator(rows=8, cols=8, seed=1)
    srv = create_server(port=0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % srv.server_address[1]

    def call(path, method="GET"):
        req = urllib.request.Request(base + path, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    try:
        assert len(call("/api/history")[1]["history"]) == 1  # initial state
        call("/api/tick?hours=1", "POST")
        call("/api/tick?hours=1", "POST")
        hist = call("/api/history")[1]["history"]
        assert [h["time"] for h in hist] == [0, 1.0, 2.0]
        assert {"danger", "warning", "caution", "safe", "intensity"} <= set(hist[-1])
        assert call("/api/tick?hours=500", "POST")[0] == 400
        assert call("/api/tick?hours=-1", "POST")[0] == 400
        status, snap = call("/api/reset", "POST")
        assert status == 200 and snap["time"] == 0
        assert len(call("/api/history")[1]["history"]) == 1
        assert call("/api/reset?seed=42", "POST")[1]["seed"] == 42
        assert call("/api/network")[1]["seed"] == 42
        assert call("/api/reset?seed=abc", "POST")[0] == 400
    finally:
        srv.shutdown()
    print("history/reset api ok")


def run_all():
    test_min_heap()
    test_hash_table()
    test_avl_tree()
    test_avl_from_sorted()
    test_avl_contains_none_value()
    test_graph_dynamic_updates()
    test_dijkstra_vs_astar()
    test_bfs_dfs_components()
    test_simulator()
    test_flood_weights_follow_depth()
    test_water_collects_in_low_ground()
    test_water_recedes_after_storm()
    test_weather_random_but_reproducible()
    test_storm_shape()
    test_dangerous_roads_keeps_equal_depths()
    test_route_astar_matches_dijkstra()
    test_history_and_reset_api()
    print("\nAll tests PASSED")


if __name__ == "__main__":
    run_all()
