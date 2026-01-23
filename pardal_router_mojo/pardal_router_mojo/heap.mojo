from collections import List


struct PopResult:
    var g: UInt32
    var idx: Int

    fn __init__(out self, g: UInt32, idx: Int):
        self.g = g
        self.idx = idx


struct MinHeap:
    var f: List[UInt32]
    var g: List[UInt32]
    var idx: List[Int]

    fn __init__(out self):
        self.f = List[UInt32]()
        self.g = List[UInt32]()
        self.idx = List[Int]()

    fn is_empty(self) -> Bool:
        return len(self.idx) == 0

    fn clear(mut self):
        while len(self.idx) > 0:
            _ = self.f.pop()
            _ = self.g.pop()
            _ = self.idx.pop()

    fn _less(self, a: Int, b: Int) -> Bool:
        if self.f[a] != self.f[b]:
            return self.f[a] < self.f[b]
        if self.g[a] != self.g[b]:
            return self.g[a] < self.g[b]
        return self.idx[a] < self.idx[b]

    fn _swap(mut self, a: Int, b: Int):
        var tf = self.f[a]
        self.f[a] = self.f[b]
        self.f[b] = tf

        var tg = self.g[a]
        self.g[a] = self.g[b]
        self.g[b] = tg

        var ti = self.idx[a]
        self.idx[a] = self.idx[b]
        self.idx[b] = ti

    fn push(mut self, f: UInt32, g: UInt32, idx: Int):
        self.f.append(f)
        self.g.append(g)
        self.idx.append(idx)

        var i = len(self.idx) - 1
        while i > 0:
            var parent = (i - 1) // 2
            if self._less(parent, i):
                break
            self._swap(parent, i)
            i = parent

    fn pop_min(mut self) -> PopResult:
        var n = len(self.idx)
        if n == 1:
            var out_g = self.g[0]
            var out_idx = self.idx[0]
            _ = self.f.pop()
            _ = self.g.pop()
            _ = self.idx.pop()
            return PopResult(out_g, out_idx)

        var out_g = self.g[0]
        var out_idx = self.idx[0]

        var last_f = self.f[n - 1]
        var last_g = self.g[n - 1]
        var last_idx = self.idx[n - 1]
        _ = self.f.pop()
        _ = self.g.pop()
        _ = self.idx.pop()

        self.f[0] = last_f
        self.g[0] = last_g
        self.idx[0] = last_idx

        var i = 0
        while True:
            var left = 2 * i + 1
            var right = 2 * i + 2
            if left >= len(self.idx):
                break
            var best = left
            if right < len(self.idx) and self._less(right, left):
                best = right
            if self._less(i, best):
                break
            self._swap(i, best)
            i = best

        return PopResult(out_g, out_idx)
