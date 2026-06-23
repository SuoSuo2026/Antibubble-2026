from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import traceback
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from dashboard_builder import (
    BASE_DIR,
    DASHBOARD_DIR,
    RAW_DIR,
    SWITCHES_PATH,
    build_dashboard_data,
    load_json,
    slugify,
    write_json,
)

mimetypes.add_type("video/mp4", ".mp4")
mimetypes.add_type("video/webm", ".webm")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_print(message: str) -> None:
    if sys.stdout is None:
        return
    try:
        print(message)
    except Exception:
        return


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):  # noqa: A002, N802 - http.server API.
        safe_print("[dashboard] " + (format % args))

    def end_headers(self):  # noqa: N802 - http.server API.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):  # noqa: N802 - http.server API.
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/dashboard/")
            self.end_headers()
            return
        if parsed.path == "/api/rebuild":
            payload = build_dashboard_data()
            write_json(DASHBOARD_DIR / "dashboard_data.json", payload)
            self._send_json({"ok": True, "generated_at": payload["generated_at"]})
            return
        if parsed.path == "/api/switches":
            self._send_json(json.loads(SWITCHES_PATH.read_text(encoding="utf-8")))
            return
        super().do_GET()

    def do_POST(self):  # noqa: N802 - http.server API.
        parsed = urlparse(self.path)
        if parsed.path == "/api/case-action":
            self._handle_case_action()
            return
        if parsed.path != "/api/switches":
            self.send_error(HTTPStatus.NOT_FOUND, "Unknown endpoint")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {exc}")
            return

        if not isinstance(payload, dict) or "cases" not in payload:
            self.send_error(HTTPStatus.BAD_REQUEST, "Switch payload must contain cases")
            return

        write_json(SWITCHES_PATH, payload)
        dashboard_payload = build_dashboard_data()
        write_json(DASHBOARD_DIR / "dashboard_data.json", dashboard_payload)
        self._send_json({"ok": True, "generated_at": dashboard_payload["generated_at"]})

    def _handle_case_action(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length)
        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            self.send_error(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {exc}")
            return

        case_id = str(payload.get("case_id", "")).strip()
        action = str(payload.get("action", "")).strip()
        if not case_id or action not in {"confirm", "rerun"}:
            self.send_error(HTTPStatus.BAD_REQUEST, "Payload must contain case_id and action=confirm|rerun")
            return

        switches = load_json(SWITCHES_PATH, {"version": 1, "global": {}, "default_method": {}, "cases": {}})
        switches.setdefault("cases", {}).setdefault(case_id, {})
        case_switch = switches["cases"][case_id]
        if action == "confirm":
            case_switch["confirmed"] = True
            case_switch["confirmed_at"] = now_iso()
            case_switch.pop("rerun_requested_at", None)
            case_switch.pop("rerun_status", None)
            start_rerun = False
        else:
            case_switch["confirmed"] = False
            case_switch["rerun_requested_at"] = now_iso()
            case_switch["rerun_status"] = "queued"
            start_rerun = True

        write_json(SWITCHES_PATH, switches)
        dashboard_payload = build_dashboard_data()
        write_json(DASHBOARD_DIR / "dashboard_data.json", dashboard_payload)
        if start_rerun:
            threading.Thread(target=run_case_rerun, args=(case_id,), daemon=True).start()
        self._send_json({"ok": True, "case_id": case_id, "action": action, "generated_at": dashboard_payload["generated_at"]})

    def _send_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def find_raw_tiff(case_id: str) -> Path | None:
    for path in RAW_DIR.rglob("*.tif"):
        if slugify(path.stem) == case_id:
            return path
    return None


def update_case_switch(case_id: str, updates: dict) -> None:
    switches = load_json(SWITCHES_PATH, {"version": 1, "global": {}, "default_method": {}, "cases": {}})
    switches.setdefault("cases", {}).setdefault(case_id, {}).update(updates)
    write_json(SWITCHES_PATH, switches)
    dashboard_payload = build_dashboard_data()
    write_json(DASHBOARD_DIR / "dashboard_data.json", dashboard_payload)


def run_case_rerun(case_id: str) -> None:
    raw_path = find_raw_tiff(case_id)
    if raw_path is None:
        update_case_switch(case_id, {"rerun_status": "failed", "rerun_error": "raw TIFF not found", "rerun_finished_at": now_iso()})
        return
    update_case_switch(case_id, {"rerun_status": "running", "rerun_started_at": now_iso()})
    try:
        from agent_loop import process_tiff

        result = process_tiff(raw_path, case_id, intake=None)
        update_case_switch(
            case_id,
            {
                "rerun_status": "finished",
                "rerun_finished_at": now_iso(),
                "rerun_output_dir": result.get("output_dir"),
                "confirmed": False,
            },
        )
    except Exception as exc:  # noqa: BLE001 - background rerun should not stop dashboard.
        update_case_switch(
            case_id,
            {
                "rerun_status": "failed",
                "rerun_error": str(exc),
                "rerun_traceback": traceback.format_exc(),
                "rerun_finished_at": now_iso(),
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Antibubble dashboard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    payload = build_dashboard_data()
    write_json(DASHBOARD_DIR / "dashboard_data.json", payload)

    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}/dashboard/"
    safe_print(f"Dashboard ready: {url}")
    safe_print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        safe_print("\nDashboard stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
