#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_TASK_STATUSES = {"pending", "done", "exhausted", "blocked"}
ALLOWED_KINDS = {"algorithm", "reduce"}
REPAIR_MAP = {
    "build_failure": "repair_build",
    "trace_missing": "repair_trace",
    "artifact_invalid": "repair_worklist",
    "runner_connectivity": "repair_trace",
}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8", errors="replace"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _task_map(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(t.get("id", "")): t for t in doc.get("tasks", []) if isinstance(t, dict)}


def _append_note(existing: str, note: str | None) -> str:
    if note is None:
        return existing
    note = note.strip()
    if not note:
        return existing
    existing = existing.rstrip()
    return note if not existing else existing + " " + note


def _goal_met(doc: dict[str, Any]) -> bool:
    goal = doc.get("goal", {}) or {}
    cur = doc.get("current_best", {}) or {}
    try:
        return (
            int(cur.get("failed_nets", 10**9)) <= int(goal.get("target_failed_nets", 0))
            and int(cur.get("unconnected", 10**9)) <= int(goal.get("target_unconnected", 0))
            and int(cur.get("violations", 10**9)) <= int(goal.get("target_violations", 0))
        )
    except Exception:
        return False


def _next_repair_action(doc: dict[str, Any]) -> dict[str, Any] | None:
    blocked: list[dict[str, Any]] = []
    for task in doc.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "")) != "blocked":
            continue
        failure = str(task.get("failure_class", "")).strip()
        if failure not in REPAIR_MAP:
            continue
        blocked.append(task)
    blocked.sort(key=lambda t: int(t.get("priority", 1_000_000)))
    if not blocked:
        return None
    t = blocked[0]
    failure = str(t.get("failure_class", "")).strip()
    return {
        "action_type": REPAIR_MAP[failure],
        "task": t,
        "failure_class": failure,
    }


def _next_task_action(doc: dict[str, Any]) -> dict[str, Any] | None:
    pending: list[dict[str, Any]] = []
    for task in doc.get("tasks", []) or []:
        if not isinstance(task, dict):
            continue
        if str(task.get("status", "pending")) != "pending":
            continue
        pending.append(task)
    pending.sort(key=lambda t: int(t.get("priority", 1_000_000)))
    if not pending:
        return None
    t = pending[0]
    kind = str(t.get("kind", "algorithm"))
    if kind not in ALLOWED_KINDS:
        kind = "algorithm"
    return {"action_type": kind, "task": t}


def _summary(doc: dict[str, Any]) -> dict[str, Any]:
    counts = Counter(str(t.get("status", "pending")) for t in doc.get("tasks", []) if isinstance(t, dict))
    next_action = _next_repair_action(doc) or _next_task_action(doc)
    ready_tasks = [
        str(t.get("id", ""))
        for t in doc.get("tasks", [])
        if isinstance(t, dict) and str(t.get("status", "pending")) == "pending"
    ]
    return {
        "pending_count": counts.get("pending", 0),
        "done_count": counts.get("done", 0),
        "blocked_count": counts.get("blocked", 0),
        "exhausted_count": counts.get("exhausted", 0),
        "ready_count": max(len(ready_tasks), 1 if next_action is not None else 0),
        "ready_tasks": ready_tasks,
        "next_action": None
        if next_action is None
        else {
            "action_type": next_action["action_type"],
            "task_id": str(next_action["task"].get("id", "")),
        },
        "goal_met": _goal_met(doc),
    }


