#!/usr/bin/env python3
"""Run FreeRouting CLI over the `freerouting/tests` DSN corpus.

Oracle triage tool:
- Runs FreeRouting headless.
- Captures stdout/stderr per fixture.
- Writes output `.ses` and FreeRouting `-drc` JSON when possible.
- Records per-fixture metrics (exit code, runtime, output sizes).

This does not assert parity; it generates data to classify fixtures and fill the
parity checklist.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


@dataclass
class RunResult:
    status: str  # ok | error | timeout | skipped
    reason: Optional[str]
    dsn: str
    rel: str
    group: str
    rules: Optional[str]
    ses_out: str
    drc_out: str
    returncode: int
    runtime_s: float
    stdout_path: str
    stderr_path: str
    ses_bytes: int
    drc_bytes: int


def _find_repo_root(start: Path) -> Path:
    cur = start.resolve()
    while cur != cur.parent:
        if (cur / "freerouting").exists() and (cur / "pardal-pcb").exists():
            return cur
        cur = cur.parent
    raise RuntimeError("Failed to locate workspace root (expected freerouting/ and pardal-pcb/)")


def _group_key(rel: str) -> str:
    if rel.startswith("Issue"):
        head = rel.split("/", 1)[0]
        return head.split("-", 1)[0]
    return "ROOT"


def _peek_bytes(path: Path, n: int = 512) -> bytes:
    try:
        with path.open("rb") as f:
            return f.read(n)
    except OSError:
        return b""


def _is_probably_text_specctra_dsn(path: Path) -> tuple[bool, Optional[str]]:
    """Heuristic filter: FreeRouting CLI only supports Specctra DSN text files.

    The corpus sometimes contains non-DSN files with a .dsn extension (e.g. OLE
    compound documents from EDA tools). Running the oracle on those produces
    noisy failures; skip them deterministically.
    """
    head = _peek_bytes(path, 512)
    if not head:
        return False, "unreadable-or-empty"

    # Reject obvious binary.
    if b"\x00" in head:
        return False, "binary-null-bytes"
    if head.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
        return False, "binary-ole-compound"

    # Interpret as UTF-8 for the *header* check. Use replacement to avoid false
    # negatives when we cut off a multibyte character at the read boundary.
    text = head.decode("utf-8", errors="replace")

    stripped = text.lstrip()
    if not stripped.startswith("("):
        return False, "not-sexpr"

    if not stripped.startswith("(pcb"):
        return True, "non-pcb-sexpr"

    return True, None


def run_one(
    *,
    jar: Path,
    dsn: Path,
    rel: str,
    rules: Optional[Path],
    out_dir: Path,
    seed: int,
    max_passes: int,
    threads: int,
    timeout_s: int,
    log_level: str,
) -> RunResult:
    out_dir.mkdir(parents=True, exist_ok=True)

    stem = dsn.stem
    ses_out = out_dir / f"{stem}.ses"
    drc_out = out_dir / f"{stem}.drc.json"
    stdout_path = out_dir / f"{stem}.stdout.txt"
    stderr_path = out_dir / f"{stem}.stderr.txt"

    ok, skip_reason = _is_probably_text_specctra_dsn(dsn)
    if not ok:
        stdout_path.write_text("")
        stderr_path.write_text(f"SKIPPED: {skip_reason}\n")
        return RunResult(
            status="skipped",
            reason=skip_reason,
            dsn=str(dsn),
            rel=rel,
            group=_group_key(rel),
            rules=str(rules) if rules is not None else None,
            ses_out=str(ses_out),
            drc_out=str(drc_out),
            returncode=0,
            runtime_s=0.0,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            ses_bytes=0,
            drc_bytes=0,
        )

    cmd = [
        "java",
        "-jar",
        str(jar),
        "--gui.enabled=false",
        "-de",
        str(dsn),
        "-do",
        str(ses_out),
        "-drc",
        str(drc_out),
        "-random_seed",
        str(seed),
        "-mp",
        str(max_passes),
        "-mt",
        str(threads),
        "-ll",
        str(log_level),
    ]
    if rules is not None:
        cmd.extend(["-dr", str(rules)])

    t0 = time.time()
    rc = 0
    with stdout_path.open("wb") as out_f, stderr_path.open("wb") as err_f:
        try:
            proc = subprocess.run(
                cmd,
                stdout=out_f,
                stderr=err_f,
                timeout=timeout_s,
                check=False,
            )
            rc = int(proc.returncode)
        except subprocess.TimeoutExpired:
            rc = 124
    dt = time.time() - t0

    if rc == 0:
        status = "ok"
        reason = None
    elif rc == 124:
        status = "timeout"
        reason = f"timeout>{timeout_s}s"
    else:
        status = "error"
        reason = None

    return RunResult(
        status=status,
        reason=skip_reason if skip_reason else reason,
        dsn=str(dsn),
        rel=rel,
        group=_group_key(rel),
        rules=str(rules) if rules is not None else None,
        ses_out=str(ses_out),
        drc_out=str(drc_out),
        returncode=rc,
        runtime_s=float(dt),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        ses_bytes=ses_out.stat().st_size if ses_out.exists() else 0,
        drc_bytes=drc_out.stat().st_size if drc_out.exists() else 0,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jar", type=Path, default=None)
    ap.add_argument("--tests", type=Path, default=None, help="Path to freerouting/tests")
    ap.add_argument("--out", type=Path, default=None, help="Output directory")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-passes", type=int, default=20)
    ap.add_argument("--threads", type=int, default=0)
    ap.add_argument("--timeout-s", type=int, default=180)
    ap.add_argument("--log-level", type=str, default="INFO")
    ap.add_argument("--limit", type=int, default=0, help="Limit number of DSNs (0=all)")
    args = ap.parse_args()

    root = _find_repo_root(Path.cwd())
    jar = args.jar or (root / "freerouting" / "build" / "libs" / "freerouting-cli.jar")
    if not jar.exists():
        jar = root / "freerouting" / "build" / "libs" / "freerouting.jar"
    tests = args.tests or (root / "freerouting" / "tests")
    out = args.out or (root / "pardal-pcb" / "parity_out" / "freerouting_oracle_sweep")

    if not jar.exists():
        raise SystemExit(f"FreeRouting jar not found: {jar}")
    if not tests.exists():
        raise SystemExit(f"FreeRouting tests directory not found: {tests}")

    dsns = sorted(tests.rglob("*.dsn"))
    if args.limit and args.limit > 0:
        dsns = dsns[: args.limit]

    out.mkdir(parents=True, exist_ok=True)

    results: list[RunResult] = []
    for i, dsn in enumerate(dsns, start=1):
        rel = str(dsn.relative_to(tests))
        group = _group_key(rel)
        case_dir = out / group / Path(rel).parent

        rules = None
        sibling_rules = dsn.with_suffix(".rules")
        if sibling_rules.exists():
            rules = sibling_rules

        print(f"[{i}/{len(dsns)}] {rel} (group={group})")
        res = run_one(
            jar=jar,
            dsn=dsn,
            rel=rel,
            rules=rules,
            out_dir=case_dir,
            seed=args.seed,
            max_passes=args.max_passes,
            threads=args.threads,
            timeout_s=args.timeout_s,
            log_level=args.log_level,
        )
        results.append(res)

    report_path = out / "oracle_sweep_results.json"
    report_path.write_text(json.dumps([asdict(r) for r in results], indent=2))
    print(f"wrote {report_path}")

    ok = [r for r in results if r.status == "ok"]
    skipped = [r for r in results if r.status == "skipped"]
    bad = [r for r in results if r.status in {"error", "timeout"}]
    print(f"total={len(results)} ok={len(ok)} bad={len(bad)} skipped={len(skipped)}")
    return 0 if not bad else 2


if __name__ == "__main__":
    raise SystemExit(main())
