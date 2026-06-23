from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
RAW_DIR = BASE_DIR / "raw_data"
PROCESSED_DIR = BASE_DIR / "processed_data"
LIBRARY_DIR = BASE_DIR / "library"
DASHBOARD_DATA_PATH = BASE_DIR / "dashboard" / "dashboard_data.json"
WORKFLOW_DIR = BASE_DIR / "agent_workspace"
STATE_PATH = WORKFLOW_DIR / "quill_session_state.json"
BRIEF_PATH = WORKFLOW_DIR / "quill_session_brief.md"
DAILY_MEMO_PATH = WORKFLOW_DIR / "daily_memo.md"


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def file_stat(path: Path) -> dict[str, Any]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": str(path), "missing": True}
    return {
        "path": str(path.resolve().relative_to(BASE_DIR.resolve())),
        "size": stat.st_size,
        "mtime": int(stat.st_mtime),
    }


def scan_tree(root: Path, suffixes: set[str]) -> dict[str, Any]:
    if not root.exists():
        return {"count": 0, "max_mtime": 0, "files": []}
    records = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if suffixes and path.suffix.lower() not in suffixes:
            continue
        records.append(file_stat(path))
    max_mtime = max((item.get("mtime", 0) for item in records), default=0)
    return {"count": len(records), "max_mtime": max_mtime, "files": sorted(records, key=lambda item: item["path"])}


def compact_tree(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"count": 0, "max_mtime": 0}
    count = 0
    max_mtime = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        count += 1
        max_mtime = max(max_mtime, int(stat.st_mtime))
    return {"count": count, "max_mtime": max_mtime}


def fingerprint(payload: Any) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def collect_state() -> dict[str, Any]:
    library_inputs = []
    for pattern in ("*.xlsx", "*.pptx", "*.tex", "*.pdf", "*.bib", "zotero_*.json"):
        library_inputs.extend(LIBRARY_DIR.glob(pattern))
    library_records = [file_stat(path) for path in sorted(set(library_inputs))]
    state = {
        "raw": scan_tree(RAW_DIR, {".tif", ".tiff"}),
        "processed": compact_tree(PROCESSED_DIR),
        "library": {
            "count": len(library_records),
            "max_mtime": max((item.get("mtime", 0) for item in library_records), default=0),
            "files": library_records,
        },
        "manuscript": scan_tree(LIBRARY_DIR / "manuscript", {".tex", ".md", ".txt", ".pdf"}),
        "dashboard": file_stat(DASHBOARD_DATA_PATH),
    }
    state["fingerprint"] = fingerprint(state)
    return state


