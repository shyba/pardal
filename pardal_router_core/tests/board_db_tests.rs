use pardal_router_core::board::BoardDbNm;
use pardal_router_core::board_nm::BoardNm;
use pardal_router_core::drc_nm::{TerminalNm, TrackNm, ViaNm};
use pardal_router_core::geom_nm::{CircleNm, Nm, PointNm, SegmentNm};
use pardal_router_core::spatial_nm::AabbNm;

#[test]
fn board_db_indexes_tracks_vias_and_terminals_by_layer() {
    let mut board = BoardNm::new(2);

    board.tracks.push(TrackNm {
        net_id: 2,
        clearance_class: 0,
        layer: 0,
        seg: SegmentNm {
            a: PointNm::new(0, 0),
            b: PointNm::new(10_000_000, 0),
        },
        r: Nm(100_000),
    });

    board.vias.push(ViaNm {
        net_id: 3,
        clearance_class: 0,
        layers: (0, 1),
        padstack: None,
        circle: CircleNm {
            center: PointNm::new(5_000_000, 2_000_000),
            r: Nm(200_000),
        },
        shapes: Vec::new(),
    });

    board.terminals.push(TerminalNm {
        net_id: 4,
        pin_ref: Some("U1-1".to_string()),
        clearance_class: 0,
        layers: vec![0],
        circle: CircleNm {
            center: PointNm::new(9_000_000, 1_000_000),
            r: Nm(300_000),
        },
        shapes: Vec::new(),
    });

    let db = BoardDbNm::from_board(board, 2_000_000, Nm(0));

    let mut out: Vec<usize> = Vec::new();
    db.query_tracks(
        0,
        AabbNm {
            min_x: 4_900_000,
            min_y: -500_000,
            max_x: 5_100_000,
            max_y: 500_000,
        },
        &mut out,
    );
    assert_eq!(out, vec![0]);

    db.query_vias(
        0,
        AabbNm {
            min_x: 4_700_000,
            min_y: 1_700_000,
            max_x: 5_300_000,
            max_y: 2_300_000,
        },
        &mut out,
    );
    assert_eq!(out, vec![0]);

    // Via should also be queryable on the other layer.
    db.query_vias(
        1,
        AabbNm {
            min_x: 4_700_000,
            min_y: 1_700_000,
            max_x: 5_300_000,
            max_y: 2_300_000,
        },
        &mut out,
    );
    assert_eq!(out, vec![0]);

    // Terminal is only on layer 0.
    db.query_terminals(
        0,
        AabbNm {
            min_x: 8_500_000,
            min_y: 500_000,
            max_x: 9_500_000,
            max_y: 1_500_000,
        },
        &mut out,
    );
    assert_eq!(out, vec![0]);
    db.query_terminals(
        1,
        AabbNm {
            min_x: 8_500_000,
            min_y: 500_000,
            max_x: 9_500_000,
            max_y: 1_500_000,
        },
        &mut out,
    );
    assert!(out.is_empty());
}
