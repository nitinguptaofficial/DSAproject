"""A* search on a weighted graph.

Like Dijkstra but guided by a heuristic h(v) that estimates the remaining cost
from v to the goal. When h is admissible the first path found is optimal, and
in practice A* explores far fewer vertices than Dijkstra on a large city grid.
Uses the same MinHeap priority queue, keyed by f = g + h.
"""

from floodguard.structures import MinHeap
from floodguard.algorithms.dijkstra import reconstruct_path


def astar(graph, source, target, heuristic=None, weight_key=None, weight_fn=None):
    """Return (path, cost) from source to target using A*.

    heuristic: callable(vertex) -> estimated remaining cost to target. If None,
               a zero heuristic is used (equivalent to Dijkstra).
    """
    if not graph.has_vertex(source):
        raise KeyError("source %r not in graph" % (source,))
    if not graph.has_vertex(target):
        raise KeyError("target %r not in graph" % (target,))

    if heuristic is None:
        heuristic = lambda v: 0.0

    g = {source: 0.0}
    prev = {}
    open_set = MinHeap()
    open_set.push(heuristic(source), source)
    closed = set()

    while not open_set.is_empty():
        f, u = open_set.pop()
        if u in closed:
            continue
        if u == target:
            return reconstruct_path(prev, target), g[u]
        closed.add(u)

        for v in graph.neighbors(u):
            if v in closed:
                continue
            if weight_fn is not None:
                w = weight_fn(u, v)
            else:
                w = graph.get_weight(u, v)
            if w is None:
                continue
            if weight_key is not None:
                w = weight_key(w)
            tentative = g[u] + w
            if tentative < g.get(v, float("inf")):
                g[v] = tentative
                prev[v] = u
                fv = tentative + heuristic(v)
                if v in open_set:
                    open_set.decrease_key(v, fv)
                else:
                    open_set.push(fv, v)

    return None, None
