from __future__ import annotations

import argparse
import json
import math
import posixpath
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from eureka_agent import (
    apply_eureka_training_to_review,
    build_eureka_case,
    load_literature_corpus,
    write_eureka_profile,
)
from manuscript_agent import build_manuscript_draft


BASE_DIR = Path(__file__).resolve().parent
PROCESSED_DIR = BASE_DIR / "processed_data"
RAW_DIR = BASE_DIR / "raw_data"
DASHBOARD_DIR = BASE_DIR / "dashboard"
PHASE_SOURCE_DIR = DASHBOARD_DIR / "assets" / "phase_sources"
WORKFLOW_DIR = BASE_DIR / "agent_workspace"
SWITCHES_PATH = WORKFLOW_DIR / "processing_switches.json"
REVIEWER_PROFILE_PATH = WORKFLOW_DIR / "reviewer_profile.json"
REVIEW_REPORT_DIR = WORKFLOW_DIR / "reviewer_reports"
DAILY_MEMO_PATH = WORKFLOW_DIR / "daily_memo.md"
QUILL_SESSION_BRIEF_PATH = WORKFLOW_DIR / "quill_session_brief.md"
PAPER_SECTIONS_DIR = WORKFLOW_DIR / "paper_sections"
WRITING_STATE_PATH = WORKFLOW_DIR / "writing_state.json"
PRL_FIGURE_INDEX_PATH = WORKFLOW_DIR / "prl_figure_index.json"
PAPER_FIGURES_ASSETS = DASHBOARD_DIR / "assets" / "paper_figures"


AGENT_ROSTER = {
    "loop": {
        "name": "Sisyphus",
        "role": "Loop 处理智能体",
        "scope": "监控 raw_data、继承 FAST 参数、触发处理、刷新看板；不擅自改算法。",
    },
    "reviewer": {
        "name": "Franklin",
        "role": "副 Agent 质检智能体",
        "scope": "按规则与经验对 tracking、ROI、Vfr、拟合质量打分并给出复核建议。",
    },
    "literature": {
        "name": "Eureka",
        "role": "文献观察智能体",
        "scope": "读取 library 文献栈，独立总结现象与可分析方向，只通过白名单规则影响 Franklin。",
    },
    "writer": {
        "name": "Quill",
        "role": "论文撰写智能体",
        "scope": "根据已有结果撰写引言、方法、结果与结论草稿；未知内容留空。",
    },
}


ASSET_PRIORITY = [
    "output_monitor.webm",
    "auto_output_monitor.webm",
    "output_monitor.mp4",
    "auto_output_monitor.mp4",
    "group_meeting_final_four_panel.png",
    "rigid_ball_summary_panel.png",
    "rigid_ball_trajectory.png",
    "valid_window_tracking_preview.png",
    "tracking_preview.png",
    "frame0_with_roi.png",
    "acceleration_core_robust.png",
    "acceleration.png",
    "position.png",
    "radius_volume_equivalent.png",
]


DEFAULT_REVIEWER_PROFILE = {
    "version": 1,
    "weights": {
        "tracking": 0.25,
        "radius_stability": 0.25,
        "fit_stability": 0.30,
        "frequency_stability": 0.20,
    },
    "neutral_score_when_missing": 60.0,
    "thresholds": {
        "radius_rel_std_percent_excellent": 2.0,
        "radius_rel_std_percent_poor": 8.0,
        "fit_rel_std_percent_excellent": 0.5,
        "fit_rel_std_percent_poor": 3.0,
        "freq_rel_std_percent_excellent": 1.0,
        "freq_rel_std_percent_poor": 5.0,
    },
    "dashboard_display": {
        "default_view": "all",
        "featured_min_score": 75.0,
        "hide_raw_only_by_default": True,
    },
    "subjective_notes": [
        "Prefer cases with continuous tracking and stable radius.",
        "Reward acceleration fits that stay stable across smoothing windows and time windows.",
        "Penalize outputs that miss preview figures, valid windows, or fit summaries.",
    ],
}


DEFAULT_SWITCHES = {
    "version": 1,
    "global": {
        "auto_process_new_raw_data": False,
        "prefer_group_meeting_outputs": True,
        "cloud_sync_enabled": False,
        "cloud_sync_target": "",
    },
    "default_method": {
        "tracking_refinement": True,
        "use_quad_osc_fit": True,
        "export_video": True,
        "review_after_processing": True,
    },
    "cases": {},
}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:  # noqa: BLE001 - keep dashboard resilient.
        return {"_load_error": str(exc), "_path": str(path)}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def ensure_workflow_files() -> None:
    if not SWITCHES_PATH.exists():
        write_json(SWITCHES_PATH, DEFAULT_SWITCHES)
    if not REVIEWER_PROFILE_PATH.exists():
        write_json(REVIEWER_PROFILE_PATH, DEFAULT_REVIEWER_PROFILE)


def slugify(value: str) -> str:
    value = value.strip().replace("\\", "/")
    value = Path(value).stem if "/" in value else value
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "unknown_case"


