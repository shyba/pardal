from pathlib import Path

from pardal.freerouting_backend import sanitize_dsn


def test_sanitize_dsn_rewrites_first_line_and_strips_chars(tmp_path: Path) -> None:
    raw = tmp_path / "raw.dsn"
    cleaned = tmp_path / "cleaned.dsn"
    raw.write_text(
        "(pcb /tmp/rawΩµΦ.dsn\n"
        "  (parser (host_cad \"KiCad's Pcbnew\"))\n"
        "  (network (net N1µ))\n"
        ")\n",
        encoding="utf-8",
    )

    sanitize_dsn(raw, cleaned, pcb_name="freerouting.dsn")
    out = cleaned.read_text(encoding="utf-8")
    assert out.splitlines()[0] == "(pcb freerouting.dsn"
    assert "Ω" not in out
    assert "µ" not in out
    assert "Φ" not in out


def test_sanitize_dsn_strip_planes(tmp_path: Path) -> None:
    raw = tmp_path / "raw.dsn"
    cleaned = tmp_path / "cleaned.dsn"
    raw.write_text(
        "(pcb /tmp/raw.dsn\n"
        "  (structure\n"
        "    (plane GND\n"
        "      (polygon F.Cu\n"
        "        (polyline (pt 0 0) (pt 1 0) (pt 1 1) (pt 0 1))\n"
        "      )\n"
        "    )\n"
        "    (rule (width 200))\n"
        "  )\n"
        ")\n",
        encoding="utf-8",
    )

    sanitize_dsn(raw, cleaned, pcb_name="freerouting.dsn", strip_planes=True)
    out = cleaned.read_text(encoding="utf-8")
    assert "(plane" not in out
    assert "(rule (width 200))" in out

