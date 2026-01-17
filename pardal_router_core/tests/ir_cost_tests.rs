use pardal_router_core::ir::RoutingIr;

#[test]
fn build_cost_field_adjacent_adds_penalties_near_blocked_and_occ() {
    let mut ir = RoutingIr::new(1, 5, 1);
    let blocked = 1u32;
    // blocked at x=2, other net at x=4
    ir.set_occ(0, 2, 0, blocked);
    ir.set_occ(0, 4, 0, 9);

    let cost = ir.build_cost_field_adjacent(blocked, 3, 7);
    // x=1 neighbors blocked => blocked_penalty
    assert_eq!(cost[ir.idx(0, 1, 0)], 7);
    // x=3 neighbors blocked and net => 7 + 3
    assert_eq!(cost[ir.idx(0, 3, 0)], 10);
    // occupied cells get 0 cost
    assert_eq!(cost[ir.idx(0, 2, 0)], 0);
    assert_eq!(cost[ir.idx(0, 4, 0)], 0);
}

