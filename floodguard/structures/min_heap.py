"""Binary min-heap priority queue.

Used by Dijkstra and A* to always extract the lowest-cost vertex in O(log n).
Supports decrease-key (update of an existing element's priority), which is
essential for efficient shortest-path algorithms on weighted graphs.
"""


class MinHeap:
    def __init__(self):
        self._items = []  # list of [priority, value]
        self._pos = {}    # value -> index in _items

    def __len__(self):
        return len(self._items)

    def is_empty(self):
        return not self._items

    def peek(self):
        """Return (priority, value) of the smallest element without removing it."""
        if not self._items:
            raise IndexError("peek from empty heap")
        return self._items[0][0], self._items[0][1]

    def _swap(self, i, j):
        self._items[i], self._items[j] = self._items[j], self._items[i]
        self._pos[self._items[i][1]] = i
        self._pos[self._items[j][1]] = j

    def _sift_up(self, idx):
        while idx > 0:
            parent = (idx - 1) // 2
            if self._items[idx][0] < self._items[parent][0]:
                self._swap(idx, parent)
                idx = parent
            else:
                break

    def _sift_down(self, idx):
        n = len(self._items)
        while True:
            left = 2 * idx + 1
            right = 2 * idx + 2
            smallest = idx
            if left < n and self._items[left][0] < self._items[smallest][0]:
                smallest = left
            if right < n and self._items[right][0] < self._items[smallest][0]:
                smallest = right
            if smallest == idx:
                break
            self._swap(idx, smallest)
            idx = smallest

    def push(self, priority, value):
        """Insert value with the given priority. Returns nothing."""
        if value in self._pos:
            raise ValueError("value already in heap (use decrease_key)")
        self._items.append([priority, value])
        self._pos[value] = len(self._items) - 1
        self._sift_up(len(self._items) - 1)

    def pop(self):
        """Remove and return (priority, value) of the smallest element."""
        if not self._items:
            raise IndexError("pop from empty heap")
        root = self._items[0]
        last = self._items.pop()
        del self._pos[root[1]]
        if self._items:
            self._items[0] = last
            self._pos[last[1]] = 0
            self._sift_down(0)
        return root[0], root[1]

    def decrease_key(self, value, new_priority):
        """Lower the priority of an existing value. O(log n)."""
        if value not in self._pos:
            raise ValueError("decrease_key on missing value")
        idx = self._pos[value]
        if new_priority > self._items[idx][0]:
            raise ValueError("decrease_key only lowers priority")
        self._items[idx][0] = new_priority
        self._sift_up(idx)

    def __contains__(self, value):
        return value in self._pos

    def __repr__(self):
        return "MinHeap(%r)" % ([p for p, _ in self._items],)
