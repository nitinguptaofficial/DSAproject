"""Self-balancing AVL tree.

Organises locations/intersections by a numeric key (e.g. flood severity or
elevation) so the system can perform fast ordered queries such as "give me the
top-10 most dangerous roads" or "all roads with depth >= 0.3 m" as a fully
ordered range. Keeps O(log n) height balance after every insert/delete.
"""


class AVLNode:
    __slots__ = ("key", "value", "left", "right", "height")

    def __init__(self, key, value):
        self.key = key
        self.value = value
        self.left = None
        self.right = None
        self.height = 1


class AVLTree:
    def __init__(self):
        self.root = None
        self._size = 0

    @classmethod
    def from_sorted(cls, items):
        """Build a perfectly balanced tree from (key, value) pairs in O(n).

        `items` must be sorted by key with no duplicate keys. Much faster than
        n separate inserts when rebuilding the whole index at once.
        """
        tree = cls()

        def build(lo, hi):
            if lo > hi:
                return None
            mid = (lo + hi) // 2
            node = AVLNode(*items[mid])
            node.left = build(lo, mid - 1)
            node.right = build(mid + 1, hi)
            tree._update_height(node)
            return node

        tree.root = build(0, len(items) - 1)
        tree._size = len(items)
        return tree

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _height(self, node):
        return node.height if node else 0

    def _update_height(self, node):
        node.height = 1 + max(self._height(node.left), self._height(node.right))

    def _balance_factor(self, node):
        return self._height(node.left) - self._height(node.right)

    def _rotate_right(self, y):
        x = y.left
        t2 = x.right
        x.right = y
        y.left = t2
        self._update_height(y)
        self._update_height(x)
        return x

    def _rotate_left(self, x):
        y = x.right
        t2 = y.left
        y.left = x
        x.right = t2
        self._update_height(x)
        self._update_height(y)
        return y

    def _balance(self, node):
        self._update_height(node)
        bf = self._balance_factor(node)
        if bf > 1:
            if self._balance_factor(node.left) < 0:
                node.left = self._rotate_left(node.left)
            return self._rotate_right(node)
        if bf < -1:
            if self._balance_factor(node.right) > 0:
                node.right = self._rotate_right(node.right)
            return self._rotate_left(node)
        return node

    # ------------------------------------------------------------------ #
    # Insert / delete
    # ------------------------------------------------------------------ #
    def insert(self, key, value=None):
        self.root = self._insert(self.root, key, value)
        self._size += 1

    def _insert(self, node, key, value):
        if node is None:
            return AVLNode(key, value)
        if key < node.key:
            node.left = self._insert(node.left, key, value)
        elif key > node.key:
            node.right = self._insert(node.right, key, value)
        else:
            # duplicate: update value, don't grow size
            node.value = value
            self._size -= 1
            return node
        return self._balance(node)

    def delete(self, key):
        if self.root is None:
            return False
        self.root, removed = self._delete(self.root, key)
        if removed:
            self._size -= 1
        return removed

    def _delete(self, node, key):
        if node is None:
            return None, False
        if key < node.key:
            node.left, removed = self._delete(node.left, key)
        elif key > node.key:
            node.right, removed = self._delete(node.right, key)
        else:
            removed = True
            if node.left is None:
                return node.right, True
            if node.right is None:
                return node.left, True
            # two children: replace with inorder successor
            succ = self._min(node.right)
            node.key, node.value = succ.key, succ.value
            node.right, _ = self._delete(node.right, succ.key)
        return self._balance(node), removed

    def _min(self, node):
        while node.left is not None:
            node = node.left
        return node

    # ------------------------------------------------------------------ #
    # Queries
    # ------------------------------------------------------------------ #
    def _find(self, key):
        node = self.root
        while node is not None:
            if key == node.key:
                return node
            node = node.left if key < node.key else node.right
        return None

    def search(self, key):
        """Return the value stored under key, or None if absent."""
        node = self._find(key)
        return node.value if node else None

    def __contains__(self, key):
        return self._find(key) is not None

    def min_key(self):
        if self.root is None:
            return None
        return self._min(self.root).key

    def inorder(self):
        out = []
        self._inorder(self.root, out)
        return out

    def _inorder(self, node, out):
        if node is None:
            return
        self._inorder(node.left, out)
        out.append((node.key, node.value))
        self._inorder(node.right, out)

    def range_query(self, lo, hi):
        """Return all (key, value) pairs with lo <= key <= hi, in order."""
        out = []
        self._range(self.root, lo, hi, out)
        return out

    def _range(self, node, lo, hi, out):
        if node is None:
            return
        if lo < node.key:
            self._range(node.left, lo, hi, out)
        if lo <= node.key <= hi:
            out.append((node.key, node.value))
        if node.key < hi:
            self._range(node.right, lo, hi, out)

    def top_k(self, k):
        """Return the k largest (key, value) pairs, descending."""
        entries = self.inorder()
        return list(reversed(entries[-k:])) if k > 0 else []

    def __len__(self):
        return self._size

    def height(self):
        return self._height(self.root)

    def __repr__(self):
        return "AVLTree(size=%d, height=%d)" % (self._size, self.height())
