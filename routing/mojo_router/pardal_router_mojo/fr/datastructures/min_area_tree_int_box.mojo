"""A minimal `MinAreaTree` implementation specialized for `IntBox` bounds.

Ported from `app.freerouting.datastructures.MinAreaTree`:
- nodes are stored in leaves, tree built by minimal area-increase heuristic
- search uses a stack and bounding-box intersection
"""

from collections import List

from ..geometry.planar.int_box import IntBox
from ..geometry.planar.int_point import IntPoint


@fieldwise_init
struct NodeRef(Copyable, Movable):
    var is_leaf: Bool
    var idx: Int


fn _union_int_box(a: IntBox, b: IntBox) -> IntBox:
    var llx = a.ll.x if a.ll.x < b.ll.x else b.ll.x
    var lly = a.ll.y if a.ll.y < b.ll.y else b.ll.y
    var urx = a.ur.x if a.ur.x > b.ur.x else b.ur.x
    var ury = a.ur.y if a.ur.y > b.ur.y else b.ur.y
    return IntBox(IntPoint(llx, lly), IntPoint(urx, ury))


fn _contains_int_box(container: IntBox, inner: IntBox) -> Bool:
    if container.is_empty():
        return inner.is_empty()
    return (
        container.ll.x <= inner.ll.x
        and container.ll.y <= inner.ll.y
        and container.ur.x >= inner.ur.x
        and container.ur.y >= inner.ur.y
    )


