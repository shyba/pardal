#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_FEATURE_STATUSES = {"pending", "done", "exhausted", "blocked"}
ALLOWED_TEST_STATUSES = {"pending", "done", "skipped"}
ALLOWED_ARTIFACT_STATUSES = {"done", "absent"}
ALLOWED_KINDS = {"align", "reduce", "guard_applicable", "guard_fast"}
REPAIRABLE_FAILURES = {"build_failure", "trace_missing", "artifact_invalid", "runner_connectivity", "applicable_regression", "fast_regression"}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _feature_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(f["id"]): f for f in doc.get("features", [])}


def _artifact_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(a["id"]): a for a in doc.get("artifacts", [])}


def _test_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(t["id"]): t for t in doc.get("tests", [])}


def _append_note(existing: str, note: str | None) -> str:
    if note is None:
        return existing
    note = note.strip()
    if not note:
        return existing
    existing = existing.rstrip()
    return note if not existing else existing + " " + note


def _artifact_by_capability(doc: dict[str, Any], capability: str) -> dict[str, Any] | None:
    for art in doc.get("artifacts", []):
        if str(art.get("capability", "")) == capability:
            return art
    return None


def _done_capabilities(doc: dict[str, Any]) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for art in doc.get("artifacts", []):
        if str(art.get("status", "")) == "done":
            cap = str(art.get("capability", "")).strip()
            if cap:
                out[cap] = True
    return out


def _feature_ready(feature: dict[str, Any], caps: dict[str, bool]) -> bool:
    if str(feature.get("status", "pending")) != "pending":
        return False
    for cap in feature.get("requires_all_capabilities", []) or []:
        if not caps.get(str(cap), False):
            return False
    any_sets = feature.get("requires_any_capability_sets", []) or []
    if any_sets:
        if not any(all(caps.get(str(cap), False) for cap in capset or []) for capset in any_sets):
            return False
    return True


def _goal_met(doc: dict[str, Any]) -> bool:
    caps = _done_capabilities(doc)
    return all(caps.get(str(cap), False) for cap in doc.get("goal", {}).get("requires_all_capabilities", []) or [])


def _next_repair_action(doc: dict[str, Any]) -> dict[str, Any] | None:
    blocked = []
    for feat in doc.get("features", []):
        if str(feat.get("status", "")) != "blocked":
            continue
        failure = str(feat.get("last_failure_class", "")).strip()
        if failure not in REPAIRABLE_FAILURES:
            continue
        blocked.append(feat)
    blocked.sort(key=lambda f: int(f.get("priority", 1_000_000)))
    if not blocked:
        return None
    feat = blocked[0]
    failure = str(feat.get("last_failure_class", ""))
    repair_catalog = doc.get("repair_catalog", {}) or {}
    repair = repair_catalog.get(failure)
    if not isinstance(repair, dict):
        return None
    return {
        "action_type": str(repair.get("task_type", "repair_build")),
        "feature": feat,
        "repair": repair,
    }


def _next_retry_feature_action(doc: dict[str, Any]) -> dict[str, Any] | None:
    caps = _done_capabilities(doc)
    retryable = []
    for feat in doc.get("features", []):
        if str(feat.get("status", "")) != "exhausted":
            continue
        kind = str(feat.get("kind", ""))
        if kind not in {"align", "reduce"}:
            continue
        if not _feature_ready({**feat, "status": "pending"}, caps):
            continue
        retryable.append(feat)
    retryable.sort(key=lambda f: int(f.get("priority", 1_000_000)))
    if not retryable:
        return None
    feat = retryable[0]
    return {
        "action_type": str(feat.get("kind", "align")),
        "feature": feat,
        "retry": True,
    }


def _next_feature_action(doc: dict[str, Any]) -> dict[str, Any] | None:
    caps = _done_capabilities(doc)
    pending = [f for f in doc.get("features", []) if _feature_ready(f, caps)]
    pending.sort(key=lambda f: int(f.get("priority", 1_000_000)))
    if not pending:
        return None
    feat = pending[0]
    return {
        "action_type": str(feat.get("kind", "align")),
        "feature": feat,
    }


def _summary(doc: dict[str, Any]) -> dict[str, Any]:
    caps = _done_capabilities(doc)
    ready_features = [str(f["id"]) for f in doc.get("features", []) if _feature_ready(f, caps)]
    counts = Counter(str(f.get("status", "pending")) for f in doc.get("features", []))
    next_action = _next_repair_action(doc) or _next_feature_action(doc) or _next_retry_feature_action(doc)
    return {
        "pending_count": counts.get("pending", 0),
        "done_count": counts.get("done", 0),
        "blocked_count": counts.get("blocked", 0),
        "exhausted_count": counts.get("exhausted", 0),
        "ready_count": max(len(ready_features), 1 if next_action is not None else 0),
        "ready_features": ready_features,
        "next_action": None if next_action is None else {
            "action_type": next_action["action_type"],
            "feature_id": next_action["feature"]["id"],
        },
        "goal_met": _goal_met(doc),
    }


