import builtins

from pardal.footprint_library import get_footprint_pads


def test_production_intent_footprints_have_deterministic_pads():
    testpoint_pads, testpoint_error = get_footprint_pads(
        "TestPoint:TestPoint_Pad_1.0mm"
    )
    assert testpoint_error is None
    assert len(testpoint_pads) == 1
    assert testpoint_pads[0].is_smd

    fiducial_pads, fiducial_error = get_footprint_pads("Fiducial:Fiducial_1mm_Mask2mm")
    assert fiducial_error is None
    assert len(fiducial_pads) == 1
    assert fiducial_pads[0].is_smd

    hole_pads, hole_error = get_footprint_pads("MountingHole:MountingHole_3.2mm_M3")
    assert hole_error is None
    assert len(hole_pads) == 1
    assert hole_pads[0].is_tht
    assert hole_pads[0].drill == 3.2


def test_template_import_failure_falls_back_to_unknown_footprint(monkeypatch):
    original_import = builtins.__import__

    def fail_template_import(name, *args, **kwargs):
        if name == "pardal.footprint_templates":
            raise ImportError("template module unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_template_import)

    pads, error = get_footprint_pads("NoSuchLib:NoSuchFootprint")

    assert pads == []
    assert error == "Unknown footprint: NoSuchLib:NoSuchFootprint"


def test_local_kicad_mod_loader_preserves_through_hole_drill(tmp_path, monkeypatch):
    footprints = tmp_path / "footprints"
    footprints.mkdir()
    (footprints / "LocalHeader.kicad_mod").write_text(
        """
        (footprint "LocalHeader"
          (pad "1" thru_hole rect
            (at 0 0)
            (size 1.7 1.7)
            (drill 1)
            (layers "*.Cu" "*.Mask"))
          (pad "2" thru_hole circle
            (at 0 2.54)
            (size 1.7 1.7)
            (drill 0.9)
            (layers "*.Cu" "*.Mask")))
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("PARDAL_LOCAL_FOOTPRINT_DIRS", str(footprints))

    pads, error = get_footprint_pads("atopile:LocalHeader")

    assert error is None
    assert [pad.drill for pad in pads] == [1.0, 0.9]
    assert [pad.position_offset for pad in pads] == [(0.0, 0.0), (0.0, 2.54)]


def test_local_through_hole_without_drill_is_not_used(tmp_path, monkeypatch):
    footprints = tmp_path / "footprints"
    footprints.mkdir()
    (footprints / "IncompleteHeader.kicad_mod").write_text(
        """
        (footprint "IncompleteHeader"
          (pad "1" thru_hole rect
            (at 0 0)
            (size 1.7 1.7)
            (layers "*.Cu" "*.Mask")))
        """,
        encoding="utf-8",
    )
    monkeypatch.setenv("PARDAL_LOCAL_FOOTPRINT_DIRS", str(footprints))

    pads, error = get_footprint_pads("atopile:IncompleteHeader")

    assert pads == []
    assert error == "Unknown footprint: atopile:IncompleteHeader"


def test_pin_header_offsets_are_origin_based_only_for_kicad_library_name():
    legacy_pads, legacy_error = get_footprint_pads("PinHeader_1x03_P2.54mm_Vertical")
    kicad_pads, kicad_error = get_footprint_pads(
        "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
    )

    assert legacy_error is None
    assert kicad_error is None
    assert [pad.position_offset for pad in legacy_pads] == [
        (0.0, -2.54),
        (0.0, 0.0),
        (0.0, 2.54),
    ]
    assert [pad.position_offset for pad in kicad_pads] == [
        (0.0, 0.0),
        (0.0, 2.54),
        (0.0, 5.08),
    ]
