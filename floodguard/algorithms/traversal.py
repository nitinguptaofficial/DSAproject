"""BFS and DFS traversal of the network.

Used to analyse connectivity: identifying connected flooded regions, checking
whether two parts of the city are reachable, and flood-fill of affected areas.
"""

from collections import deque


def bfs(graph, start):
    """Breadth-first search from `start`. Returns (order, parent)."""
    order = []
    parent = {}
    visited = {start}
    queue = deque([start])
    while queue:
        u = queue.popleft()
        order.append(u)
        for v in graph.neighbors(u):
            if v not in visited:
                visited.add(v)
                parent[v] = u
                queue.append(v)
    return order, parent


def dfs(graph, start):
    """Iterative depth-first search from `start`. Returns (order, parent)."""
    order = []
    parent = {}
    visited = {start}
    stack = [start]
    while stack:
        u = stack.pop()
        order.append(u)
        for v in graph.neighbors(u):
            if v not in visited:
                visited.add(v)
                parent[v] = u
                stack.append(v)
    return order, parent


def connected_components(graph, predicate=None):
    """Partition the graph into connected components.

    predicate: optional callable(vertex) -> bool. When given, only vertices
               passing the predicate are included (e.g. flooded vertices), and
               the result lists the connected components of the subgraph they
               induce.
    """
    if predicate is None:
        predicate = lambda v: True
    seen = set()
    components = []
    for start in graph.vertices():
        if not predicate(start) or start in seen:
            continue
        comp = []
        visited = {start}
        queue = deque([start])
        while queue:
            u = queue.popleft()
            comp.append(u)
            for v in graph.neighbors(u):
                if predicate(v) and v not in visited:
                    visited.add(v)
                    queue.append(v)
        seen.update(visited)
        components.append(comp)
    return components


def is_reachable(graph, a, b):
    order, _ = bfs(graph, a)
    return b in order