def _validate(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc.get("schema_version"), int):
        errors.append("schema_version must be an int")

    seen_artifact_ids: set[str] = set()
    seen_caps: set[str] = set()
    for art in doc.get("artifacts", []):
        art_id = str(art.get("id", "")).strip()
        cap = str(art.get("capability", "")).strip()
        if not art_id:
            errors.append("artifact missing id")
            continue
        if art_id in seen_artifact_ids:
            errors.append(f"duplicate artifact id: {art_id}")
        seen_artifact_ids.add(art_id)
        if not cap:
            errors.append(f"artifact {art_id} missing capability")
        elif cap in seen_caps:
            errors.append(f"duplicate artifact capability: {cap}")
        seen_caps.add(cap)
        if str(art.get("status", "absent")) not in ALLOWED_ARTIFACT_STATUSES:
            errors.append(f"artifact {art_id} invalid status")

    feature_ids: set[str] = set()
    for feat in doc.get("features", []):
        fid = str(feat.get("id", "")).strip()
        if not fid:
            errors.append("feature missing id")
            continue
        if fid in feature_ids:
            errors.append(f"duplicate feature id: {fid}")
        feature_ids.add(fid)
        if str(feat.get("status", "pending")) not in ALLOWED_FEATURE_STATUSES:
            errors.append(f"feature {fid} invalid status")
        if str(feat.get("kind", "")) not in ALLOWED_KINDS:
            errors.append(f"feature {fid} invalid kind")
        if not isinstance(feat.get("attempts_used", 0), int) or not isinstance(feat.get("max_attempts", 0), int):
            errors.append(f"feature {fid} attempts fields must be ints")
        if not isinstance(feat.get("repair_attempts_used", 0), int) or not isinstance(feat.get("max_repair_attempts", 0), int):
            errors.append(f"feature {fid} repair_attempts fields must be ints")
        kind = str(feat.get("kind", ""))
        if kind in {"align", "reduce"}:
            if not str(feat.get("reproduce_cmd", "")).strip():
                errors.append(f"feature {fid} missing reproduce_cmd")
            if not str(feat.get("artifact_summary_json", "")).strip():
                errors.append(f"feature {fid} missing artifact_summary_json")
            outputs = feat.get("outputs", []) or []
            if not isinstance(outputs, list) or len(outputs) == 0:
                errors.append(f"feature {fid} missing outputs")
        if kind in {"guard_applicable", "guard_fast"}:
            guards = feat.get("guard_cmds", []) or []
            if not isinstance(guards, list) or len(guards) == 0:
                errors.append(f"feature {fid} missing guard_cmds")

    test_ids: set[str] = set()
    for test in doc.get("tests", []):
        tid = str(test.get("id", "")).strip()
        if not tid:
            errors.append("test missing id")
            continue
        if tid in test_ids:
            errors.append(f"duplicate test id: {tid}")
        test_ids.add(tid)
        if str(test.get("status", "pending")) not in ALLOWED_TEST_STATUSES:
            errors.append(f"test {tid} invalid status")
    return errors


def _set_artifact(doc: dict[str, Any], artifact_id: str | None, capability: str | None, status: str, path: str | None, notes: str | None) -> None:
    art = None
    if artifact_id:
        art = _artifact_map(doc).get(artifact_id)
    if art is None and capability:
        art = _artifact_by_capability(doc, capability)
    if art is None:
        art = {"id": artifact_id or capability, "capability": capability or artifact_id, "status": "absent", "path": "", "notes": ""}
        doc.setdefault("artifacts", []).append(art)
    art["status"] = status
    if path is not None:
        art["path"] = path
        if art.get("id") == "decision_compare_current" and status == "done":
            doc.setdefault("planner_state", {})["latest_compare_artifact"] = path
    if notes is not None:
        art["notes"] = _append_note(str(art.get("notes", "")), notes)


def _mark_feature(doc: dict[str, Any], feature_id: str, status: str, notes_append: str | None, increment_attempts: bool, failure_class: str | None, clear_failure: bool, increment_repair_attempts: bool) -> None:
    feat = _feature_map(doc)[feature_id]
    feat["status"] = status
    if increment_attempts:
        feat["attempts_used"] = int(feat.get("attempts_used", 0)) + 1
    if increment_repair_attempts:
        feat["repair_attempts_used"] = int(feat.get("repair_attempts_used", 0)) + 1
    if clear_failure:
        feat["last_failure_class"] = ""
    elif failure_class is not None:
        feat["last_failure_class"] = failure_class
    if notes_append is not None:
        feat["notes"] = _append_note(str(feat.get("notes", "")), notes_append)
    if status == "done":
        artifact_summary = str(feat.get("artifact_summary_json", "")).strip()
        for cap in feat.get("success_capabilities", []) or []:
            _set_artifact(
                doc,
                artifact_id=None,
                capability=str(cap),
                status="done",
                path=artifact_summary if artifact_summary else None,
                notes=f"Set by feature {feature_id} completion.",
            )
        if str(feat.get("kind", "")) == "align" and artifact_summary:
            _set_artifact(
                doc,
                artifact_id="decision_compare_current",
                capability="cap.compare.current",
                status="done",
                path=artifact_summary,
                notes=f"Refreshed by feature {feature_id}.",
            )


