import json
from pathlib import Path

from pardal.tools.routes_json_to_ses import routes_to_ses


def test_routes_json_to_ses_writes_session(tmp_path: Path):
    dsn = tmp_path / "b.dsn"
    dsn.write_text(
        "(pcb test\n"
        "  (parser (string_quote \") (space_in_quoted_tokens on))\n"
        "  (resolution um 10)\n"
        "  (unit um)\n"
        ")\n",
        encoding="utf-8",
    )
    routes = tmp_path / "routes.json"
    routes.write_text(
        json.dumps(
            {
                "tracks": [
                    {
                        "net": "N1",
                        "layer": "F.Cu",
                        "width_mm": 0.2,
                        "start_mm": [1.0, 2.0],
                        "end_mm": [3.0, 4.0],
                    }
                ],
                "vias": [],
                "failed_nets": [],
            }
        ),
        encoding="utf-8",
    )
    out = tmp_path / "out.ses"
    routes_to_ses(dsn=dsn, routes_json=routes, out_ses=out, host="pardal-test")
    txt = out.read_text(encoding="utf-8")
    assert "(session" in txt
    assert "(host_cad \"KiCad's Pcbnew\")" in txt
    assert "(net N1" in txt