def rel_url(path: Path) -> str:
    try:
        return "/" + path.resolve().relative_to(BASE_DIR.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def score_lower_is_better(value: float | None, excellent: float, poor: float) -> float | None:
    if value is None:
        return None
    if value <= excellent:
        return 100.0
    if value >= poor:
        return 20.0
    span = poor - excellent
    return 100.0 - 80.0 * ((value - excellent) / span)


def score_higher_is_better(value: float | None, poor: float, excellent: float) -> float | None:
    if value is None:
        return None
    if value >= excellent:
        return 100.0
    if value <= poor:
        return 20.0
    span = excellent - poor
    return 20.0 + 80.0 * ((value - poor) / span)


def compute_reviewer_score(metrics: dict[str, Any], profile: dict[str, Any]) -> dict[str, Any]:
    neutral = finite_float(profile.get("neutral_score_when_missing")) or 60.0
    weights = profile.get("weights", {})
    thresholds = profile.get("thresholds", {})

    experiment_type = str(metrics.get("experiment_type", "")).lower()
    is_rigid_ball = experiment_type in {"rigid_ball", "rigid", "solid_ball", "hard_sphere", "sphere"}

    tracking_ratio = finite_float(metrics.get("valid_found_ratio"))
    tracking_score = tracking_ratio * 100.0 if tracking_ratio is not None else None

    radius_rel = finite_float(metrics.get("radius_rel_std_percent"))
    if radius_rel is None:
        radius_mean = finite_float(metrics.get("radius_mean_mm"))
        radius_std = finite_float(metrics.get("radius_std_mm"))
        if radius_mean and radius_std is not None:
            radius_rel = abs(radius_std / radius_mean) * 100.0

    fit_rel = finite_float(metrics.get("a_fit_osc_rel_std_percent"))
    if fit_rel is None:
        fit_mean = finite_float(metrics.get("a_fit_osc_mean_mm_s2"))
        fit_std = finite_float(metrics.get("a_fit_osc_std_mm_s2"))
        if fit_mean and fit_std is not None:
            fit_rel = abs(fit_std / fit_mean) * 100.0

    freq_rel = None
    freq_mean = finite_float(metrics.get("freq_mean_hz"))
    freq_std = finite_float(metrics.get("freq_std_hz"))
    if freq_mean and freq_std is not None:
        freq_rel = abs(freq_std / freq_mean) * 100.0

    method = "rigid_ball" if is_rigid_ball else "oscillation"
    if freq_mean is None and (
        "a_quad_mean_mm_s2" in metrics
        or "a_prefusion_quadratic_mean_mm_s2" in metrics
        or "a_prefusion_mean_mm_s2" in metrics
    ) and not is_rigid_ball:
        method = "prefusion_quadratic"

    radius_score = score_lower_is_better(
        radius_rel,
        float(thresholds.get("radius_rel_std_percent_excellent", 2.0)),
        float(thresholds.get("radius_rel_std_percent_poor", 8.0)),
    )
    fit_score = score_lower_is_better(
        fit_rel,
        float(thresholds.get("fit_rel_std_percent_excellent", 0.5)),
        float(thresholds.get("fit_rel_std_percent_poor", 3.0)),
    )
    freq_score = score_lower_is_better(
        freq_rel,
        float(thresholds.get("freq_rel_std_percent_excellent", 1.0)),
        float(thresholds.get("freq_rel_std_percent_poor", 5.0)),
    )

    flags = []

    if is_rigid_ball:
        fit_score = score_higher_is_better(
            finite_float(metrics.get("primary_fit_r2"))
            or finite_float(metrics.get("x_linear_r2"))
            or finite_float(metrics.get("y_parabola_r2")),
            poor=0.90,
            excellent=0.995,
        )
        freq_score = 100.0
        radius_step = finite_float(metrics.get("radius_step_rel_max_percent"))
        center_outliers = finite_float(metrics.get("center_step_outlier_count")) or 0.0
        radius_outliers = finite_float(metrics.get("radius_step_outlier_count")) or 0.0
        if radius_step is not None and radius_step > 12.0:
            flags.append("radius_step_jump")
            if radius_score is not None:
                radius_score = min(radius_score, max(20.0, 100.0 - radius_step * 2.0))
        if center_outliers > 0:
            flags.append("center_step_jump")
            if fit_score is not None:
                fit_score = max(20.0, fit_score - 18.0 * center_outliers)
        if radius_outliers > 0:
            flags.append("radius_step_outlier")
            if radius_score is not None:
                radius_score = max(20.0, radius_score - 12.0 * radius_outliers)
    if tracking_ratio is not None and tracking_ratio < 0.98:
        flags.append("tracking_incomplete")
    if radius_rel is not None and radius_rel > float(thresholds.get("radius_rel_std_percent_poor", 8.0)):
        flags.append("radius_unstable")
    if fit_rel is not None and fit_rel > float(thresholds.get("fit_rel_std_percent_poor", 3.0)):
        flags.append("fit_window_sensitive")
    if is_rigid_ball:
        if fit_score is None:
            flags.append("primary_fit_unavailable")
        if radius_rel is not None and radius_rel > 4.0:
            flags.append("rigid_radius_unstable")
    elif freq_mean is None:
        flags.append("frequency_unavailable")
    elif freq_rel is not None and freq_rel > float(thresholds.get("freq_rel_std_percent_poor", 5.0)):
        flags.append("frequency_unstable")

    scan_range = metrics.get("freq_scan_range_hz")
    if isinstance(scan_range, list) and len(scan_range) == 2 and freq_mean is not None:
        low = finite_float(scan_range[0])
        high = finite_float(scan_range[1])
        if low is not None and high is not None:
            margin = max((high - low) * 0.03, 0.5)
            if freq_mean <= low + margin or freq_mean >= high - margin:
                flags.append("frequency_near_scan_boundary")
                if freq_score is not None:
                    freq_score *= 0.3

    valid_range = metrics.get("valid_frame_range")
    if isinstance(valid_range, list) and len(valid_range) == 2:
        f0 = finite_float(valid_range[0])
        f1 = finite_float(valid_range[1])
        short_threshold = 45 if is_rigid_ball else 30
        if f0 is not None and f1 is not None and f1 - f0 + 1 < short_threshold:
            flags.append("short_valid_window")
            if fit_score is not None:
                fit_score = min(fit_score, 50.0)

    parts = {
        "tracking": tracking_score,
        "radius_stability": radius_score,
        "fit_stability": fit_score,
        "frequency_stability": freq_score,
    }
    total_weight = 0.0
    total = 0.0
    for key, raw_weight in weights.items():
        weight = finite_float(raw_weight) or 0.0
        score = parts.get(key)
        total += weight * (neutral if score is None else score)
        total_weight += weight

    reviewer_score = total / total_weight if total_weight else neutral
    if is_rigid_ball and "short_valid_window" in flags:
        reviewer_score = min(reviewer_score, 84.0)
    missing = [key for key, value in parts.items() if value is None]
    if reviewer_score >= 85:
        band = "excellent"
    elif reviewer_score >= 70:
        band = "usable_review"
    elif reviewer_score >= 50:
        band = "needs_review"
    else:
        band = "low_confidence"

    return {
        "reviewer_score": round(max(0.0, min(100.0, reviewer_score)), 1),
        "band": band,
        "method": method,
        "flags": sorted(set(flags)),
        "score_parts": {k: None if v is None else round(v, 1) for k, v in parts.items()},
        "score_inputs": {
            "radius_rel_std_percent": None if radius_rel is None else round(radius_rel, 3),
            "fit_rel_std_percent": None if fit_rel is None else round(fit_rel, 3),
            "freq_rel_std_percent": None if freq_rel is None else round(freq_rel, 3),
        },
        "missing_score_inputs": missing,
    }


def output_root_for_json(path: Path) -> Path:
    parent_names = {
        "acceleration_fit_osc",
        "acceleration_prefusion_quadratic",
    }
    if path.parent.name in parent_names:
        return path.parent.parent
    return path.parent


def case_id_from_path(path: Path) -> str:
    try:
        rel = path.relative_to(PROCESSED_DIR)
    except ValueError:
        return slugify(path.parent.name)
    parts = rel.parts
    if not parts:
        return "unknown_case"
    if parts[0] == "group_meeting_package" and len(parts) > 1 and parts[1] != "_summary":
        return slugify(parts[1])
    return slugify(parts[0])


def merge_metrics(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if key.startswith("_"):
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            target[key] = value
        elif key in {"valid_frame_range", "roi", "tracking_overrides", "fit_windows", "smooth_windows", "auto_selection"}:
            target[key] = value


def collect_assets(outdir: Path) -> dict[str, Any]:
    images = []
    videos = []
    if outdir.exists():
        for path in outdir.rglob("*"):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            item = {
                "name": path.name,
                "path": str(path),
                "url": rel_url(path),
                "relative_path": path.relative_to(BASE_DIR).as_posix()
                if path.is_relative_to(BASE_DIR)
                else path.as_posix(),
                "modified_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
            }
            if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                images.append(item)
            elif suffix in {".webm", ".mp4", ".mov", ".avi"}:
                videos.append(item)

    def image_priority(item: dict[str, Any]) -> tuple[int, str]:
        try:
            rank = ASSET_PRIORITY.index(item["name"])
        except ValueError:
            name = item["name"].lower()
            rank = len(ASSET_PRIORITY)
        return rank, item["name"]

    def video_priority(item: dict[str, Any]) -> tuple[int, float, str]:
        name = item["name"].lower()
        modified = Path(item["path"]).stat().st_mtime if Path(item["path"]).exists() else 0.0
        if name.endswith("monitor.mp4"):
            rank = 0
        elif name.endswith(".mp4"):
            rank = 1
        elif name.endswith("monitor.webm"):
            rank = 2
        elif name.endswith(".webm"):
            rank = 3
        else:
            rank = 4
        return rank, -modified, item["name"]

    images.sort(key=image_priority)
    videos.sort(key=video_priority)
    return {
        "preview_image": images[0] if images else None,
        "images": images[:24],
        "videos": videos[:12],
        "image_count": len(images),
        "video_count": len(videos),
    }


def collect_raw_files() -> dict[str, list[dict[str, str]]]:
    raw_by_case: dict[str, list[dict[str, str]]] = {}
    if not RAW_DIR.exists():
        return raw_by_case

    for path in RAW_DIR.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".tif", ".tiff", ".mp4", ".avi", ".mov"}:
            continue
        case_id = slugify(path.stem)
        raw_by_case.setdefault(case_id, []).append(
            {
                "name": path.name,
                "path": str(path),
                "url": rel_url(path),
                "relative_path": path.relative_to(BASE_DIR).as_posix()
                if path.is_relative_to(BASE_DIR)
                else path.as_posix(),
                "kind": "video" if path.suffix.lower() in {".mp4", ".avi", ".mov"} else "tiff",
            }
        )
    return raw_by_case


def load_latest_review_reports() -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    if not REVIEW_REPORT_DIR.exists():
        return reports
    for path in REVIEW_REPORT_DIR.glob("*_latest.json"):
        payload = load_json(path)
        if not isinstance(payload, dict):
            continue
        case_id = payload.get("case_id") or path.name.removesuffix("_latest.json")
        reports[str(case_id)] = {
            "path": str(path),
            "created_at": payload.get("created_at"),
            "reviewer_score": payload.get("reviewer_score"),
            "band": payload.get("band"),
            "flags": payload.get("flags", []),
            "recommended_next_action": payload.get("recommended_next_action"),
            "assumptions": payload.get("assumptions", []),
            "memory_score_adjustment": payload.get("memory_score_adjustment"),
            "memory_matches": payload.get("memory_matches", {}),
            "memory_recommendations": payload.get("memory_recommendations", []),
            "eureka_score_adjustment": payload.get("eureka_score_adjustment"),
            "reviewer_score_before_eureka": payload.get("reviewer_score_before_eureka"),
            "eureka_training_notes": payload.get("eureka_training_notes", []),
            "eureka_applied_rules": payload.get("eureka_applied_rules", []),
        }
    return reports


def load_run_payloads(outdir: Path) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    known_files = {
        "case_summary": outdir / "case_summary.json",
        "group_meeting_summary": outdir / "group_meeting_summary.json",
        "group_meeting_final_metrics": outdir / "group_meeting_final_metrics.json",
        "a_fit_osc_summary": outdir / "acceleration_fit_osc" / "a_fit_osc_summary.json",
        "a_prefusion_quadratic_summary": outdir
        / "acceleration_prefusion_quadratic"
        / "a_prefusion_quadratic_summary.json",
    }
    for key, path in known_files.items():
        payload = load_json(path)
        if payload is not None:
            payloads[key] = payload
    return payloads


def summarize_run(outdir: Path) -> dict[str, Any]:
    payloads = load_run_payloads(outdir)
    metrics: dict[str, Any] = {}
    display_name = None

    for key in ["case_summary", "group_meeting_summary", "group_meeting_final_metrics"]:
        payload = payloads.get(key)
        if isinstance(payload, dict):
            display_name = display_name or payload.get("case")
            merge_metrics(metrics, payload)

    fit_payload = payloads.get("a_fit_osc_summary")
    if isinstance(fit_payload, dict):
        summary = fit_payload.get("summary", fit_payload)
        if isinstance(summary, dict):
            display_name = display_name or summary.get("case")
            merge_metrics(metrics, summary)
            if "fits" in fit_payload:
                metrics["n_fits"] = len(fit_payload.get("fits") or [])

    prefusion_payload = payloads.get("a_prefusion_quadratic_summary")
    if isinstance(prefusion_payload, dict):
        merge_metrics(metrics, prefusion_payload)

    if not display_name:
        display_name = case_id_from_path(outdir)

    return {
        "run_id": outdir.relative_to(BASE_DIR).as_posix()
        if outdir.is_relative_to(BASE_DIR)
        else str(outdir),
        "case_id": slugify(display_name),
        "display_name": display_name,
        "output_dir": str(outdir),
        "output_url": rel_url(outdir),
        "metrics": metrics,
        "payloads_present": sorted(payloads.keys()),
        "assets": collect_assets(outdir),
        "modified_at": datetime.fromtimestamp(outdir.stat().st_mtime).isoformat(timespec="seconds")
        if outdir.exists()
        else None,
    }


def discover_output_dirs() -> set[Path]:
    output_dirs: set[Path] = set()
    if not PROCESSED_DIR.exists():
        return output_dirs
    for path in PROCESSED_DIR.rglob("*.json"):
        try:
            rel_parts = path.relative_to(PROCESSED_DIR).parts
        except ValueError:
            rel_parts = ()
        if rel_parts and rel_parts[0] == "internal_diagnostics":
            continue
        if path.name in {
            "case_summary.json",
            "group_meeting_summary.json",
            "group_meeting_final_metrics.json",
            "a_fit_osc_summary.json",
            "a_prefusion_quadratic_summary.json",
        }:
            outdir = output_root_for_json(path)
            if "group_meeting_package/_summary" not in outdir.as_posix():
                output_dirs.add(outdir)
    return output_dirs


def choose_best_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not runs:
        return None

    def key(run: dict[str, Any]) -> tuple[float, int, int, str]:
        score = finite_float(run.get("review", {}).get("reviewer_score")) or 0.0
        has_final = int("group_meeting_final_metrics" in run.get("payloads_present", []))
        processed_by = str(run.get("metrics", {}).get("processed_by", ""))
        is_diagnostic = int(
            processed_by == "rigid_ball_perspective_correction"
            or "perspective" in str(run.get("run_id", "")).lower()
        )
        modified = run.get("modified_at") or ""
        return score, has_final, -is_diagnostic, modified

    return sorted(runs, key=key, reverse=True)[0]


def build_history_payload(runs: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    today = datetime.now().date().isoformat()
    recent_runs = []
    for run in sorted(runs, key=lambda item: item.get("modified_at") or "", reverse=True):
        metrics = run.get("metrics", {})
        review = run.get("review", {})
        recent_runs.append(
            {
                "case_id": run.get("case_id"),
                "run_id": run.get("run_id"),
                "modified_at": run.get("modified_at"),
                "score": review.get("reviewer_score"),
                "band": review.get("band"),
                "flags": review.get("flags", []),
                "radius_rel_std_percent": metrics.get("radius_rel_std_percent"),
                "accel_mm_s2": metrics.get("primary_quad_accel_mm_s2") or metrics.get("a_fit_osc_mean_mm_s2"),
            }
        )
    today_cases = [
        item
        for item in recent_runs
        if isinstance(item.get("modified_at"), str) and item["modified_at"].startswith(today)
    ]
    memo_text = ""
    if DAILY_MEMO_PATH.exists():
        memo_text = DAILY_MEMO_PATH.read_text(encoding="utf-8").strip()
    if not memo_text:
        rigid_today = [
            case["display_name"]
            for case in cases
            if str(case.get("metrics", {}).get("experiment_type", "")).lower() == "rigid_ball"
            and any(
                isinstance(run.get("modified_at"), str) and run["modified_at"].startswith(today)
                for run in case.get("runs", [])
            )
        ]
        if rigid_today:
            memo_text = (
                f"{today}：硬小球-液膜相互作用 Case 已更新。\n"
                "重点问题：左侧液体运动会误导小球识别。\n"
                "处理策略：Franklin 已加重半径突变、质心突变和左侧液体污染惩罚。\n"
                f"今日 Case：{', '.join(rigid_today[:8])}。"
            )
        else:
            memo_text = f"{today}：暂无新增处理记录。"
    session_brief_text = ""
    if QUILL_SESSION_BRIEF_PATH.exists():
        session_brief_text = QUILL_SESSION_BRIEF_PATH.read_text(encoding="utf-8", errors="ignore").strip()
    return {
        "today": today,
        "today_run_count": len(today_cases),
        "recent_runs": recent_runs[:12],
        "contribution_calendar": build_contribution_calendar(runs),
        "memo": {
            "path": str(DAILY_MEMO_PATH),
            "text": memo_text,
        },
        "session_brief": {
            "path": str(QUILL_SESSION_BRIEF_PATH),
            "text": session_brief_text,
        },
    }


def build_showcase_payload(
    cases: list[dict[str, Any]],
    research_digest: dict[str, Any],
    summary: dict[str, Any],
) -> dict[str, Any]:
    def case_score(case: dict[str, Any]) -> float:
        return finite_float(case.get("best_score")) or 0.0

    def case_type(case: dict[str, Any]) -> str:
        experiment = str(case.get("metrics", {}).get("experiment_type", "")).lower()
        return "rigid" if experiment in {"rigid_ball", "rigid", "solid_ball", "hard_sphere", "sphere"} else "droplet"

    def compact_case(case: dict[str, Any]) -> dict[str, Any]:
        metrics = case.get("metrics", {})
        eureka = case.get("eureka", {})
        observation = str(eureka.get("phenomenon_summary") or "").split("；")[0].strip()
        return {
            "case_id": case.get("case_id"),
            "display_name": case.get("display_name"),
            "status": case.get("status"),
            "score": case.get("best_score"),
            "type": case_type(case),
            "preview": case.get("best_preview"),
            "material": metrics.get("material") or "-",
            "radius_mean_mm": metrics.get("radius_mean_mm"),
            "velocity_abs_mean_mm_s": metrics.get("velocity_abs_mean_mm_s"),
            "accel_mm_s2": metrics.get("primary_quad_accel_mm_s2") or metrics.get("a_fit_osc_mean_mm_s2"),
            "observation": observation,
        }

    processed = [case for case in cases if case.get("best_run_id")]
    with_preview = [case for case in processed if case.get("best_preview")]
    rigid_cases = [case for case in with_preview if case_type(case) == "rigid"]
    droplet_cases = [case for case in with_preview if case_type(case) != "rigid"]
    selected: list[dict[str, Any]] = []
    for pool in (rigid_cases, droplet_cases, with_preview):
        for case in sorted(pool, key=case_score, reverse=True):
            if case.get("case_id") not in {item.get("case_id") for item in selected}:
                selected.append(case)
            if len(selected) >= 4:
                break
        if len(selected) >= 4:
            break

    return {
        "title": "从实验录像到论文素材：本地 AI 科研工作流",
        "subtitle": "给组会/同学看的轻量展示区；完整参数、复核和数据细节仍保留在你自己的看板页。",
        "stats": {
            "case_count": summary.get("case_count"),
            "processed_count": summary.get("processed_count"),
            "run_count": summary.get("run_count"),
            "top_case": summary.get("top_case"),
        },
        "pipeline": [
            {"agent": "Raw data", "title": "录入实验录像", "detail": "tif/mp4 进入 raw_data，文件名携带材料与实验类型。"},
            {"agent": "Sisyphus", "title": "自动处理", "detail": "继承同批参数，提取 ROI、R、v、a 和有效窗口。"},
            {"agent": "Franklin", "title": "质量复核", "detail": "惩罚半径突变、质心跳变、左侧液体误识别和短窗口。"},
            {"agent": "Eureka", "title": "文献解释", "detail": "只做独立观察与复核建议，不擅自改变处理 pipeline。"},
            {"agent": "Quill", "title": "论文草稿", "detail": "把已完成结果写成引言、方法、结果和讨论片段。"},
        ],
        "demo_cases": [compact_case(case) for case in selected],
        "talk_track": [
            "先展示 raw data 到看板的自动路径，避免同学陷入文件夹细节。",
            "再展示一个高分刚体 Case，说明 tracking、R-v-a 和 Franklin 评分如何闭环。",
            "然后展示 Eureka/Quill 如何把数据和文献连接到论文问题。",
            "最后展示待验证问题：颗粒-PB 是否存在气膜、液桥或直接润湿接触。",
        ],
        "pb_particle_focus": research_digest.get("pb_particle_brief", {}),
        "optimization_backlog": research_digest.get("optimization_backlog", []),
        "presentation_rule": "展示页只服务交流和复盘；任何处理算法修改仍以用户明确确认为准。",
    }


def parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def file_modified_date(path: Path) -> date | None:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).date()
    except OSError:
        return None


def contribution_level(score: float) -> int:
    if score <= 0:
        return 0
    if score < 5:
        return 1
    if score < 12:
        return 2
    if score < 24:
        return 3
    return 4


def add_contribution(
    daily: dict[str, dict[str, Any]],
    day: date | None,
    category: str,
    points: float,
    detail: str,
    start_date: date,
    end_date: date,
) -> None:
    if day is None or day < start_date or day > end_date:
        return
    key = day.isoformat()
    row = daily.setdefault(key, {"raw_categories": {}, "details": []})
    row["raw_categories"][category] = row["raw_categories"].get(category, 0.0) + points
    if len(row["details"]) < 10:
        row["details"].append(detail)


def iter_files(root: Path, suffixes: set[str], skip_parts: set[str] | None = None) -> list[Path]:
    if not root.exists():
        return []
    skip_parts = skip_parts or set()
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        parts = {part.lower() for part in path.parts}
        if parts & skip_parts:
            continue
        if path.suffix.lower() in suffixes:
            files.append(path)
    return files


def build_contribution_calendar(runs: list[dict[str, Any]], days: int = 365) -> dict[str, Any]:
    today = datetime.now().date()
    start_date = date(today.year, 4, 1)
    if start_date > today:
        start_date = today - timedelta(days=days - 1)
    days = (today - start_date).days + 1
    daily: dict[str, dict[str, Any]] = {}
    category_caps = {
        "data": 30.0,
        "raw": 30.0,
        "writing": 18.0,
        "literature": 14.0,
        "agent": 10.0,
        "code": 10.0,
    }
    category_labels = {
        "data": "数据处理",
        "raw": "原始数据",
        "writing": "论文写作",
        "literature": "文献/组会",
        "agent": "智能体经验",
        "code": "看板/代码",
    }

    for run in runs:
        day = parse_date(run.get("modified_at"))
        case_id = run.get("case_id") or "case"
        add_contribution(daily, day, "data", 6.0, f"处理结果：{case_id}", start_date, today)

    for path in iter_files(RAW_DIR, {".tif", ".tiff", ".mp4", ".avi", ".webm", ".mov"}):
        add_contribution(daily, file_modified_date(path), "raw", 6.0, f"录入 raw_data：{path.name}", start_date, today)

    writing_paths = [BASE_DIR / "library" / "Manuscript.tex"]
    writing_paths.extend(iter_files(BASE_DIR / "library" / "manuscript", {".tex", ".md", ".bib"}))
    for path in writing_paths:
        if path.exists():
            add_contribution(daily, file_modified_date(path), "writing", 8.0, f"论文写作：{path.name}", start_date, today)

    library_suffixes = {".bib", ".json", ".md", ".xlsx", ".pptx", ".pdf", ".jpg", ".jpeg", ".png"}
    for path in iter_files(BASE_DIR / "library", library_suffixes, skip_parts={"files"}):
        if path.name == "Manuscript.tex":
            continue
        add_contribution(daily, file_modified_date(path), "literature", 2.0, f"文献/材料：{path.name}", start_date, today)

    agent_suffixes = {".md", ".json"}
    for path in iter_files(WORKFLOW_DIR, agent_suffixes, skip_parts={"reviewer_reports"}):
        add_contribution(daily, file_modified_date(path), "agent", 2.0, f"智能体记录：{path.name}", start_date, today)
    for path in iter_files(REVIEW_REPORT_DIR, {".json"}):
        add_contribution(daily, file_modified_date(path), "agent", 1.0, f"Franklin 复核：{path.name}", start_date, today)

    code_paths = [
        BASE_DIR / "dashboard_builder.py",
        BASE_DIR / "agent_loop.py",
        BASE_DIR / "rigid_ball_processing.py",
        BASE_DIR / "eureka_agent.py",
        BASE_DIR / "manuscript_agent.py",
        BASE_DIR / "quill_session_refresh.py",
        BASE_DIR / "dashboard" / "app.js",
        BASE_DIR / "dashboard" / "styles.css",
        BASE_DIR / "dashboard" / "index.html",
    ]
    for path in code_paths:
        if path.exists():
            add_contribution(daily, file_modified_date(path), "code", 2.0, f"看板/代码：{path.name}", start_date, today)

    day_rows = []
    for offset in range(days):
        day = start_date + timedelta(days=offset)
        key = day.isoformat()
        raw = daily.get(key, {"raw_categories": {}, "details": []})
        categories = {
            name: round(min(float(value), category_caps.get(name, float(value))), 1)
            for name, value in raw.get("raw_categories", {}).items()
        }
        score = round(sum(categories.values()), 1)
        top_categories = sorted(categories.items(), key=lambda item: item[1], reverse=True)
        day_rows.append(
            {
                "date": key,
                "score": score,
                "level": contribution_level(score),
                "categories": categories,
                "top_categories": [
                    {"key": key_name, "label": category_labels.get(key_name, key_name), "points": value}
                    for key_name, value in top_categories[:3]
                    if value > 0
                ],
                "details": raw.get("details", [])[:5],
            }
        )

    active_days = sum(1 for item in day_rows if item["score"] > 0)
    total_score = round(sum(float(item["score"]) for item in day_rows), 1)
    current_streak = 0
    for item in reversed(day_rows):
        if item["score"] <= 0:
            break
        current_streak += 1

    return {
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "days": day_rows,
        "active_days": active_days,
        "total_score": total_score,
        "today_score": day_rows[-1]["score"] if day_rows else 0,
        "current_streak": current_streak,
        "max_level": 4,
        "category_labels": category_labels,
        "rules": [
            "数据处理：每个处理版本 +6，单日最多 30。",
            "raw 数据录入/做实验：每个视频/TIFF +6，单日最多 30。",
            "论文写作：Manuscript/草稿文件变动 +8，单日最多 18。",
            "文献/组会材料：library 文献、PPT、图文资料 +2，单日最多 14。",
            "智能体经验：memo、Quill/Eureka/Franklin 记录 +1 到 +2，单日最多 10。",
            "看板/代码维护：关键脚本或前端更新 +2，单日最多 10。",
        ],
        "levels": [
            {"level": 0, "label": "无记录", "min_score": 0},
            {"level": 1, "label": "轻推进", "min_score": 1},
            {"level": 2, "label": "有效推进", "min_score": 5},
            {"level": 3, "label": "强推进", "min_score": 12},
            {"level": 4, "label": "高强度推进", "min_score": 24},
        ],
    }


def resolve_library_ppt(file_name: str) -> Path | None:
    matches = [path for path in (BASE_DIR / "library").rglob("*.pptx") if path.name == file_name]
    if not matches:
        return None
    matches.sort(key=lambda path: (0 if path.parent == BASE_DIR / "library" else 1, path.as_posix().lower()))
    return matches[0]


def ppt_slide_image_relationships(ppt_path: Path, slide_number: int) -> list[tuple[str, str, bytes]]:
    rel_path = f"ppt/slides/_rels/slide{slide_number}.xml.rels"
    try:
        with zipfile.ZipFile(ppt_path) as zf:
            names = set(zf.namelist())
            if rel_path not in names:
                return []
            root = ET.fromstring(zf.read(rel_path))
            images = []
            for rel in root:
                target = rel.attrib.get("Target", "")
                rel_type = rel.attrib.get("Type", "")
                if "image" not in rel_type and not re.search(r"\.(png|jpe?g)$", target, re.I):
                    continue
                media_path = posixpath.normpath(posixpath.join("ppt/slides", target))
                if media_path not in names:
                    media_path = posixpath.normpath(posixpath.join("ppt", target.replace("../", "")))
                if media_path not in names or not re.search(r"\.(png|jpe?g)$", media_path, re.I):
                    continue
                images.append((media_path, Path(media_path).suffix.lower(), zf.read(media_path)))
            return images
    except Exception:
        return []


def raster_size(image_bytes: bytes) -> tuple[int | None, int | None]:
    try:
        from PIL import Image
        from io import BytesIO

        image = Image.open(BytesIO(image_bytes))
        return image.width, image.height
    except Exception:
        return None, None


def extract_phase_ppt_sources(phase_candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    PHASE_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, Any]] = []
    seen: set[tuple[str, int, str]] = set()
    preferred = [item for item in phase_candidates if any(key in str(item.get("text", "")).lower() for key in ["相图", "we-bo", "criteria", "无量纲"])]
    ordered = preferred + [item for item in phase_candidates if item not in preferred]
    for index, candidate in enumerate(ordered[:8], start=1):
        file_name = str(candidate.get("file") or "")
        slide_number = int(candidate.get("slide") or 0)
        ppt_path = resolve_library_ppt(file_name)
        if not ppt_path or not slide_number:
            continue
        image_entries = []
        for media_path, suffix, content in ppt_slide_image_relationships(ppt_path, slide_number):
            width, height = raster_size(content)
            area = (width or 0) * (height or 0)
            if area < 120_000 and len(content) < 25_000:
                continue
            image_entries.append((area, len(content), media_path, suffix, content, width, height))
        image_entries.sort(reverse=True, key=lambda item: (item[0], item[1]))
        for image_rank, (_area, _size, media_path, suffix, content, width, height) in enumerate(image_entries[:2], start=1):
            key = (ppt_path.name, slide_number, media_path)
            if key in seen:
                continue
            seen.add(key)
            extension = ".jpg" if suffix in {".jpg", ".jpeg"} else ".png"
            out_name = f"phase_{index:02d}_slide{slide_number:02d}_{image_rank}{extension}"
            out_path = PHASE_SOURCE_DIR / out_name
            out_path.write_bytes(content)
            sources.append(
                {
                    "file": ppt_path.name,
                    "slide": slide_number,
                    "media": Path(media_path).name,
                    "image_url": rel_url(out_path),
                    "width": width,
                    "height": height,
                    "text": str(candidate.get("text", ""))[:240],
                }
            )
            if len(sources) >= 8:
                return sources
    return sources


