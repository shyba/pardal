import json
from pathlib import Path


def test_convert_dsn_to_problem_smoke(tmp_path: Path):
    from pcb_tool.tools.convert_dsn_to_problem import convert_dsn_to_problem

    # repo layout: ee/pardal-pcb and ee/freerouting
    ee_root = Path(__file__).resolve().parents[2]
    dsn = ee_root / "freerouting" / "tests" / "Issue269-min_fr_test" / "min_fr_test_no_quotes.dsn"
    assert dsn.exists()

    out = tmp_path / "problem.json"
    convert_dsn_to_problem(dsn_path=dsn, out_json=out, net_limit=5)
    data = json.loads(out.read_text())

    assert data["format"] == "dsn_mvp"
    assert "layers" in data and len(data["layers"]) >= 2
    assert "nets" in data and 1 <= len(data["nets"]) <= 5
    for n in data["nets"]:
        assert "start" in n and "goal" in n
        assert "net" in n and "net_id" in n
        assert n["start"]["layer"] == 0
        assert n["goal"]["layer"] == 0


def test_convert_dsn_keepout_smoke(tmp_path: Path):
    from pcb_tool.tools.convert_dsn_to_problem import convert_dsn_to_problem

    ee_root = Path(__file__).resolve().parents[2]
    dsn = ee_root / "freerouting" / "tests" / "Issue229-display-8-digit-hc595.dsn"
    assert dsn.exists()

    out = tmp_path / "problem.json"
    convert_dsn_to_problem(dsn_path=dsn, out_json=out, net_limit=5)
    data = json.loads(out.read_text())
    assert "circles" in data
    assert isinstance(data["circles"], list)
    assert "polygons" in data
    assert isinstance(data["polygons"], list)