def _mark_test(doc: dict[str, Any], test_id: str, status: str, notes_append: str | None) -> None:
    t = _test_map(doc)[test_id]
    t["status"] = status
    if notes_append is not None:
        t["notes"] = _append_note(str(t.get("notes", "")), notes_append)


def _append_history(doc: dict[str, Any], text: str) -> None:
    if not text.strip():
        return
    doc.setdefault("history", []).append(text.strip())


def _set_current_best(
    doc: dict[str, Any],
    *,
    failed_nets: int,
    unconnected: int,
    violations: int,
    source_artifact: str,
    notes: str | None,
) -> None:
    best = doc.setdefault("current_best", {})
    best["failed_nets"] = int(failed_nets)
    best["unconnected"] = int(unconnected)
    best["violations"] = int(violations)
    best["source_artifact"] = str(source_artifact)
    if notes is not None:
        best["notes"] = _append_note(str(best.get("notes", "")), notes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--worklist", type=Path, required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_summary = sub.add_parser("summary")
    p_summary.add_argument("--format", choices=["json"], default="json")
    p_next = sub.add_parser("next-action")
    p_next.add_argument("--format", choices=["json", "story", "id"], default="json")
    sub.add_parser("validate")
    sub.add_parser("goal-met")

    p_markf = sub.add_parser("mark-feature")
    p_markf.add_argument("--feature-id", required=True)
    p_markf.add_argument("--status", required=True, choices=sorted(ALLOWED_FEATURE_STATUSES))
    p_markf.add_argument("--notes-append", default=None)
    p_markf.add_argument("--increment-attempts", action="store_true")
    p_markf.add_argument("--failure-class", default=None)
    p_markf.add_argument("--clear-failure", action="store_true")
    p_markf.add_argument("--increment-repair-attempts", action="store_true")

    p_markt = sub.add_parser("mark-test")
    p_markt.add_argument("--test-id", required=True)
    p_markt.add_argument("--status", required=True, choices=sorted(ALLOWED_TEST_STATUSES))
    p_markt.add_argument("--notes-append", default=None)

    p_art = sub.add_parser("set-artifact")
    p_art.add_argument("--artifact-id", default=None)
    p_art.add_argument("--capability", default=None)
    p_art.add_argument("--status", required=True, choices=sorted(ALLOWED_ARTIFACT_STATUSES))
    p_art.add_argument("--path", default=None)
    p_art.add_argument("--notes", default=None)

    p_hist = sub.add_parser("append-history")
    p_hist.add_argument("--text", required=True)

    p_best = sub.add_parser("set-current-best")
    p_best.add_argument("--failed-nets", type=int, required=True)
    p_best.add_argument("--unconnected", type=int, required=True)
    p_best.add_argument("--violations", type=int, required=True)
    p_best.add_argument("--source-artifact", required=True)
    p_best.add_argument("--notes", default=None)

    args = ap.parse_args(argv)
    worklist = args.worklist.resolve()
    doc = _load_json(worklist)

    if args.cmd == "validate":
        errors = _validate(doc)
        if errors:
            for e in errors:
                print(e, file=sys.stderr)
            return 1
        return 0

    if args.cmd == "summary":
        print(json.dumps(_summary(doc), indent=2, sort_keys=True))
        return 0

    if args.cmd == "goal-met":
        print("true" if _goal_met(doc) else "false")
        return 0

    if args.cmd == "next-action":
        action = _next_repair_action(doc) or _next_feature_action(doc) or _next_retry_feature_action(doc)
        if action is None:
            return 1
        if args.format == "id":
            print(action["feature"]["id"])
        elif args.format == "story":
            feature = action["feature"]
            title = str(feature.get("title", "")).strip()
            if not title:
                target = str(feature.get("target_net", "")).strip()
                kind = str(feature.get("kind", action["action_type"])).strip()
                title = f"{kind} {target}".strip()
            retry_suffix = " retry" if action.get("retry") else ""
            print(f"{feature['id']}: {title} [{action['action_type']}{retry_suffix}]")
        else:
            print(json.dumps(action, indent=2, sort_keys=True))
        return 0

    if args.cmd == "mark-feature":
        _mark_feature(doc, args.feature_id, args.status, args.notes_append, bool(args.increment_attempts), args.failure_class, bool(args.clear_failure), bool(args.increment_repair_attempts))
    elif args.cmd == "mark-test":
        _mark_test(doc, args.test_id, args.status, args.notes_append)
    elif args.cmd == "set-artifact":
        _set_artifact(doc, args.artifact_id, args.capability, args.status, args.path, args.notes)
    elif args.cmd == "append-history":
        _append_history(doc, args.text)
    elif args.cmd == "set-current-best":
        _set_current_best(
            doc,
            failed_nets=args.failed_nets,
            unconnected=args.unconnected,
            violations=args.violations,
            source_artifact=args.source_artifact,
            notes=args.notes,
        )
    else:
        raise SystemExit(f"unsupported command: {args.cmd}")

    errors = _validate(doc)
    if errors:
        raise SystemExit("; ".join(errors))
    _write_json(worklist, doc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