@fieldwise_init
struct MinAreaTreeIntBox(Movable):
    # Leaf storage (parallel arrays; `List[T]` needs `T: Copyable`).
    var leaf_llx: List[Int]
    var leaf_lly: List[Int]
    var leaf_urx: List[Int]
    var leaf_ury: List[Int]
    var leaf_parent: List[Int]  # inner idx, or -1
    var leaf_object_id: List[Int]
    var leaf_shape_index: List[Int]

    # Inner node storage (parallel arrays).
    var inner_llx: List[Int]
    var inner_lly: List[Int]
    var inner_urx: List[Int]
    var inner_ury: List[Int]
    var inner_parent: List[Int]
    var inner_child_is_leaf_a: List[Bool]
    var inner_child_idx_a: List[Int]
    var inner_child_is_leaf_b: List[Bool]
    var inner_child_idx_b: List[Int]

    var root: NodeRef
    var leaf_count: Int

    fn __init__(out self):
        self.leaf_llx = List[Int]()
        self.leaf_lly = List[Int]()
        self.leaf_urx = List[Int]()
        self.leaf_ury = List[Int]()
        self.leaf_parent = List[Int]()
        self.leaf_object_id = List[Int]()
        self.leaf_shape_index = List[Int]()

        self.inner_llx = List[Int]()
        self.inner_lly = List[Int]()
        self.inner_urx = List[Int]()
        self.inner_ury = List[Int]()
        self.inner_parent = List[Int]()
        self.inner_child_is_leaf_a = List[Bool]()
        self.inner_child_idx_a = List[Int]()
        self.inner_child_is_leaf_b = List[Bool]()
        self.inner_child_idx_b = List[Int]()

        self.root = NodeRef(True, -1)
        self.leaf_count = 0

    fn _bounds(self, n: NodeRef) -> IntBox:
        if n.is_leaf:
            return IntBox(
                IntPoint(self.leaf_llx[n.idx], self.leaf_lly[n.idx]),
                IntPoint(self.leaf_urx[n.idx], self.leaf_ury[n.idx]),
            )
        return IntBox(
            IntPoint(self.inner_llx[n.idx], self.inner_lly[n.idx]),
            IntPoint(self.inner_urx[n.idx], self.inner_ury[n.idx]),
        )

    fn overlaps(self, shape: IntBox) -> List[Int]:
        # Returns leaf indices that intersect the query shape.
        var out = List[Int]()
        if self.leaf_count == 0:
            return out^
        var stack = List[NodeRef]()
        stack.append(self.root.copy())
        while len(stack) > 0:
            var n = stack.pop()
            if self._bounds(n).intersects(shape):
                if n.is_leaf:
                    out.append(n.idx)
                else:
                    stack.append(
                        NodeRef(
                            self.inner_child_is_leaf_a[n.idx],
                            self.inner_child_idx_a[n.idx],
                        )
                    )
                    stack.append(
                        NodeRef(
                            self.inner_child_is_leaf_b[n.idx],
                            self.inner_child_idx_b[n.idx],
                        )
                    )
        return out^

    fn insert_leaf(mut self, object_id: Int, shape_index: Int, shape: IntBox) -> Int:
        self.leaf_count += 1
        var leaf_id = len(self.leaf_llx)
        self.leaf_llx.append(shape.ll.x)
        self.leaf_lly.append(shape.ll.y)
        self.leaf_urx.append(shape.ur.x)
        self.leaf_ury.append(shape.ur.y)
        self.leaf_parent.append(-1)
        self.leaf_object_id.append(object_id)
        self.leaf_shape_index.append(shape_index)

        if self.leaf_count == 1:
            self.root = NodeRef(True, leaf_id)
            return leaf_id

        # Find leaf to replace starting from root, updating bounds on path.
        var leaf_to_replace = self._position_locate(NodeRef(True, leaf_id))

        var new_bounds = _union_int_box(
            self._bounds(NodeRef(True, leaf_id)), self._bounds(leaf_to_replace)
        )
        var parent = self.leaf_parent[leaf_to_replace.idx]
        var new_inner_id = len(self.inner_llx)
        self.inner_llx.append(new_bounds.ll.x)
        self.inner_lly.append(new_bounds.ll.y)
        self.inner_urx.append(new_bounds.ur.x)
        self.inner_ury.append(new_bounds.ur.y)
        self.inner_parent.append(parent)
        self.inner_child_is_leaf_a.append(leaf_to_replace.is_leaf)
        self.inner_child_idx_a.append(leaf_to_replace.idx)
        self.inner_child_is_leaf_b.append(True)
        self.inner_child_idx_b.append(leaf_id)

        # Update parents of children.
        self.leaf_parent[leaf_to_replace.idx] = new_inner_id
        self.leaf_parent[leaf_id] = new_inner_id

        if parent < 0:
            self.root = NodeRef(False, new_inner_id)
        else:
            # Update parent's child reference to point to new inner node.
            if (
                self.inner_child_is_leaf_a[parent]
                and self.inner_child_idx_a[parent] == leaf_to_replace.idx
            ):
                self.inner_child_is_leaf_a[parent] = False
                self.inner_child_idx_a[parent] = new_inner_id
            elif (
                self.inner_child_is_leaf_b[parent]
                and self.inner_child_idx_b[parent] == leaf_to_replace.idx
            ):
                self.inner_child_is_leaf_b[parent] = False
                self.inner_child_idx_b[parent] = new_inner_id

        return leaf_id

    fn remove_leaf(mut self, leaf_idx: Int) -> Bool:
        if self.leaf_count == 0 or leaf_idx < 0 or leaf_idx >= len(self.leaf_llx):
            return False

        if self.leaf_count == 1:
            _ = self.leaf_llx.pop()
            _ = self.leaf_lly.pop()
            _ = self.leaf_urx.pop()
            _ = self.leaf_ury.pop()
            _ = self.leaf_parent.pop()
            _ = self.leaf_object_id.pop()
            _ = self.leaf_shape_index.pop()
            self.leaf_count = 0
            self.root = NodeRef(True, -1)
            return True

        # Detach leaf from the tree structure.
        var parent = self.leaf_parent[leaf_idx]
        var recalc_from: Int = -1
        if parent < 0:
            self.root = NodeRef(True, -1)
        else:
            # Find sibling under parent.
            var sib_is_leaf: Bool
            var sib_idx: Int
            if (
                self.inner_child_is_leaf_a[parent]
                and self.inner_child_idx_a[parent] == leaf_idx
            ):
                sib_is_leaf = self.inner_child_is_leaf_b[parent]
                sib_idx = self.inner_child_idx_b[parent]
            elif (
                self.inner_child_is_leaf_b[parent]
                and self.inner_child_idx_b[parent] == leaf_idx
            ):
                sib_is_leaf = self.inner_child_is_leaf_a[parent]
                sib_idx = self.inner_child_idx_a[parent]
            else:
                # Tree structure already inconsistent; bail out.
                return False

            var grandparent = self.inner_parent[parent]
            recalc_from = grandparent
            if grandparent < 0:
                self.root = NodeRef(sib_is_leaf, sib_idx)
            else:
                # Replace parent in grandparent with sibling.
                if (
                    not self.inner_child_is_leaf_a[grandparent]
                    and self.inner_child_idx_a[grandparent] == parent
                ):
                    self.inner_child_is_leaf_a[grandparent] = sib_is_leaf
                    self.inner_child_idx_a[grandparent] = sib_idx
                elif (
                    not self.inner_child_is_leaf_b[grandparent]
                    and self.inner_child_idx_b[grandparent] == parent
                ):
                    self.inner_child_is_leaf_b[grandparent] = sib_is_leaf
                    self.inner_child_idx_b[grandparent] = sib_idx

            # Update sibling's parent pointer.
            if sib_is_leaf:
                self.leaf_parent[sib_idx] = grandparent
            else:
                self.inner_parent[sib_idx] = grandparent

        # Swap-remove leaf arrays to keep them dense.
        var last = len(self.leaf_llx) - 1
        if leaf_idx != last:
            # Move last leaf into removed slot.
            self.leaf_llx[leaf_idx] = self.leaf_llx[last]
            self.leaf_lly[leaf_idx] = self.leaf_lly[last]
            self.leaf_urx[leaf_idx] = self.leaf_urx[last]
            self.leaf_ury[leaf_idx] = self.leaf_ury[last]
            self.leaf_parent[leaf_idx] = self.leaf_parent[last]
            self.leaf_object_id[leaf_idx] = self.leaf_object_id[last]
            self.leaf_shape_index[leaf_idx] = self.leaf_shape_index[last]

            # Fix reference from the moved leaf's parent (if any).
            var moved_parent = self.leaf_parent[leaf_idx]
            if moved_parent >= 0:
                if (
                    self.inner_child_is_leaf_a[moved_parent]
                    and self.inner_child_idx_a[moved_parent] == last
                ):
                    self.inner_child_idx_a[moved_parent] = leaf_idx
                elif (
                    self.inner_child_is_leaf_b[moved_parent]
                    and self.inner_child_idx_b[moved_parent] == last
                ):
                    self.inner_child_idx_b[moved_parent] = leaf_idx
                else:
                    # If parent doesn't point at last, the moved leaf might have been the sibling
                    # in the detach step. That's fine if parent already points at leaf_idx.
                    # No-op recovery; leave parent pointers unchanged in this uncommon
                    # branch while keeping tree shape consistent.
                    pass

            # Root may have pointed to the moved leaf.
            if self.root.is_leaf and self.root.idx == last:
                self.root = NodeRef(True, leaf_idx)

        _ = self.leaf_llx.pop()
        _ = self.leaf_lly.pop()
        _ = self.leaf_urx.pop()
        _ = self.leaf_ury.pop()
        _ = self.leaf_parent.pop()
        _ = self.leaf_object_id.pop()
        _ = self.leaf_shape_index.pop()

        self.leaf_count -= 1
        if self.leaf_count == 0:
            self.root = NodeRef(True, -1)
            return True

        # Recompute parent bounds from recalc_from upward while they shrink.
        while recalc_from >= 0:
            var child_a = NodeRef(
                self.inner_child_is_leaf_a[recalc_from],
                self.inner_child_idx_a[recalc_from],
            )
            var child_b = NodeRef(
                self.inner_child_is_leaf_b[recalc_from],
                self.inner_child_idx_b[recalc_from],
            )
            var child_a_bounds = self._bounds(child_a)
            var child_b_bounds = self._bounds(child_b)
            var new_bounds = _union_int_box(child_a_bounds, child_b_bounds)
            var old_bounds = self._bounds(NodeRef(False, recalc_from))
            if _contains_int_box(old_bounds, new_bounds):
                break
            self.inner_llx[recalc_from] = new_bounds.ll.x
            self.inner_lly[recalc_from] = new_bounds.ll.y
            self.inner_urx[recalc_from] = new_bounds.ur.x
            self.inner_ury[recalc_from] = new_bounds.ur.y
            recalc_from = self.inner_parent[recalc_from]
        return True

    fn _position_locate(mut self, leaf_to_insert: NodeRef) -> NodeRef:
        var curr = self.root.copy()
        while not curr.is_leaf:
            var inner_bounds = self._bounds(curr)
            var updated = _union_int_box(inner_bounds, self._bounds(leaf_to_insert))
            self.inner_llx[curr.idx] = updated.ll.x
            self.inner_lly[curr.idx] = updated.ll.y
            self.inner_urx[curr.idx] = updated.ur.x
            self.inner_ury[curr.idx] = updated.ur.y

            var first_ref = NodeRef(
                self.inner_child_is_leaf_a[curr.idx], self.inner_child_idx_a[curr.idx]
            )
            var second_ref = NodeRef(
                self.inner_child_is_leaf_b[curr.idx], self.inner_child_idx_b[curr.idx]
            )
            var first_shape = self._bounds(first_ref)
            var second_shape = self._bounds(second_ref)
            var union_first = _union_int_box(self._bounds(leaf_to_insert), first_shape)
            var union_second = _union_int_box(
                self._bounds(leaf_to_insert), second_shape
            )
            var first_inc = union_first.area() - first_shape.area()
            var second_inc = union_second.area() - second_shape.area()
            if first_inc <= second_inc:
                curr = first_ref.copy()
            else:
                curr = second_ref.copy()
        return curr.copy()
