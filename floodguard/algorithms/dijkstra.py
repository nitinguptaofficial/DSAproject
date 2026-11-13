"""Dijkstra's shortest-path algorithm on a weighted graph.

Uses the MinHeap priority queue so the next lowest-cost vertex is extracted in
O(log n). Returns the optimal path and its total cost (here, the "safest"
route when edge weights represent flood-adjusted travel cost).
"""

from floodguard.structures import MinHeap


def dijkstra(graph, source, target=None, weight_key=None, weight_fn=None):
    """Shortest paths from `source`.

    Args:
        graph: Graph instance.
        source: start vertex.
        target: optional destination; if given, stop early when reached.
        weight_key: optional callable(weight) -> adjusted numeric cost.
        weight_fn: optional callable(u, v) -> raw weight, overriding graph weights.

    Returns:
        (dist, prev) where dist: vertex -> cost, prev: vertex -> predecessor.
    """
    if not graph.has_vertex(source):
        raise KeyError("source %r not in graph" % (source,))

    dist = {source: 0}
    prev = {}
    heap = MinHeap()
    heap.push(0.0, source)
    settled = set()

    while not heap.is_empty():
        d, u = heap.pop()
        if u in settled:
            continue
        settled.add(u)
        if target is not None and u == target:
            break

        for v in graph.neighbors(u):
            if weight_fn is not None:
                w = weight_fn(u, v)
            else:
                w = graph.get_weight(u, v)
            if w is None:
                continue
            if weight_key is not None:
                w = weight_key(w)
            nd = d + w
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                if v in heap:
                    heap.decrease_key(v, nd)
                else:
                    heap.push(nd, v)

    return dist, prev


def reconstruct_path(prev, target):
    """Rebuild the vertex path from a prev dict."""
    if target not in prev:
        return [target]
    path = [target]
    cur = target
    while cur in prev:
        cur = prev[cur]
        path.append(cur)
    path.reverse()
    return path


def shortest_path(graph, source, target, weight_key=None, weight_fn=None):
    """Convenience: return (path, cost) from source to target."""
    dist, prev = dijkstra(graph, source, target, weight_key=weight_key, weight_fn=weight_fn)
    if target not in dist:
        return None, None
    return reconstruct_path(prev, target), dist[target]
