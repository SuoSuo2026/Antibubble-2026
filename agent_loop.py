from __future__ import annotations

import argparse
import copy
import json
import math
import re
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from analysis import apply_valid_frame_window, compute_kinematics, results_to_dict, run_enabled_advanced_analysis
from config_loader import load_config
from dashboard_builder import (
    BASE_DIR,
    DASHBOARD_DIR,
    RAW_DIR,
    REVIEWER_PROFILE_PATH,
    SWITCHES_PATH,
    WORKFLOW_DIR,
    build_dashboard_data,
    compute_reviewer_score,
    slugify,
    write_json,
)
from eureka_agent import apply_eureka_training_to_review, load_literature_corpus
from franklin_memory import apply_memory_to_review, remember_intake
from main import (
    run_tracking_pipeline,
    run_tracking_preview_pipeline,
    run_video_export_pipeline,
    run_visualization_pipeline,
)
from rigid_ball_processing import run_rigid_ball_case


STATE_PATH = WORKFLOW_DIR / "agent_loop_state.json"
CASE_REGISTRY_PATH = WORKFLOW_DIR / "case_registry.json"
REVIEW_REPORT_DIR = WORKFLOW_DIR / "reviewer_reports"
INTAKE_DIR = WORKFLOW_DIR / "intake"
DEFAULT_OUTPUT_SUFFIX = "auto_agent"
LOOP_AGENT_NAME = "Sisyphus"


DEFAULT_CASE_REGISTRY = {
    "version": 1,
    "description": "Optional per-case overrides for the automatic agent loop.",
    "defaults": {
        "auto_process": True,
        "require_experience_before_processing": True,
        "mark_default_roi_as_assumption": True,
        "mark_default_valid_frame_range_as_assumption": True,
    },
    "cases": {},
}


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def ensure_loop_files() -> None:
    WORKFLOW_DIR.mkdir(parents=True, exist_ok=True)
    REVIEW_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    INTAKE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_PATH.exists():
        write_json(
            STATE_PATH,
            {
                "version": 1,
                "created_at": now_iso(),
                "updated_at": now_iso(),
                "files": {},
                "events": [],
            },
        )
    if not CASE_REGISTRY_PATH.exists():
        write_json(CASE_REGISTRY_PATH, DEFAULT_CASE_REGISTRY)


def tiff_files() -> list[Path]:
    if not RAW_DIR.exists():
        return []
    return sorted(
        [
            path
            for path in RAW_DIR.rglob("*")
            if path.is_file() and path.suffix.lower() in {".tif", ".tiff"}
        ],
        key=lambda p: p.as_posix().lower(),
    )


