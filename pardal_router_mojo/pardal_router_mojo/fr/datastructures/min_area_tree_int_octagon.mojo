"""A minimal `MinAreaTree` implementation specialized for `IntOctagon` bounds.

This mirrors `min_area_tree_int_box.mojo` but stores full octagon bounds and
uses `IntOctagon.intersects(...)` for traversal pruning.
"""

from collections import List

from ..geometry.planar.int_octagon import IntOctagon


@fieldwise_init
struct NodeRef(Copyable, Movable):
    var is_leaf: Bool
    var idx: Int


fn _union_oct(a: IntOctagon, b: IntOctagon) -> IntOctagon:
    return a.union(b)


fn _contains_oct(outer: IntOctagon, inner: IntOctagon) -> Bool:
    var outer_bb = outer.bounding_box()
    var inner_bb = inner.bounding_box()
    if outer_bb.is_empty():
        return inner_bb.is_empty()
    return (
        outer_bb.ll.x <= inner_bb.ll.x
        and outer_bb.ll.y <= inner_bb.ll.y
        and outer_bb.ur.x >= inner_bb.ur.x
        and outer_bb.ur.y >= inner_bb.ur.y
    )


@fieldwise_init
struct MinAreaTreeIntOctagon(Movable):
    # Leaf storage (parallel arrays).
    var leaf_lx: List[Int]
    var leaf_rx: List[Int]
    var leaf_by: List[Int]
    var leaf_ty: List[Int]
    var leaf_lld: List[Int]
    var leaf_urd: List[Int]
    var leaf_uld: List[Int]
    var leaf_lrd: List[Int]
    var leaf_parent: List[Int]
    var leaf_object_id: List[Int]
    var leaf_shape_index: List[Int]

    # Inner node storage (parallel arrays).
    var inner_lx: List[Int]
    var inner_rx: List[Int]
    var inner_by: List[Int]
    var inner_ty: List[Int]
    var inner_lld: List[Int]
    var inner_urd: List[Int]
    var inner_uld: List[Int]
    var inner_lrd: List[Int]
    var inner_parent: List[Int]
    var inner_child_is_leaf_a: List[Bool]
    var inner_child_idx_a: List[Int]
    var inner_child_is_leaf_b: List[Bool]
    var inner_child_idx_b: List[Int]

    var root: NodeRef
    var leaf_count: Int

    fn __init__(out self):
        self.leaf_lx = List[Int]()
        self.leaf_rx = List[Int]()
        self.leaf_by = List[Int]()
        self.leaf_ty = List[Int]()
        self.leaf_lld = List[Int]()
        self.leaf_urd = List[Int]()
        self.leaf_uld = List[Int]()
        self.leaf_lrd = List[Int]()
        self.leaf_parent = List[Int]()
        self.leaf_object_id = List[Int]()
        self.leaf_shape_index = List[Int]()

        self.inner_lx = List[Int]()
        self.inner_rx = List[Int]()
        self.inner_by = List[Int]()
        self.inner_ty = List[Int]()
        self.inner_lld = List[Int]()
        self.inner_urd = List[Int]()
        self.inner_uld = List[Int]()
        self.inner_lrd = List[Int]()
        self.inner_parent = List[Int]()
        self.inner_child_is_leaf_a = List[Bool]()
        self.inner_child_idx_a = List[Int]()
        self.inner_child_is_leaf_b = List[Bool]()
        self.inner_child_idx_b = List[Int]()

        self.root = NodeRef(True, -1)
        self.leaf_count = 0

    fn _bounds(self, n: NodeRef) -> IntOctagon:
        if n.is_leaf:
            return IntOctagon(
                self.leaf_lx[n.idx],
                self.leaf_rx[n.idx],
                self.leaf_by[n.idx],
                self.leaf_ty[n.idx],
                self.leaf_lld[n.idx],
                self.leaf_urd[n.idx],
                self.leaf_uld[n.idx],
                self.leaf_lrd[n.idx],
            )
        return IntOctagon(
            self.inner_lx[n.idx],
            self.inner_rx[n.idx],
            self.inner_by[n.idx],
            self.inner_ty[n.idx],
            self.inner_lld[n.idx],
            self.inner_urd[n.idx],
            self.inner_uld[n.idx],
            self.inner_lrd[n.idx],
        )

    fn overlaps(self, shape: IntOctagon) -> List[Int]:
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

    fn insert_leaf(
        mut self, object_id: Int, shape_index: Int, shape: IntOctagon
    ) -> Int:
        self.leaf_count += 1
        var leaf_id = len(self.leaf_lx)
        self.leaf_lx.append(shape.leftX)
        self.leaf_rx.append(shape.rightX)
        self.leaf_by.append(shape.bottomY)
        self.leaf_ty.append(shape.topY)
        self.leaf_lld.append(shape.lowerLeftDiagonalX)
        self.leaf_urd.append(shape.upperRightDiagonalX)
        self.leaf_uld.append(shape.upperLeftDiagonalX)
        self.leaf_lrd.append(shape.lowerRightDiagonalX)
        self.leaf_parent.append(-1)
        self.leaf_object_id.append(object_id)
        self.leaf_shape_index.append(shape_index)

        if self.leaf_count == 1:
            self.root = NodeRef(True, leaf_id)
            return leaf_id

        var leaf_to_replace = self._position_locate(NodeRef(True, leaf_id))

        var new_bounds = _union_oct(
            self._bounds(NodeRef(True, leaf_id)),
            self._bounds(leaf_to_replace),
        )
        var parent = self.leaf_parent[leaf_to_replace.idx]
        var new_inner_id = len(self.inner_lx)
        self.inner_lx.append(new_bounds.leftX)
        self.inner_rx.append(new_bounds.rightX)
        self.inner_by.append(new_bounds.bottomY)
        self.inner_ty.append(new_bounds.topY)
        self.inner_lld.append(new_bounds.lowerLeftDiagonalX)
        self.inner_urd.append(new_bounds.upperRightDiagonalX)
        self.inner_uld.append(new_bounds.upperLeftDiagonalX)
        self.inner_lrd.append(new_bounds.lowerRightDiagonalX)
        self.inner_parent.append(parent)
        self.inner_child_is_leaf_a.append(leaf_to_replace.is_leaf)
        self.inner_child_idx_a.append(leaf_to_replace.idx)
        self.inner_child_is_leaf_b.append(True)
        self.inner_child_idx_b.append(leaf_id)

        self.leaf_parent[leaf_to_replace.idx] = new_inner_id
        self.leaf_parent[leaf_id] = new_inner_id

        if parent < 0:
            self.root = NodeRef(False, new_inner_id)
        else:
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
        if self.leaf_count == 0 or leaf_idx < 0 or leaf_idx >= len(self.leaf_lx):
            return False
        if self.leaf_count == 1:
            _ = self.leaf_lx.pop()
            _ = self.leaf_rx.pop()
            _ = self.leaf_by.pop()
            _ = self.leaf_ty.pop()
            _ = self.leaf_lld.pop()
            _ = self.leaf_urd.pop()
            _ = self.leaf_uld.pop()
            _ = self.leaf_lrd.pop()
            _ = self.leaf_parent.pop()
            _ = self.leaf_object_id.pop()
            _ = self.leaf_shape_index.pop()
            self.leaf_count = 0
            self.root = NodeRef(True, -1)
            return True

        var parent = self.leaf_parent[leaf_idx]
        var recalc_from: Int = -1
        if parent < 0:
            self.root = NodeRef(True, -1)
        else:
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
                return False

            var grandparent = self.inner_parent[parent]
            recalc_from = grandparent
            if grandparent < 0:
                self.root = NodeRef(sib_is_leaf, sib_idx)
            else:
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

            if sib_is_leaf:
                self.leaf_parent[sib_idx] = grandparent
            else:
                self.inner_parent[sib_idx] = grandparent

        var last = len(self.leaf_lx) - 1
        if leaf_idx != last:
            self.leaf_lx[leaf_idx] = self.leaf_lx[last]
            self.leaf_rx[leaf_idx] = self.leaf_rx[last]
            self.leaf_by[leaf_idx] = self.leaf_by[last]
            self.leaf_ty[leaf_idx] = self.leaf_ty[last]
            self.leaf_lld[leaf_idx] = self.leaf_lld[last]
            self.leaf_urd[leaf_idx] = self.leaf_urd[last]
            self.leaf_uld[leaf_idx] = self.leaf_uld[last]
            self.leaf_lrd[leaf_idx] = self.leaf_lrd[last]
            self.leaf_parent[leaf_idx] = self.leaf_parent[last]
            self.leaf_object_id[leaf_idx] = self.leaf_object_id[last]
            self.leaf_shape_index[leaf_idx] = self.leaf_shape_index[last]

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
            if self.root.is_leaf and self.root.idx == last:
                self.root = NodeRef(True, leaf_idx)

        _ = self.leaf_lx.pop()
        _ = self.leaf_rx.pop()
        _ = self.leaf_by.pop()
        _ = self.leaf_ty.pop()
        _ = self.leaf_lld.pop()
        _ = self.leaf_urd.pop()
        _ = self.leaf_uld.pop()
        _ = self.leaf_lrd.pop()
        _ = self.leaf_parent.pop()
        _ = self.leaf_object_id.pop()
        _ = self.leaf_shape_index.pop()

        self.leaf_count -= 1
        if self.leaf_count == 0:
            self.root = NodeRef(True, -1)
            return True

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
            var new_bounds = _union_oct(child_a_bounds, child_b_bounds)
            var old_bounds = self._bounds(NodeRef(False, recalc_from))
            if _contains_oct(old_bounds, new_bounds):
                break
            self.inner_lx[recalc_from] = new_bounds.leftX
            self.inner_rx[recalc_from] = new_bounds.rightX
            self.inner_by[recalc_from] = new_bounds.bottomY
            self.inner_ty[recalc_from] = new_bounds.topY
            self.inner_lld[recalc_from] = new_bounds.lowerLeftDiagonalX
            self.inner_urd[recalc_from] = new_bounds.upperRightDiagonalX
            self.inner_uld[recalc_from] = new_bounds.upperLeftDiagonalX
            self.inner_lrd[recalc_from] = new_bounds.lowerRightDiagonalX
            recalc_from = self.inner_parent[recalc_from]
        return True

    fn _position_locate(mut self, leaf_to_insert: NodeRef) -> NodeRef:
        var curr = self.root.copy()
        while not curr.is_leaf:
            var inner_bounds = self._bounds(curr)
            var updated = _union_oct(inner_bounds, self._bounds(leaf_to_insert))
            self.inner_lx[curr.idx] = updated.leftX
            self.inner_rx[curr.idx] = updated.rightX
            self.inner_by[curr.idx] = updated.bottomY
            self.inner_ty[curr.idx] = updated.topY
            self.inner_lld[curr.idx] = updated.lowerLeftDiagonalX
            self.inner_urd[curr.idx] = updated.upperRightDiagonalX
            self.inner_uld[curr.idx] = updated.upperLeftDiagonalX
            self.inner_lrd[curr.idx] = updated.lowerRightDiagonalX

            var a_ref = NodeRef(
                self.inner_child_is_leaf_a[curr.idx],
                self.inner_child_idx_a[curr.idx],
            )
            var b_ref = NodeRef(
                self.inner_child_is_leaf_b[curr.idx],
                self.inner_child_idx_b[curr.idx],
            )
            var a_shape = self._bounds(a_ref)
            var b_shape = self._bounds(b_ref)
            var union_a = _union_oct(self._bounds(leaf_to_insert), a_shape)
            var union_b = _union_oct(self._bounds(leaf_to_insert), b_shape)
            var inc_a = union_a.bounding_box().area() - a_shape.bounding_box().area()
            var inc_b = union_b.bounding_box().area() - b_shape.bounding_box().area()
            if inc_a <= inc_b:
                curr = a_ref.copy()
            else:
                curr = b_ref.copy()
        return curr.copy()
