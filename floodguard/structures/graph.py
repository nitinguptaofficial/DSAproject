"""Weighted graph representing the city's road + drainage network.

Vertices are intersections / manholes; edges are roads or drains. Edges carry
a dynamic weight (a generalised travel cost that rises with flood severity), so
the graph supports efficient dynamic updates when new water-level data arrives.
"""


class Graph:
    def __init__(self, directed=False):
        self.directed = directed
        self._vertices = {}    # vertex -> metadata dict
        self._adj = {}         # vertex -> {neighbor: weight}
        self._edges = set()    # set of frozenset({u, v}) for undirected bookkeeping

    # ------------------------------------------------------------------ #
    # Vertex / edge construction
    # ------------------------------------------------------------------ #
    def add_vertex(self, v, **meta):
        if v not in self._vertices:
            self._vertices[v] = {}
            self._adj[v] = {}
        self._vertices[v].update(meta)
        return v

    def has_vertex(self, v):
        return v in self._vertices

    def add_edge(self, u, v, weight):
        self.add_vertex(u)
        self.add_vertex(v)
        self._adj[u][v] = weight
        if not self.directed:
            self._adj[v][u] = weight
            self._edges.add(frozenset((u, v)))
        else:
            self._edges.add((u, v))

    def get_weight(self, u, v):
        """Weight of edge u->v, or None if absent."""
        return self._adj[u].get(v)

    def update_edge_weight(self, u, v, new_weight):
        """Dynamic graph update: assign a new weight to an existing edge.

        Raises KeyError if the edge does not exist. This is how the system
        reacts to fresh rainfall / water-level readings.
        """
        if u not in self._adj or v not in self._adj[u]:
            raise KeyError("no such edge (%s, %s)" % (u, v))
        self._adj[u][v] = new_weight
        if not self.directed:
            self._adj[v][u] = new_weight

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def neighbors(self, v):
        return list(self._adj.get(v, {}))

    def degree(self, v):
        return len(self._adj.get(v, {}))

    def vertices(self):
        return list(self._vertices.keys())

    def num_vertices(self):
        return len(self._vertices)

    def num_edges(self):
        return len(self._edges)

    def edge_list(self):
        """Return [(u, v, weight), ...]."""
        out = []
        if self.directed:
            for u in self._adj:
                for v, w in self._adj[u].items():
                    out.append((u, v, w))
        else:
            seen = set()
            for u in self._adj:
                for v, w in self._adj[u].items():
                    key = frozenset((u, v))
                    if key not in seen:
                        seen.add(key)
                        out.append((u, v, w))
        return out

    def vertex_meta(self, v):
        return self._vertices.get(v, {})

    def __repr__(self):
        return "Graph(%d vertices, %d edges)" % (self.num_vertices(), self.num_edges())