def diff_state(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    if not previous:
        return ["first_project_session"]
    events = []
    for key in ("raw", "processed", "library", "manuscript"):
        before = previous.get("state", {}).get(key, {})
        after = current.get(key, {})
        if before.get("count") != after.get("count") or before.get("max_mtime") != after.get("max_mtime"):
            events.append(f"{key}_changed")
    if previous.get("state", {}).get("dashboard", {}).get("mtime") != current.get("dashboard", {}).get("mtime"):
        events.append("dashboard_changed")
    if previous.get("state", {}).get("fingerprint") == current.get("fingerprint") and not events:
        return []
    return events


def run_step(command: list[str], timeout: int) -> dict[str, Any]:
    started = datetime.now()
    result = subprocess.run(
        command,
        cwd=str(BASE_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": result.returncode,
        "seconds": round((datetime.now() - started).total_seconds(), 2),
        "stdout": (result.stdout or "").strip()[-1200:],
        "stderr": (result.stderr or "").strip()[-1200:],
    }


def build_project_snapshot() -> dict[str, Any]:
    dashboard = load_json(DASHBOARD_DATA_PATH, {})
    zotero = load_json(LIBRARY_DIR / "zotero_digest.json", {})
    summary = dashboard.get("summary", {}) if isinstance(dashboard, dict) else {}
    zsummary = zotero.get("summary", {}) if isinstance(zotero, dict) else {}
    return {
        "cases": summary.get("case_count"),
        "processed": summary.get("processed_count"),
        "runs": summary.get("run_count"),
        "top_case": summary.get("top_case"),
        "zotero_provider": zotero.get("provider"),
        "zotero_unique": zsummary.get("unique_entry_count"),
        "zotero_recent": zsummary.get("recent_2020_plus_count"),
        "zotero_collections": zotero.get("collections", {}).get("count") if isinstance(zotero.get("collections"), dict) else None,
    }


def append_daily_memo(line: str) -> None:
    DAILY_MEMO_PATH.parent.mkdir(parents=True, exist_ok=True)
    existing = DAILY_MEMO_PATH.read_text(encoding="utf-8", errors="ignore") if DAILY_MEMO_PATH.exists() else ""
    if line in existing:
        return
    with DAILY_MEMO_PATH.open("a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(line + "\n")


def write_brief(events: list[str], actions: list[dict[str, Any]], snapshot: dict[str, Any], skipped_deep: bool) -> None:
    now = datetime.now().isoformat(timespec="seconds")
    event_text = ", ".join(events) if events else "no material project change"
    successful = [item for item in actions if item.get("returncode") == 0]
    failed = [item for item in actions if item.get("returncode") != 0]
    next_step = (
        "无需深度例会；总控台已刷新，可直接继续当前问题。"
        if skipped_deep
        else "建议查看总控台：若出现低分 Case、新 Zotero 文献或论文进度变化，再请求 Franklin/Eureka/Quill 深度复盘。"
    )
    lines = [
        "# Quill Session Refresh",
        "",
        f"- 时间：{now}",
        f"- 触发事件：{event_text}",
        f"- 本次深度刷新：成功 {len(successful)} 项，失败 {len(failed)} 项。",
        f"- 当前数据：{snapshot.get('cases', '-')} Cases，{snapshot.get('processed', '-')} 已处理，{snapshot.get('runs', '-')} 个处理版本。",
        f"- 当前最高分 Case：{snapshot.get('top_case') or '-'}。",
        f"- Zotero：{snapshot.get('zotero_provider') or '-'}，{snapshot.get('zotero_unique') or '-'} 条去重，{snapshot.get('zotero_recent') or '-'} 条 2020+，{snapshot.get('zotero_collections') or '-'} 个分类。",
        f"- Quill 判断：{next_step}",
    ]
    if failed:
        lines.extend(["", "## 需要注意"])
        for item in failed:
            lines.append(f"- `{item['command']}` failed: {item.get('stderr') or item.get('stdout') or item.get('returncode')}")
    BRIEF_PATH.parent.mkdir(parents=True, exist_ok=True)
    BRIEF_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def refresh(force: bool = False, skip_zotero: bool = False) -> dict[str, Any]:
    previous = load_json(STATE_PATH, {})
    before = collect_state()
    events = diff_state(previous, before)
    actions: list[dict[str, Any]] = []
    should_refresh = force or bool(events) or not DASHBOARD_DATA_PATH.exists()

    if should_refresh and not skip_zotero:
        actions.append(run_step([sys.executable, "zotero_plugin_bridge.py"], timeout=60))
    if should_refresh:
        actions.append(run_step([sys.executable, "zotero_importer.py"], timeout=30))
        actions.append(run_step([sys.executable, "dashboard_builder.py"], timeout=45))

    snapshot = build_project_snapshot()
    skipped_deep = not force and not events
    write_brief(events, actions, snapshot, skipped_deep)
    memo_line = (
        f"- {datetime.now().date().isoformat()}：Quill Session Refresh 已运行；"
        f"触发={', '.join(events) if events else '无实质变化'}；"
        f"当前 {snapshot.get('cases', '-')} Cases / {snapshot.get('processed', '-')} 已处理 / Zotero {snapshot.get('zotero_unique', '-')} 条。"
    )
    append_daily_memo(memo_line)
    actions.append(run_step([sys.executable, "dashboard_builder.py"], timeout=45))
    after = collect_state()
    write_json(
        STATE_PATH,
        {
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "events": events,
            "actions": actions,
            "snapshot": snapshot,
            "state": after,
        },
    )
    return {"events": events, "actions": actions, "snapshot": snapshot, "brief": str(BRIEF_PATH)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Quill session refresh: event-gated project refresh for Codex sessions.")
    parser.add_argument("--force", action="store_true", help="Refresh even if no material project change is detected.")
    parser.add_argument("--skip-zotero", action="store_true", help="Skip Zotero plugin bridge and use the current local digest inputs.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    args = parser.parse_args()
    payload = refresh(force=args.force, skip_zotero=args.skip_zotero)
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    print(
        "Quill session refresh: "
        f"events={payload['events'] or ['none']}; "
        f"brief={payload['brief']}"
    )


if __name__ == "__main__":
    main()
