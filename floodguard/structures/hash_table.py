"""Hash table (separate chaining) with dynamic resizing.

Stores and retrieves location-wise flood information, road conditions and
drainage details in amortised O(1) time.
"""


class HashTable:
    def __init__(self, capacity=16, load_factor=0.75):
        self._capacity = capacity
        self._load_factor = load_factor
        self._buckets = [[] for _ in range(capacity)]
        self._size = 0

    def _hash(self, key):
        return abs(hash(key)) % self._capacity

    def _resize(self, new_capacity):
        old_buckets = self._buckets
        self._capacity = new_capacity
        self._buckets = [[] for _ in range(new_capacity)]
        self._size = 0
        for bucket in old_buckets:
            for k, v in bucket:
                self[k] = v

    def _maybe_resize(self):
        if self._size / self._capacity > self._load_factor:
            self._resize(self._capacity * 2)

    def __setitem__(self, key, value):
        idx = self._hash(key)
        bucket = self._buckets[idx]
        for i, (k, _) in enumerate(bucket):
            if k == key:
                bucket[i] = (key, value)
                return
        bucket.append((key, value))
        self._size += 1
        self._maybe_resize()

    def __getitem__(self, key):
        idx = self._hash(key)
        for k, v in self._buckets[idx]:
            if k == key:
                return v
        raise KeyError(key)

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key):
        idx = self._hash(key)
        for k, _ in self._buckets[idx]:
            if k == key:
                return True
        return False

    def __delitem__(self, key):
        idx = self._hash(key)
        bucket = self._buckets[idx]
        for i, (k, _) in enumerate(bucket):
            if k == key:
                del bucket[i]
                self._size -= 1
                return
        raise KeyError(key)

    def __len__(self):
        return self._size

    def keys(self):
        out = []
        for bucket in self._buckets:
            for k, _ in bucket:
                out.append(k)
        return out

    def values(self):
        out = []
        for bucket in self._buckets:
            for _, v in bucket:
                out.append(v)
        return out

    def items(self):
        out = []
        for bucket in self._buckets:
            for k, v in bucket:
                out.append((k, v))
        return out

    def __iter__(self):
        return iter(self.keys())

    def __repr__(self):
        return "HashTable(size=%d, capacity=%d)" % (self._size, self._capacity)