def fingerprint(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtime_iso": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


def append_event(state: dict[str, Any], event: dict[str, Any]) -> None:
    event = {"time": now_iso(), **event}
    state.setdefault("events", []).append(event)
    state["events"] = state["events"][-200:]
    state["updated_at"] = now_iso()


def finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def parse_number(text: str) -> float | None:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if not match:
        return None
    return float(match.group(0))


def parse_scale_text(text: str) -> float | None:
    """
    Return pixel_per_mm.

    Accepts examples:
    - 32
    - 32 px/mm
    - 60mm/1920pixel
    - 1920px/60mm
    - 0.03125 mm/px
    """
    text = (text or "").strip().lower()
    if not text:
        return None

    if "/" in text and ("mm" in text) and any(unit in text for unit in ["px", "pixel", "pixels"]):
        left, right = text.split("/", 1)
        left_num = parse_number(left)
        right_num = parse_number(right)
        if left_num and right_num:
            left_is_mm = "mm" in left
            right_is_mm = "mm" in right
            left_is_px = any(unit in left for unit in ["px", "pixel", "pixels"])
            right_is_px = any(unit in right for unit in ["px", "pixel", "pixels"])
            if left_is_mm and right_is_px:
                return right_num / left_num
            if left_is_px and right_is_mm:
                return left_num / right_num

    number = parse_number(text)
    if number is None:
        return None
    if "mm/px" in text or "mm per px" in text or "mm_per_pixel" in text:
        return 1.0 / number if number > 0 else None
    return number


def parse_rigid_radius_text(text: str, pixel_per_mm: float | None) -> dict[str, float]:
    text = (text or "").strip().lower()
    if not text:
        return {}
    numbers = [float(item) for item in re.findall(r"[-+]?\d+(?:\.\d+)?", text)]
    if not numbers:
        return {}

    is_mm = "mm" in text and not any(unit in text for unit in ["px", "pixel", "pixels"])
    if len(numbers) >= 2:
        lo, hi = min(numbers[0], numbers[1]), max(numbers[0], numbers[1])
        if is_mm and pixel_per_mm:
            lo *= pixel_per_mm
            hi *= pixel_per_mm
        return {"min_radius_px": lo, "max_radius_px": hi}

    value = numbers[0]
    if is_mm and pixel_per_mm:
        value *= pixel_per_mm
    return {
        "min_radius_px": max(1.0, value * 0.5),
        "max_radius_px": max(2.0, value * 1.8),
    }


def safe_nanmean(values: Any) -> float | None:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or np.all(np.isnan(arr)):
        return None
    return float(np.nanmean(arr))


def safe_nanstd(values: Any) -> float | None:
    arr = np.asarray(values, dtype=float)
    if arr.size == 0 or np.all(np.isnan(arr)):
        return None
    return float(np.nanstd(arr))


def build_context(
    tiff_path: Path,
    case_id: str,
    registry: dict[str, Any],
    switches: dict[str, Any],
    intake: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    config = copy.deepcopy(load_config())
    case_override = copy.deepcopy(registry.get("cases", {}).get(case_id, {}))
    if intake:
        for key in ["roi", "valid_frame_range", "fps", "pixel_per_mm", "mm_per_pixel", "motion_axis"]:
            if intake.get(key) not in (None, "", []):
                case_override[key] = intake[key]
    assumptions = []

    output_dir = BASE_DIR / "processed_data" / case_id / f"{case_id}_{DEFAULT_OUTPUT_SUFFIX}"
    config["data"]["tiff_path"] = str(tiff_path)
    config["data"]["output_dir"] = str(output_dir)

    if "roi" in case_override:
        config["roi"] = case_override["roi"]
    elif registry.get("defaults", {}).get("mark_default_roi_as_assumption", True):
        assumptions.append("using_default_roi_from_config")

    if "valid_frame_range" in case_override:
        config["experiment"]["valid_frame_range"] = case_override["valid_frame_range"]
    elif registry.get("defaults", {}).get("mark_default_valid_frame_range_as_assumption", True):
        assumptions.append("using_default_valid_frame_range_from_config")

    for key in ["fps", "pixel_per_mm", "mm_per_pixel", "motion_axis"]:
        if key in case_override:
            config["experiment"][key] = case_override[key]

    method = switches.get("default_method", {})
    method.update(switches.get("cases", {}).get(case_id, {}))
    config["tracking"]["refine_thin_connections"] = bool(
        method.get("tracking_refinement", config["tracking"].get("refine_thin_connections", True))
    )
    config["oscillation"]["use_quad_osc_fit"] = bool(
        method.get("use_quad_osc_fit", config["oscillation"].get("use_quad_osc_fit", True))
    )
    config["video_export"]["enabled"] = bool(method.get("export_video", config["video_export"].get("enabled", False)))
    config["video_export"]["filename"] = f"{case_id}_{DEFAULT_OUTPUT_SUFFIX}_monitor.mp4"
    config["video_export"]["frame_range_mode"] = "valid"
    config["video_export"]["crop_to_roi"] = True
    config["visualization"]["preview_sample_count"] = int(config["visualization"].get("preview_sample_count", 6))

    roi = config["roi"]
    if "scale_bar_y" in config["video_export"]:
        config["video_export"]["scale_bar_y"] = min(int(config["video_export"]["scale_bar_y"]), max(1, int(roi["h"]) - 20))

    return (
        {
            "config": config,
            "data_cfg": config["data"],
            "exp_cfg": config["experiment"],
            "kin_cfg": config["kinematics"],
            "fit_cfg": config["fit"],
            "osc_cfg": config["oscillation"],
            "vis_cfg": config["visualization"],
            "video_cfg": config["video_export"],
            "tiff_path": tiff_path,
            "output_dir": output_dir,
            "roi": (roi["x"], roi["y"], roi["w"], roi["h"]),
        },
        assumptions,
    )


def clamp_valid_frame_range(context: dict[str, Any], result_count: int, assumptions: list[str]) -> None:
    raw_range = context["exp_cfg"].get("valid_frame_range", [0, result_count - 1])
    f0 = int(max(0, raw_range[0]))
    f1 = int(min(result_count - 1, raw_range[1]))
    if f1 < f0:
        f0, f1 = 0, max(0, result_count - 1)
        assumptions.append("valid_frame_range_reset_to_full_stack")
    if [f0, f1] != list(raw_range):
        assumptions.append("valid_frame_range_clamped_to_stack")
    context["exp_cfg"]["valid_frame_range"] = [f0, f1]
    context["config"]["experiment"]["valid_frame_range"] = [f0, f1]


def summarize_case(case_name: str, context: dict[str, Any], analysis_outputs: dict[str, Any], assumptions: list[str]) -> dict[str, Any]:
    valid_data = analysis_outputs["valid_data"]
    found = np.asarray(valid_data["found"], dtype=float)
    valid_found_ratio = safe_nanmean(found)
    pixel_per_mm = finite_float(context["exp_cfg"].get("pixel_per_mm"))

    radius_mean = radius_std = radius_rel = None
    if pixel_per_mm and pixel_per_mm > 0:
        radius_mm = np.asarray(valid_data["radius_volume_eq_px"], dtype=float) / pixel_per_mm
        radius_mean = safe_nanmean(radius_mm)
        radius_std = safe_nanstd(radius_mm)
        if radius_mean and radius_std is not None:
            radius_rel = 100.0 * radius_std / radius_mean

    advanced = analysis_outputs["advanced_outputs"]
    quad_osc = advanced.get("quad_osc_fit") or {}
    robust = advanced.get("quadratic_fit_robust_summary") or {}
    acc_fft = advanced.get("acceleration_fft") or {}

    metrics = {
        "case": case_name,
        "case_id": slugify(case_name),
        "output_dir": str(context["output_dir"].resolve()),
        "raw_tiff_path": str(context["tiff_path"].resolve()),
        "processed_by": LOOP_AGENT_NAME,
        "processed_at": now_iso(),
        "assumptions": sorted(set(assumptions)),
        "valid_frame_range": list(context["exp_cfg"]["valid_frame_range"]),
        "roi": {
            "x": context["config"]["roi"]["x"],
            "y": context["config"]["roi"]["y"],
            "w": context["config"]["roi"]["w"],
            "h": context["config"]["roi"]["h"],
        },
        "valid_found_ratio": valid_found_ratio,
        "radius_mean_mm": radius_mean,
        "radius_std_mm": radius_std,
        "radius_rel_std_percent": radius_rel,
        "a_fit_osc_mean_mm_s2": finite_float(quad_osc.get("a_fit")),
        "a_fit_osc_std_mm_s2": None,
        "freq_mean_hz": finite_float(quad_osc.get("freq_hz")),
        "freq_std_hz": None,
        "residual_rms_mean_mm": finite_float(quad_osc.get("residual_rms")),
        "r2": finite_float(quad_osc.get("r2")),
        "a_quad_mean_mm_s2": finite_float(robust.get("a_fit_mean")),
        "a_quad_std_mm_s2": finite_float(robust.get("a_fit_std")),
        "n_fits": robust.get("n_fits"),
        "acc_fft_freq_hz": finite_float(acc_fft.get("freq")),
    }
    return metrics


def save_processing_outputs(case_name: str, context: dict[str, Any], metrics: dict[str, Any]) -> None:
    outdir = context["output_dir"]
    write_json(outdir / "case_summary.json", metrics)

    final_metrics = {
        "case": case_name,
        "figure": str((outdir / "valid_window_tracking_preview.png").resolve()),
        "a_fit_osc_mean_mm_s2": metrics.get("a_fit_osc_mean_mm_s2"),
        "a_fit_osc_std_mm_s2": metrics.get("a_fit_osc_std_mm_s2"),
        "radius_mean_mm": metrics.get("radius_mean_mm"),
        "radius_std_mm": metrics.get("radius_std_mm"),
        "radius_rel_std_percent": metrics.get("radius_rel_std_percent"),
        "freq_mean_hz": metrics.get("freq_mean_hz"),
        "freq_std_hz": metrics.get("freq_std_hz"),
        "processed_by": LOOP_AGENT_NAME,
        "assumptions": metrics.get("assumptions", []),
    }
    write_json(outdir / "group_meeting_final_metrics.json", final_metrics)


def recommend_next_action(metrics: dict[str, Any], review: dict[str, Any]) -> str:
    eureka_notes = review.get("eureka_training_notes") or []
    if eureka_notes:
        return eureka_notes[0]
    memory_recommendations = review.get("memory_recommendations") or []
    if memory_recommendations:
        return memory_recommendations[0]
    flags = set(review.get("flags", []))
    assumptions = set(metrics.get("assumptions", []))
    if "using_default_roi_from_config" in assumptions:
        return "先人工确认 ROI；如果目标不在默认窗口内，请在 agent_workspace/case_registry.json 为该 case_id 写入 roi 后重跑。"
    if "using_default_valid_frame_range_from_config" in assumptions:
        return "先人工确认有效帧范围；建议在 case_registry.json 写入 valid_frame_range，让主 agent 用确定窗口重跑。"
    if "tracking_incomplete" in flags:
        return "优先调 tracking 参数或 ROI，目标是 valid_found_ratio >= 0.98。"
    if "radius_unstable" in flags:
        return "复核分割是否混入邻近液滴或边界；必要时缩小 ROI 或调 refine 参数。"
    if "fit_window_sensitive" in flags:
        return "扩大参数扫描或缩短拟合窗口，比较不同 smooth_window 的 a_fit 稳定性。"
    if "frequency_unavailable" in flags or "frequency_unstable" in flags:
        return "不要直接引用频率结论；先看 geometry/acceleration FFT，再决定是否启用振荡拟合。"
    if review.get("reviewer_score", 0) >= 85:
        return "结果可进入候选高分集；下一步可做人工图像复核或导出汇报图。"
    return "结果可用但建议人工复核预览图、半径曲线和拟合残差。"


def save_review_report(case_id: str, metrics: dict[str, Any], intake: dict[str, Any] | None = None) -> dict[str, Any]:
    memory_write = remember_intake(case_id, intake)
    profile = load_json(REVIEWER_PROFILE_PATH, {})
    review = compute_reviewer_score(metrics, profile)
    review = apply_eureka_training_to_review(metrics, review, load_literature_corpus())
    review = apply_memory_to_review(case_id, metrics, review)
    report = {
        "case_id": case_id,
        "loop_agent": LOOP_AGENT_NAME,
        "reviewer_agent": "Franklin",
        "literature_agent": "Eureka",
        "created_at": now_iso(),
        "reviewer_score": review["reviewer_score"],
        "reviewer_score_before_memory": review.get("reviewer_score_before_memory"),
        "memory_score_adjustment": review.get("memory_score_adjustment", 0.0),
        "band": review.get("band"),
        "flags": review.get("flags", []),
        "score_parts": review.get("score_parts", {}),
        "score_inputs": review.get("score_inputs", {}),
        "assumptions": metrics.get("assumptions", []),
        "subjective_experience": (intake or {}).get("subjective_experience", ""),
        "review_criteria": (intake or {}).get("review_criteria", ""),
        "memory_write": memory_write,
        "memory_matches": review.get("memory_matches", {}),
        "memory_recommendations": review.get("memory_recommendations", []),
        "eureka_score_adjustment": review.get("eureka_score_adjustment", 0.0),
        "reviewer_score_before_eureka": review.get("reviewer_score_before_eureka"),
        "eureka_training_notes": review.get("eureka_training_notes", []),
        "eureka_applied_rules": review.get("eureka_applied_rules", []),
        "eureka_training": review.get("eureka_training", {}),
        "recommended_next_action": recommend_next_action(metrics, review),
        "main_agent_patch_request": {
            "parameter_changes": {},
            "code_changes_needed": [],
        },
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REVIEW_REPORT_DIR / f"{case_id}_{timestamp}.json"
    latest_path = REVIEW_REPORT_DIR / f"{case_id}_latest.json"
    write_json(report_path, report)
    write_json(latest_path, report)
    return {"path": str(report_path), "latest_path": str(latest_path), "report": report}


def intake_path(case_id: str) -> Path:
    return INTAKE_DIR / f"{case_id}.json"


def latest_rigid_fast_defaults(current_case_id: str | None = None) -> dict[str, Any]:
    state = load_json(STATE_PATH, {"files": {}})
    records = list(state.get("files", {}).values())
    records.sort(key=lambda item: item.get("finished_at") or item.get("updated_at") or "", reverse=True)
    for record in records:
        if record.get("status") != "reviewed":
            continue
        if current_case_id and record.get("case_id") == current_case_id:
            continue
        output_dir = record.get("output_dir")
        if not output_dir:
            continue
        summary_path = Path(output_dir) / "case_summary.json"
        if not summary_path.exists():
            continue
        summary = load_json(summary_path, {})
        if str(summary.get("experiment_type", "")).lower() != "rigid_ball":
            continue
        defaults = {
            "experiment_type": "rigid_ball",
            "fps": summary.get("fps"),
            "pixel_per_mm": summary.get("pixel_per_mm"),
            "inherited_from_case_id": summary.get("case_id") or record.get("case_id"),
        }
        return {key: value for key, value in defaults.items() if value not in (None, "", [])}
    return {"experiment_type": "rigid_ball"}


def fast_intake(path: Path, case_id: str, subjective_experience: str, review_criteria: str = "") -> dict[str, Any]:
    inherited = latest_rigid_fast_defaults(current_case_id=case_id)
    assumptions = []
    if inherited.get("inherited_from_case_id"):
        assumptions.append(f"fast_inherited_parameters_from_{inherited['inherited_from_case_id']}")
    else:
        assumptions.append("fast_no_previous_rigid_case_found_using_config_defaults")
    intake = {
        "case_id": case_id,
        "raw_tiff_path": str(path.resolve()),
        "created_at": now_iso(),
        "ready_to_process": True,
        "fast": True,
        "experiment_type": inherited.get("experiment_type", "rigid_ball"),
        "subjective_experience": subjective_experience,
        "review_criteria": review_criteria,
        "roi": None,
        "valid_frame_range": None,
        "fps": inherited.get("fps"),
        "pixel_per_mm": inherited.get("pixel_per_mm"),
        "rigid_ball": {},
        "assumptions": assumptions,
    }
    write_json(intake_path(case_id), intake)
    return intake


def create_intake_template(path: Path, case_id: str) -> Path:
    payload = {
        "case_id": case_id,
        "raw_tiff_path": str(path.resolve()),
        "created_at": now_iso(),
        "ready_to_process": False,
        "experiment_type": "rigid_ball",
        "subjective_experience": "",
        "review_criteria": "",
        "roi": None,
        "valid_frame_range": None,
        "fps": None,
        "pixel_per_mm": None,
        "rigid_ball": {
            "min_radius_px": None,
            "max_radius_px": None,
            "threshold_mode": "otsu",
            "manual_threshold": None,
            "export_video": True,
        },
        "notes": [
            "Set ready_to_process to true after adding any subjective notes.",
            "experiment_type can be rigid_ball or antibubble.",
            "Optional roi format: {\"x\": 0, \"y\": 100, \"w\": 1920, \"h\": 360}",
            "Optional valid_frame_range format: [start_frame, end_frame]",
        ],
    }
    target = intake_path(case_id)
    if not target.exists():
        write_json(target, payload)
    return target


def load_intake(case_id: str) -> dict[str, Any] | None:
    path = intake_path(case_id)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def prompt_intake(path: Path, case_id: str) -> dict[str, Any]:
    print("")
    print("=" * 72)
    print(f"New TIFF detected: {path.name}")
    print("Before processing, add subjective experience for Franklin-style review.")
    print("Type FAST at the first prompt if this case is same as previous experiments.")
    print("Leave fields blank if unknown. Type SKIP at the final confirmation to wait.")
    print("=" * 72)

    subjective = input("Subjective experience / phenomenon notes (or FAST): ").strip()
    if subjective.upper() == "FAST":
        return fast_intake(path, case_id, "FAST: same as previous rigid ball experiments.")

    criteria = input("Extra review criteria for this case: ").strip()
    experiment_type = input("Experiment type [rigid_ball/antibubble] (blank = rigid_ball): ").strip() or "rigid_ball"
    fps_text = input("FPS (blank = config default; FAST = immediate process): ").strip()
    if fps_text.upper() == "FAST":
        intake = fast_intake(path, case_id, subjective or "FAST: same as previous experiment.", criteria)
        intake["experiment_type"] = experiment_type
        write_json(intake_path(case_id), intake)
        return intake
    scale_text = input("Scale, e.g. 60mm/1920pixel, 1920px/60mm, 32 px/mm (blank = config default): ").strip()
    valid_range_text = input("Valid frame range, e.g. 160,275 (blank = auto for rigid_ball): ").strip()
    roi_text = input("ROI x,y,w,h, e.g. 0,120,1920,320 (blank = auto for rigid_ball): ").strip()
    ball_radius_text = input("Rigid ball radius/range, e.g. 8,80 px or about 2mm (blank = auto defaults): ").strip()
    confirmation = input("Type PROCESS to start, or SKIP to wait: ").strip().upper()

    intake = {
        "case_id": case_id,
        "raw_tiff_path": str(path.resolve()),
        "created_at": now_iso(),
        "ready_to_process": confirmation == "PROCESS",
        "experiment_type": experiment_type,
        "subjective_experience": subjective,
        "review_criteria": criteria,
        "roi": None,
        "valid_frame_range": None,
        "fps": None,
        "pixel_per_mm": None,
        "rigid_ball": {},
    }
    if fps_text:
        intake["fps"] = float(fps_text)
    if scale_text:
        parsed_scale = parse_scale_text(scale_text)
        if parsed_scale is None:
            raise ValueError(f"Could not parse scale text: {scale_text!r}")
        intake["pixel_per_mm"] = parsed_scale
    if valid_range_text:
        values = [int(v.strip()) for v in valid_range_text.split(",")]
        if len(values) == 2:
            intake["valid_frame_range"] = values
    if roi_text:
        values = [int(v.strip()) for v in roi_text.split(",")]
        if len(values) == 4:
            intake["roi"] = {"x": values[0], "y": values[1], "w": values[2], "h": values[3]}
    intake["rigid_ball"].update(parse_rigid_radius_text(ball_radius_text, intake.get("pixel_per_mm")))
    write_json(intake_path(case_id), intake)
    return intake


def intake_ready(path: Path, case_id: str, mode: str) -> tuple[bool, dict[str, Any] | None, Path | None]:
    if mode == "off":
        return True, None, None
    if mode == "prompt":
        intake = prompt_intake(path, case_id)
        return bool(intake.get("ready_to_process")), intake, intake_path(case_id)
    template_path = create_intake_template(path, case_id)
    intake = load_intake(case_id)
    return bool(intake and intake.get("ready_to_process")), intake, template_path


def process_tiff(tiff_path: Path, case_id: str, intake: dict[str, Any] | None = None) -> dict[str, Any]:
    registry = load_json(CASE_REGISTRY_PATH, DEFAULT_CASE_REGISTRY)
    switches = load_json(SWITCHES_PATH, {"default_method": {}, "cases": {}})

    case_override = copy.deepcopy(registry.get("cases", {}).get(case_id, {}))
    if intake:
        for key in [
            "experiment_type",
            "roi",
            "valid_frame_range",
            "fps",
            "pixel_per_mm",
            "mm_per_pixel",
            "motion_axis",
            "rigid_ball",
        ]:
            if intake.get(key) not in (None, "", []):
                case_override[key] = intake[key]

    experiment_type = str(case_override.get("experiment_type", "antibubble")).strip().lower()
    if experiment_type in {"rigid", "rigid_ball", "solid_ball", "hard_sphere", "sphere"}:
        base_config = load_config()
        assumptions = []
        if "roi" in case_override:
            roi = case_override["roi"]
        else:
            roi = None
            assumptions.append("auto_roi_selected_by_rigid_ball_pipeline")
        if "valid_frame_range" in case_override:
            valid_frame_range = case_override["valid_frame_range"]
        else:
            valid_frame_range = None
            assumptions.append("auto_valid_frame_range_selected_by_rigid_ball_pipeline")
        fps = float(case_override.get("fps", base_config["experiment"].get("fps", 2000.0)))
        pixel_per_mm = case_override.get("pixel_per_mm", base_config["experiment"].get("pixel_per_mm"))
        rigid_cfg = copy.deepcopy(case_override.get("rigid_ball", {}))
        output_dir = BASE_DIR / "processed_data" / case_id / f"{case_id}_rigid_ball_auto"
        metrics = run_rigid_ball_case(
            tiff_path=tiff_path,
            output_dir=output_dir,
            roi=roi,
            valid_frame_range=valid_frame_range,
            fps=fps,
            pixel_per_mm=pixel_per_mm,
            rigid_cfg=rigid_cfg,
            subjective_experience=(intake or {}).get("subjective_experience", ""),
            review_criteria=(intake or {}).get("review_criteria", ""),
        )
        metrics["assumptions"] = sorted(set(metrics.get("assumptions", []) + assumptions + (intake or {}).get("assumptions", [])))
        metrics["experiment_type"] = "rigid_ball"
        write_json(output_dir / "case_summary.json", metrics)
        review_result = save_review_report(case_id, metrics, intake=intake)
        dashboard_payload = build_dashboard_data()
        write_json(DASHBOARD_DIR / "dashboard_data.json", dashboard_payload)
        return {
            "case_id": case_id,
            "output_dir": str(output_dir),
            "metrics": metrics,
            "review": review_result["report"],
            "review_report_path": review_result["path"],
        }

    context, assumptions = build_context(tiff_path, case_id, registry, switches, intake=intake)
    context["output_dir"].mkdir(parents=True, exist_ok=True)

    tracking_outputs = run_tracking_pipeline(context)
    clamp_valid_frame_range(context, len(tracking_outputs["results"]), assumptions)
    run_tracking_preview_pipeline(context, tracking_outputs)

    results_dict = results_to_dict(tracking_outputs["results"])
    valid_data = apply_valid_frame_window(results_dict, tuple(context["exp_cfg"]["valid_frame_range"]))
    kin = compute_kinematics(
        data=valid_data,
        fps=context["exp_cfg"]["fps"],
        motion_axis=context["exp_cfg"]["motion_axis"],
        smooth_window=context["kin_cfg"]["smooth_window"],
        pixel_per_mm=context["exp_cfg"]["pixel_per_mm"],
    )
    analysis_outputs = {
        "results_dict": results_dict,
        "valid_data": valid_data,
        "kin": kin,
        "advanced_outputs": run_enabled_advanced_analysis(
            data=valid_data,
            kin=kin,
            exp_cfg=context["exp_cfg"],
            kin_cfg=context["kin_cfg"],
            fit_cfg=context["fit_cfg"],
            osc_cfg=context["osc_cfg"],
        ),
    }

    run_visualization_pipeline(context, tracking_outputs, analysis_outputs)
    if context["video_cfg"].get("enabled", False):
        run_video_export_pipeline(context, tracking_outputs)

    case_name = tiff_path.stem
    metrics = summarize_case(case_name, context, analysis_outputs, assumptions)
    if intake:
        metrics["subjective_experience"] = intake.get("subjective_experience", "")
        metrics["review_criteria"] = intake.get("review_criteria", "")
    save_processing_outputs(case_name, context, metrics)
    review_result = save_review_report(case_id, metrics, intake=intake)

    dashboard_payload = build_dashboard_data()
    write_json(DASHBOARD_DIR / "dashboard_data.json", dashboard_payload)

    return {
        "case_id": case_id,
        "output_dir": str(context["output_dir"]),
        "metrics": metrics,
        "review": review_result["report"],
        "review_report_path": review_result["path"],
    }


def mark_seen_without_processing(state: dict[str, Any], path: Path) -> None:
    rel = path.relative_to(BASE_DIR).as_posix()
    state.setdefault("files", {})[rel] = {
        "fingerprint": fingerprint(path),
        "status": "seen_existing",
        "case_id": slugify(path.stem),
        "updated_at": now_iso(),
    }


def handle_file(state: dict[str, Any], path: Path, dry_run: bool = False, intake: dict[str, Any] | None = None) -> None:
    rel = path.relative_to(BASE_DIR).as_posix()
    case_id = slugify(path.stem)
    file_record = {
        "fingerprint": fingerprint(path),
        "status": "queued",
        "case_id": case_id,
        "updated_at": now_iso(),
    }
    state.setdefault("files", {})[rel] = file_record
    append_event(state, {"type": "queued", "path": rel, "case_id": case_id})
    write_json(STATE_PATH, state)

    if dry_run:
        file_record["status"] = "dry_run_queued"
        file_record["updated_at"] = now_iso()
        append_event(state, {"type": "dry_run_queued", "path": rel, "case_id": case_id})
        write_json(STATE_PATH, state)
        return

    try:
        file_record["status"] = "processing"
        file_record["started_at"] = now_iso()
        write_json(STATE_PATH, state)
        result = process_tiff(path, case_id, intake=intake)
        file_record.update(
            {
                "status": "reviewed",
                "finished_at": now_iso(),
                "output_dir": result["output_dir"],
                "reviewer_score": result["review"]["reviewer_score"],
                "review_band": result["review"].get("band"),
                "review_flags": result["review"].get("flags", []),
                "recommended_next_action": result["review"].get("recommended_next_action"),
                "review_report_path": result["review_report_path"],
            }
        )
        append_event(
            state,
            {
                "type": "reviewed",
                "path": rel,
                "case_id": case_id,
                "reviewer_score": result["review"]["reviewer_score"],
            },
        )
    except Exception as exc:  # noqa: BLE001 - long-running agent loop must survive one bad case.
        file_record.update(
            {
                "status": "failed",
                "finished_at": now_iso(),
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        append_event(state, {"type": "failed", "path": rel, "case_id": case_id, "error": str(exc)})
    finally:
        file_record["updated_at"] = now_iso()
        write_json(STATE_PATH, state)


def scan_once(
    state: dict[str, Any],
    process_existing: bool,
    dry_run: bool,
    min_file_age: float,
    intake_mode: str,
) -> int:
    count = 0
    now = time.time()
    initializing = not bool(state.get("initialized_at")) and not process_existing
    for path in tiff_files():
        rel = path.relative_to(BASE_DIR).as_posix()
        if rel in state.get("files", {}):
            record = state["files"][rel]
            if record.get("status") == "awaiting_experience":
                ready, intake, intake_file = intake_ready(path, record.get("case_id", slugify(path.stem)), "file")
                if ready:
                    handle_file(state, path, dry_run=dry_run, intake=intake)
                    count += 1
                elif intake_file:
                    record["intake_path"] = str(intake_file)
                    write_json(STATE_PATH, state)
            if process_existing and state["files"][rel].get("status") == "seen_existing":
                ready, intake, intake_file = intake_ready(path, slugify(path.stem), intake_mode)
                if not ready:
                    state["files"][rel]["status"] = "awaiting_experience"
                    state["files"][rel]["intake_path"] = str(intake_file) if intake_file else None
                    state["files"][rel]["updated_at"] = now_iso()
                    append_event(state, {"type": "awaiting_experience", "path": rel, "case_id": slugify(path.stem)})
                    write_json(STATE_PATH, state)
                else:
                    handle_file(state, path, dry_run=dry_run, intake=intake)
                    count += 1
            continue
        age = now - path.stat().st_mtime
        if age < min_file_age:
            continue
        if initializing:
            mark_seen_without_processing(state, path)
            append_event(state, {"type": "seen_existing", "path": rel, "case_id": slugify(path.stem)})
            continue
        ready, intake, intake_file = intake_ready(path, slugify(path.stem), intake_mode)
        if not ready:
            state.setdefault("files", {})[rel] = {
                "fingerprint": fingerprint(path),
                "status": "awaiting_experience",
                "case_id": slugify(path.stem),
                "intake_path": str(intake_file) if intake_file else None,
                "updated_at": now_iso(),
            }
            append_event(state, {"type": "awaiting_experience", "path": rel, "case_id": slugify(path.stem)})
            write_json(STATE_PATH, state)
            continue
        handle_file(state, path, dry_run=dry_run, intake=intake)
        count += 1
    write_json(STATE_PATH, state)
    if initializing:
        state["initialized_at"] = now_iso()
        write_json(STATE_PATH, state)
    dashboard_payload = build_dashboard_data()
    write_json(DASHBOARD_DIR / "dashboard_data.json", dashboard_payload)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch raw_data for new TIFF files and run the local agent loop.")
    parser.add_argument("--poll-interval", type=float, default=15.0, help="Seconds between scans.")
    parser.add_argument("--min-file-age", type=float, default=5.0, help="Wait this many seconds after a TIFF changes before processing it.")
    parser.add_argument("--once", action="store_true", help="Run one scan and exit.")
    parser.add_argument(
        "--process-existing",
        action="store_true",
        help="Process files that are already in raw_data and not recorded in the loop state.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Queue new files without running the heavy processing pipeline.")
    parser.add_argument(
        "--intake-mode",
        choices=["file", "prompt", "off"],
        default="file",
        help="How to collect subjective experience before processing new files.",
    )
    args = parser.parse_args()

    ensure_loop_files()
    state = load_json(STATE_PATH, {})
    print("Agent loop ready.")
    print(f"Watching: {RAW_DIR}")
    print(f"State: {STATE_PATH}")
    print("Press Ctrl+C to stop.")

    while True:
        state = load_json(STATE_PATH, {})
        processed = scan_once(
            state,
            process_existing=args.process_existing,
            dry_run=args.dry_run,
            min_file_age=args.min_file_age,
            intake_mode=args.intake_mode,
        )
        if processed:
            print(f"[{now_iso()}] handled {processed} new TIFF file(s).")
        if args.once:
            break
        time.sleep(max(1.0, args.poll_interval))


if __name__ == "__main__":
    main()
