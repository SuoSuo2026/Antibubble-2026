from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
LIBRARY_DIR = BASE_DIR / "library"


def find_zotero_plugin_script() -> Path:
    plugin_root = Path.home() / ".codex" / "plugins" / "cache" / "openai-curated" / "zotero"
    candidates = list(plugin_root.glob("*/skills/zotero/scripts/zotero.py"))
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime)
    return plugin_root / "skills" / "zotero" / "scripts" / "zotero.py"


PLUGIN_SCRIPT = find_zotero_plugin_script()

LIVE_BIB_PATH = LIBRARY_DIR / "zotero_live_export.bib"
COLLECTIONS_PATH = LIBRARY_DIR / "zotero_collections.json"
INVENTORY_PATH = LIBRARY_DIR / "zotero_plugin_inventory.json"
PROBE_PATH = LIBRARY_DIR / "zotero_plugin_probe.json"
BRIDGE_STATUS_PATH = LIBRARY_DIR / "zotero_plugin_status.json"


def run_zotero(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(PLUGIN_SCRIPT), *args]
    try:
        return subprocess.run(
            command,
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, stdout="", stderr=f"Zotero helper timed out after {timeout}s.")


def parse_json_result(result: subprocess.CompletedProcess[str]) -> Any:
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "").strip())
    return json.loads(result.stdout)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def collection_tree(collections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key = {
        item.get("key"): {
            "key": item.get("key"),
            "name": item.get("name"),
            "children": [],
        }
        for item in collections
        if item.get("key")
    }
    roots: list[dict[str, Any]] = []
    for item in collections:
        key = item.get("key")
        if not key or key not in by_key:
            continue
        parent = item.get("parentCollection")
        if parent and parent in by_key:
            by_key[parent]["children"].append(by_key[key])
        else:
            roots.append(by_key[key])
    return roots


def build_bridge(library_dir: Path = LIBRARY_DIR) -> dict[str, Any]:
    if not PLUGIN_SCRIPT.exists():
        payload = {
            "available": False,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "error": f"Zotero plugin helper not found: {PLUGIN_SCRIPT}",
        }
        write_json(BRIDGE_STATUS_PATH, payload)
        return payload

    try:
        probe = parse_json_result(run_zotero(["probe", "--json"], timeout=20))
        collections = parse_json_result(run_zotero(["collections", "--json"], timeout=20))
        inventory = parse_json_result(run_zotero(["inventory", "--json"], timeout=30))

        live_bib = library_dir / LIVE_BIB_PATH.name
        export = parse_json_result(run_zotero(["export-bibtex", "--out", str(live_bib)], timeout=45))
    except Exception as exc:  # noqa: BLE001 - plugin availability should not break dashboard refresh.
        payload = {
            "available": False,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "plugin_script": str(PLUGIN_SCRIPT),
            "error": str(exc),
        }
        write_json(BRIDGE_STATUS_PATH, payload)
        return payload

    collection_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "collections": collections,
        "tree": collection_tree(collections),
    }
    write_json(library_dir / COLLECTIONS_PATH.name, collection_payload)
    write_json(library_dir / INVENTORY_PATH.name, inventory)
    write_json(library_dir / PROBE_PATH.name, probe)

    top_items = [item for item in inventory if item.get("itemType") not in {"attachment", "note"}]
    payload = {
        "available": True,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "provider": "zotero_plugin_local_api",
        "plugin_script": str(PLUGIN_SCRIPT),
        "local_api": {
            "ok_routes": sum(1 for item in probe if int(item.get("status") or 0) == 200),
            "failed_routes": [
                {
                    "label": item.get("label"),
                    "status": item.get("status"),
                    "summary": item.get("summary"),
                }
                for item in probe
                if int(item.get("status") or 0) != 200
            ],
        },
        "collections": {
            "count": len(collections),
            "top_count": sum(1 for item in collections if not item.get("parentCollection")),
            "tree": collection_payload["tree"],
        },
        "inventory": {
            "raw_count": len(inventory),
            "top_item_count": len(top_items),
        },
        "export": export,
        "outputs": {
            "bibtex": str(live_bib),
            "collections": str(library_dir / COLLECTIONS_PATH.name),
            "inventory": str(library_dir / INVENTORY_PATH.name),
            "probe": str(library_dir / PROBE_PATH.name),
        },
    }
    write_json(library_dir / BRIDGE_STATUS_PATH.name, payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Refresh project Zotero files through the Codex Zotero plugin.")
    parser.add_argument("--library", default=str(LIBRARY_DIR), help="Project library directory.")
    parser.add_argument("--json", action="store_true", help="Print full JSON status.")
    args = parser.parse_args()
    payload = build_bridge(Path(args.library))
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return
    if payload.get("available"):
        print(
            "Zotero plugin bridge: "
            f"{payload['inventory']['top_item_count']} top items, "
            f"{payload['collections']['count']} collections, "
            f"{payload['export']['bibtex_entries']} BibTeX entries."
        )
        print(f"BibTeX: {payload['outputs']['bibtex']}")
    else:
        print(f"Zotero plugin bridge unavailable: {payload.get('error')}")


if __name__ == "__main__":
    main()
