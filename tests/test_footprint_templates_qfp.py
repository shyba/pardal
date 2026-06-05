from __future__ import annotations

from pardal.footprint_templates import generate_qfp_pads


def test_generate_qfp_pads_no_overlap_for_tqfp32():
    pads = generate_qfp_pads(pin_count=32, pitch=0.8, body_size=(7.0, 7.0), pad_size=(0.5, 1.2))
    assert len(pads) == 32

    # Sanity: adjacent pads on a side should not overlap in the pitch direction.
    # Using a conservative check: for pads sharing the same x offset, compare y spacing.
    pads_by_x = {}
    for pad in pads:
        pads_by_x.setdefault(round(pad.position_offset[0], 3), []).append(pad)

    for same_x in pads_by_x.values():
        if len(same_x) <= 1:
            continue
        same_x.sort(key=lambda p: p.position_offset[1])
        for a, b in zip(same_x, same_x[1:]):
            dy = abs(b.position_offset[1] - a.position_offset[1])
            assert dy >= max(a.size[1], b.size[1]) - 1e-6