def _validate(doc: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if int(doc.get("schema_version", -1)) != 1:
        errors.append("schema_version must be 1")

    goal = doc.get("goal", {})
    for k in ("fixture", "target_failed_nets", "target_unconnected", "target_violations"):
        if k not in goal:
            errors.append(f"goal missing {k}")

    cur = doc.get("current_best", {})
    for k in ("failed_nets", "unconnected", "violations"):
        if k not in cur:
            errors.append(f"current_best missing {k}")

    seen_ids: set[str] = set()
    for task in doc.get("tasks", []) or []:
        if not isinstance(task, dict):
            errors.append("task entry must be object")
            continue
        tid = str(task.get("id", "")).strip()
        if not tid:
            errors.append("task missing id")
            continue
        if tid in seen_ids:
            errors.append(f"duplicate task id: {tid}")
        seen_ids.add(tid)

        status = str(task.get("status", "pending"))
        if status not in ALLOWED_TASK_STATUSES:
            errors.append(f"task {tid} invalid status")
        kind = str(task.get("kind", "algorithm"))
        if kind not in ALLOWED_KINDS:
            errors.append(f"task {tid} invalid kind")

        for k in ("priority", "attempts_used", "max_attempts"):
            if not isinstance(task.get(k, 0), int):
                errors.append(f"task {tid} {k} must be int")

        target_nets = task.get("target_nets", [])
        if not isinstance(target_nets, list):
            errors.append(f"task {tid} target_nets must be list")

        success_criteria = task.get("success_criteria", [])
        if not isinstance(success_criteria, list) or len(success_criteria) == 0:
            errors.append(f"task {tid} success_criteria must be non-empty list")

    return errors


def cmd_validate(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    errors = _validate(doc)
    if errors:
        for err in errors:
            print(err)
        return 1
    return 0


def cmd_summary(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    print(json.dumps(_summary(doc), indent=2, sort_keys=True))
    return 0


def cmd_goal_met(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    print("true" if _goal_met(doc) else "false")
    return 0


def cmd_next_action(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    action = _next_repair_action(doc) or _next_task_action(doc)
    if args.format == "json":
        print(json.dumps(action if action is not None else None, indent=2, sort_keys=True))
    else:
        if action is None:
            print("none")
        else:
            t = action["task"]
            tid = str(t.get("id", ""))
            kind = str(action.get("action_type", ""))
            fam = str(t.get("algorithm_family", "")).strip()
            net_hint = ",".join([str(x) for x in (t.get("target_nets") or [])[:3]])
            suffix = f" [{fam}]" if fam else ""
            print(f"{tid}: {kind}{suffix} {net_hint}".strip())
    return 0


def cmd_mark_task(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    task = _task_map(doc).get(args.task_id)
    if task is None:
        raise SystemExit(f"task not found: {args.task_id}")
    task["status"] = args.status
    if args.increment_attempts:
        task["attempts_used"] = int(task.get("attempts_used", 0)) + 1
    if args.failure_class is not None:
        task["failure_class"] = args.failure_class
    if args.clear_failure:
        task["failure_class"] = ""
    task["notes"] = _append_note(str(task.get("notes", "")), args.notes_append)
    _write_json(args.worklist, doc)
    return 0


def cmd_set_current_best(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    cur = doc.setdefault("current_best", {})
    cur["failed_nets"] = int(args.failed_nets)
    cur["unconnected"] = int(args.unconnected)
    cur["violations"] = int(args.violations)
    cur["source_artifact"] = args.source_artifact
    cur["notes"] = _append_note(str(cur.get("notes", "")), args.notes)
    _write_json(args.worklist, doc)
    return 0


def cmd_append_history(args: argparse.Namespace) -> int:
    doc = _load_json(args.worklist)
    hist = doc.setdefault("history", [])
    if not isinstance(hist, list):
        hist = []
        doc["history"] = hist
    hist.append(args.text)
    _write_json(args.worklist, doc)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Simple algorithm worklist ops")
    p.add_argument("--worklist", type=Path, required=True)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("validate")
    sp.set_defaults(func=cmd_validate)

    sp = sub.add_parser("summary")
    sp.set_defaults(func=cmd_summary)

    sp = sub.add_parser("goal-met")
    sp.set_defaults(func=cmd_goal_met)

    sp = sub.add_parser("next-action")
    sp.add_argument("--format", choices=["json", "story"], default="json")
    sp.set_defaults(func=cmd_next_action)

    sp = sub.add_parser("mark-task")
    sp.add_argument("--task-id", required=True)
    sp.add_argument("--status", choices=sorted(ALLOWED_TASK_STATUSES), required=True)
    sp.add_argument("--notes-append", default="")
    sp.add_argument("--increment-attempts", action="store_true")
    sp.add_argument("--failure-class", default=None)
    sp.add_argument("--clear-failure", action="store_true")
    sp.set_defaults(func=cmd_mark_task)

    sp = sub.add_parser("set-current-best")
    sp.add_argument("--failed-nets", type=int, required=True)
    sp.add_argument("--unconnected", type=int, required=True)
    sp.add_argument("--violations", type=int, required=True)
    sp.add_argument("--source-artifact", required=True)
    sp.add_argument("--notes", default="")
    sp.set_defaults(func=cmd_set_current_best)

    sp = sub.add_parser("append-history")
    sp.add_argument("--text", required=True)
    sp.set_defaults(func=cmd_append_history)

    return p


def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