def _load_json_file(path: Path, default: Any = None) -> Any:
    """Load a JSON file, returning default on any error."""
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def build_phase_space_payload(cases: list[dict[str, Any]], phase_candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    points = []
    g_mm_s2 = 9806.65
    for case in cases:
        metrics = case.get("metrics", {})
        best_run = next((run for run in case.get("runs", []) if run.get("run_id") == case.get("best_run_id")), None)
        videos = ((best_run or {}).get("assets") or {}).get("videos") or []
        video_url = videos[0].get("url") if videos and isinstance(videos[0], dict) else None
        radius = finite_float(metrics.get("radius_mean_mm"))
        accel = finite_float(metrics.get("primary_quad_accel_mm_s2"))
        if accel is None:
            accel = finite_float(metrics.get("a_fit_osc_mean_mm_s2"))
        velocity = finite_float(metrics.get("velocity_abs_mean_mm_s"))
        valid_range = metrics.get("valid_frame_range")
        fps = finite_float(metrics.get("fps"))
        primary_range = finite_float(metrics.get("primary_range_mm"))
        if velocity is None and isinstance(valid_range, list) and len(valid_range) == 2 and fps and primary_range is not None:
            duration = max((float(valid_range[1]) - float(valid_range[0])) / fps, 1e-9)
            velocity = abs(primary_range / duration)
        if radius is None and accel is None and velocity is None:
            continue
        experiment_type = str(metrics.get("experiment_type") or "").lower()
        points.append(
            {
                "case_id": case.get("case_id"),
                "display_name": case.get("display_name"),
                "status": case.get("status"),
                "score": case.get("best_score"),
                "experiment_type": experiment_type,
                "material": metrics.get("material"),
                "radius_mm": radius,
                "velocity_abs_mm_s": None if velocity is None else abs(velocity),
                "accel_abs_mm_s2": None if accel is None else abs(accel),
                "accel_g": None if accel is None else abs(accel) / g_mm_s2,
                "re": None,
                "we": None,
                "bo": None,
                "oh": None,
                "video_url": video_url,
            }
        )
    return {
        "axes": {
            "x": "radius_mm",
            "y": "accel_g",
            "planned_dimensionless": ["Re", "We", "Bo", "Oh"],
        },
        "ppt_sources": extract_phase_ppt_sources(phase_candidates or []),
        "points": points,
    }


def build_paper_sections_payload() -> dict[str, Any]:
    """Read paper sections generated by /write-section and writing state."""
    sections = {}
    section_order = ["abstract", "introduction", "methods", "results", "conclusions"]
    total_words = 0
    for name in section_order:
        md_path = PAPER_SECTIONS_DIR / f"{name}.md"
        tex_path = PAPER_SECTIONS_DIR / f"{name}.tex"
        if md_path.exists():
            body = md_path.read_text(encoding="utf-8")
            # Extract body content — skip the markdown metadata header
            # Header format: "# Title\n\n> Word count: ...\n> Generated: ...\n> Rules check: ...\n\n[body]"
            lines = body.split("\n")
            body_start = 0
            for i, line in enumerate(lines):
                if line.startswith("> "):
                    continue
                if line.strip() == "" and i > 0:
                    # We're past a blockquote section — check if next line is actual content
                    continue
                if i > 0 and not line.startswith("#") and not line.startswith(">") and line.strip():
                    body_start = i
                    break
            # If didn't find body start, try matching after the last ">" line
            if body_start == 0:
                for i, line in enumerate(lines):
                    if line.startswith("> "):
                        body_start = i + 1
                # Skip blank lines after header
                while body_start < len(lines) and lines[body_start].strip() == "":
                    body_start += 1
            body_text = "\n".join(lines[body_start:]).strip()
            latex = tex_path.read_text(encoding="utf-8") if tex_path.exists() else ""
            wc = len(body_text.split())
            total_words += wc
            sections[name] = {
                "title": name.replace("_", " ").title(),
                "body": body_text,
                "latex": latex,
                "word_count": wc,
                "has_content": True,
            }
        else:
            sections[name] = {
                "title": name.replace("_", " ").title(),
                "body": "",
                "latex": "",
                "word_count": 0,
                "has_content": False,
            }

    # Load writing state
    state: dict[str, Any] = {}
    if WRITING_STATE_PATH.exists():
        try:
            with WRITING_STATE_PATH.open("r", encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            pass

    state_sections = state.get("sections", {})
    section_list = []
    for name in section_order:
        s = sections.get(name, {})
        ss = state_sections.get(name, {})
        section_list.append({
            "name": name,
            "title": s.get("title", name.title()),
            "body": s.get("body", ""),
            "latex": s.get("latex", ""),
            "word_count": s.get("word_count", 0),
            "has_content": s.get("has_content", False),
            "reviewed": ss.get("reviewed", False),
            "status": ss.get("status", "draft"),
            "rules_check": ss.get("rules_check", {}),
        })

    # PRL word budgets
    budgets = {"abstract": 250, "introduction": 600, "methods": 800, "results": 1200, "conclusions": 400}

    return {
        "sections": section_list,
        "total_words": total_words,
        "section_count": sum(1 for s in section_list if s["has_content"]),
        "reviewed_count": sum(1 for s in section_list if s["reviewed"]),
        "budgets": budgets,
        "updated_at": state.get("updated_at"),
        "progress_pct": state.get("progress_pct", 0),
    }


def build_git_status() -> dict[str, Any]:
    """Collect git status for monitoring in the dashboard."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5", "--format=%h %ai %s"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        log_lines = result.stdout.strip().split("\n") if result.returncode == 0 else []
    except Exception:
        log_lines = []

    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        latest_tag = result.stdout.strip() if result.returncode == 0 else "none"
    except Exception:
        latest_tag = "error"

    try:
        result = subprocess.run(
            ["git", "status", "--short", "--branch"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        status_line = result.stdout.strip().split("\n")[0] if result.returncode == 0 else "unknown"
    except Exception:
        status_line = "error"

    # Parse ahead/behind
    ahead = 0
    behind = 0
    if "ahead" in status_line:
        m = __import__("re").search(r"ahead\s+(\d+)", status_line)
        if m:
            ahead = int(m.group(1))
    if "behind" in status_line:
        m = __import__("re").search(r"behind\s+(\d+)", status_line)
        if m:
            behind = int(m.group(1))

    synced = (ahead == 0 and behind == 0 and "origin" in status_line)

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
        remote_url = result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        remote_url = ""

    return {
        "branch": "master",
        "latest_tag": latest_tag,
        "latest_commit": log_lines[0] if log_lines else "",
        "recent_commits": log_lines[:5],
        "ahead": ahead,
        "behind": behind,
        "synced": synced,
        "remote": remote_url.replace("https://github.com/", "").replace(".git", "") if remote_url else "",
        "status_line": status_line,
    }


def build_dashboard_data() -> dict[str, Any]:
    ensure_workflow_files()
    switches = load_json(SWITCHES_PATH, DEFAULT_SWITCHES)
    profile = load_json(REVIEWER_PROFILE_PATH, DEFAULT_REVIEWER_PROFILE)
    eureka_corpus = load_literature_corpus()
    display_policy = profile.get("dashboard_display", DEFAULT_REVIEWER_PROFILE["dashboard_display"])
    featured_min_score = float(display_policy.get("featured_min_score", 75.0))
    raw_by_case = collect_raw_files()
    latest_reports = load_latest_review_reports()

    runs: list[dict[str, Any]] = []
    for outdir in sorted(discover_output_dirs(), key=lambda p: p.as_posix()):
        run = summarize_run(outdir)
        run["review"] = compute_reviewer_score(run["metrics"], profile)
        run["review"] = apply_eureka_training_to_review(run["metrics"], run["review"], eureka_corpus)
        runs.append(run)

    cases_by_id: dict[str, dict[str, Any]] = {}
    for raw_case_id, files in raw_by_case.items():
        cases_by_id.setdefault(
            raw_case_id,
            {
                "case_id": raw_case_id,
                "display_name": raw_case_id,
                "raw_files": [],
                "runs": [],
            },
        )["raw_files"].extend(files)

    for run in runs:
        case_id = run["case_id"]
        case = cases_by_id.setdefault(
            case_id,
            {
                "case_id": case_id,
                "display_name": run["display_name"],
                "raw_files": [],
                "runs": [],
            },
        )
        case["display_name"] = run["display_name"]
        case["runs"].append(run)

    switch_cases = switches.setdefault("cases", {}) if isinstance(switches, dict) else {}
    cases = []
    for case_id, case in cases_by_id.items():
        best_run = choose_best_run(case["runs"])
        case_switch = switch_cases.get(case_id, {})
        status = "raw_only"
        if best_run:
            status = "processed"
            review = best_run.get("review", {})
            needs_review = bool(
                review.get("missing_score_inputs")
                or review.get("flags")
                or review.get("band") in {"needs_review", "low_confidence", "usable_review"}
            )
            if needs_review and not case_switch.get("confirmed"):
                status = "needs_review"
        if case_switch.get("paused"):
            status = "paused"
        case["status"] = status
        case["best_run_id"] = best_run["run_id"] if best_run else None
        case["best_score"] = best_run["review"]["reviewer_score"] if best_run else None
        case["best_preview"] = best_run["assets"]["preview_image"] if best_run else None
        case["metrics"] = best_run["metrics"] if best_run else {}
        case["review"] = best_run["review"] if best_run else None
        case["switches"] = case_switch
        case["agent_recommendation"] = latest_reports.get(case_id)
        case["eureka"] = build_eureka_case(case, eureka_corpus)
        case["featured"] = bool(best_run and (case["best_score"] or 0) >= featured_min_score)
        case["run_count"] = len(case["runs"])
        cases.append(case)

    cases.sort(key=lambda item: (item.get("best_score") is None, -(item.get("best_score") or 0), item["case_id"]))
    write_eureka_profile(eureka_corpus, len(cases))

    summary = {
        "case_count": len(cases),
        "run_count": len(runs),
        "processed_count": sum(1 for c in cases if c["status"] in {"processed", "needs_review"}),
        "raw_only_count": sum(1 for c in cases if c["status"] == "raw_only"),
        "paused_count": sum(1 for c in cases if c["status"] == "paused"),
        "featured_count": sum(1 for c in cases if c.get("featured")),
        "top_case": cases[0]["display_name"] if cases else None,
    }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "base_dir": str(BASE_DIR),
        "schema_version": 1,
        "summary": summary,
        "agents": AGENT_ROSTER,
        "history": build_history_payload(runs, cases),
        "phase_space": build_phase_space_payload(
            cases,
            eureka_corpus.get("research_digest", {}).get("group_meeting_summary", {}).get("phase_candidates", []),
        ),
        "eureka": eureka_corpus.get("summary", {}),
        "eureka_research": eureka_corpus.get("research_digest", {}),
        "showcase": build_showcase_payload(cases, eureka_corpus.get("research_digest", {}), summary),
        "manuscript": build_manuscript_draft(cases, eureka_corpus.get("research_digest", {})),
        "paper_sections": build_paper_sections_payload(),
        "paper_figures": _load_json_file(PRL_FIGURE_INDEX_PATH, []),
        "git": build_git_status(),
        "reviewer_profile": profile,
        "switches": switches,
        "cases": cases,
        "runs": runs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Antibubble dashboard metadata.")
    parser.add_argument(
        "--output",
        default=str(DASHBOARD_DIR / "dashboard_data.json"),
        help="Output JSON path.",
    )
    args = parser.parse_args()

    payload = build_dashboard_data()
    output = Path(args.output)
    write_json(output, payload)
    print(f"Wrote {output}")
    print(
        f"Cases: {payload['summary']['case_count']} | "
        f"Runs: {payload['summary']['run_count']} | "
        f"Processed: {payload['summary']['processed_count']}"
    )


if __name__ == "__main__":
    main()
