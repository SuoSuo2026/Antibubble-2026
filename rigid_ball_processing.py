from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import matplotlib.pyplot as plt
import numpy as np

from image_utils import crop_roi, draw_roi_on_frame, estimate_background, normalize_to_uint8
from io_utils import read_tiff_stack


@dataclass
class BallResult:
    frame_idx: int
    found: bool
    cx: float = np.nan
    cy: float = np.nan
    radius_px: float = np.nan
    area_px2: float = np.nan
    circularity: float = np.nan
    score: float = np.nan
    major_axis_px: float = np.nan
    minor_axis_px: float = np.nan
    aspect_ratio: float = np.nan
    ellipse_angle_deg: float = np.nan
    ellipse_cx: float = np.nan
    ellipse_cy: float = np.nan
    shape_radius_px: float = np.nan


DEFAULT_RIGID_CONFIG = {
    "background_sample_count": 25,
    "threshold_mode": "otsu",
    "manual_threshold": 25,
    "morph_kernel_size": 5,
    "min_radius_px": 4,
    "max_radius_px": 300,
    "min_area_px2": 20,
    "min_circularity": 0.45,
    "max_center_jump_px": 160,
    "prefer_dark_on_bright": None,
    "preview_sample_count": 6,
    "export_video": True,
    "video_fps_out": 30.0,
    "auto_roi": True,
    "auto_valid_frame_range": True,
    "auto_roi_paddings": [30, 60, 100],
    "auto_valid_max_gap": 3,
    "core_trim_enabled": True,
    "core_window_min_frames": 12,
    "core_radius_rel_std_max": 2.5,
    "core_velocity_zscore_max": 3.5,
    "track_window_context_frames": 0,
    "candidate_edge_margin_fraction": 0.08,
    "candidate_edge_penalty": 260.0,
    "candidate_centerline_y_fraction": 0.68,
    "candidate_centerline_penalty_weight": 0.06,
    "auto_guarded_roi_enabled": True,
    "auto_guarded_roi_left_fraction": 0.16,
    "auto_guarded_roi_right_fraction": 0.94,
    "auto_guarded_roi_top_fraction": 0.07,
    "auto_guarded_roi_bottom_fraction": 0.90,
    "primary_axis": "x",
    "derivative_fit_order": 3,
    "derivative_smooth_window": 9,
    "perspective_correction_enabled": False,
    "perspective_radius_fit_order": 2,
    "perspective_reference_radius": "median_fit",
    "perspective_min_radius_rel_improvement": 0.15,
    "focus_radius_correction_enabled": True,
    "focus_radius_axis": "primary",
    "focus_radius_coord_px": None,
    "focus_radius_coord_mm": None,
    "focus_camera_distance_px": None,
    "focus_camera_distance_mm": None,
    "focus_camera_distance_auto": True,
    "focus_camera_distance_span_ratio_min": 0.6,
    "focus_camera_distance_span_ratio_max": 120.0,
    "focus_cosine_max_angle_rad": 1.2,
    "focus_cosine_min_raw_radius_rel_percent": 1.0,
    "focus_cosine_max_raw_radius_rel_percent": 20.0,
    "focus_cosine_min_radius_rel_improvement": 0.15,
    "focus_cosine_apply_to_centers": False,
}


MATERIALS = ("PMMA", "POM", "PP", "PS")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def infer_material_from_name(name: str) -> str | None:
    upper = Path(name).stem.upper()
    tokens = [token for token in re_split_material_tokens(upper) if token]
    for material in MATERIALS:
        if material in tokens:
            return material
    for material in MATERIALS:
        if material in upper:
            return material
    return None


def re_split_material_tokens(text: str) -> list[str]:
    import re

    return re.split(r"[^A-Z0-9]+", text)


def merged_rigid_config(config: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(DEFAULT_RIGID_CONFIG)
    if config:
        merged.update({k: v for k, v in config.items() if v is not None})
    return merged


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not np.isfinite(out):
        return None
    return out


def build_motion_mask(frame_roi: np.ndarray, background_roi: np.ndarray, cfg: dict[str, Any]) -> np.ndarray:
    diff_raw = np.abs(frame_roi.astype(np.float32) - background_roi.astype(np.float32))
    diff = normalize_to_uint8(diff_raw)

    if cfg["threshold_mode"] == "manual":
        _, mask = cv2.threshold(diff, int(cfg["manual_threshold"]), 255, cv2.THRESH_BINARY)
    else:
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    k = max(1, int(cfg["morph_kernel_size"]))
    if k % 2 == 0:
        k += 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    return mask


def contour_candidates(mask: np.ndarray, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < float(cfg["min_area_px2"]):
            continue
        perimeter = float(cv2.arcLength(contour, True))
        if perimeter <= 0:
            continue
        (cx, cy), radius = cv2.minEnclosingCircle(contour)
        radius = float(radius)
        if radius < float(cfg["min_radius_px"]) or radius > float(cfg["max_radius_px"]):
            continue
        circularity = float(4.0 * np.pi * area / (perimeter * perimeter))
        if circularity < float(cfg["min_circularity"]):
            continue
        major_axis = np.nan
        minor_axis = np.nan
        aspect_ratio = np.nan
        ellipse_angle = np.nan
        ellipse_cx = np.nan
        ellipse_cy = np.nan
        shape_radius = np.nan
        if len(contour) >= 5:
            (ecx, ecy), (axis_a, axis_b), angle = cv2.fitEllipse(contour)
            major_axis = float(max(axis_a, axis_b))
            minor_axis = float(min(axis_a, axis_b))
            if minor_axis > 0:
                aspect_ratio = float(major_axis / minor_axis)
                shape_radius = float(np.sqrt(major_axis * minor_axis) / 2.0)
            ellipse_angle = float(angle)
            ellipse_cx = float(ecx)
            ellipse_cy = float(ecy)
        out.append(
            {
                "cx": float(cx),
                "cy": float(cy),
                "radius_px": radius,
                "area_px2": area,
                "circularity": circularity,
                "major_axis_px": major_axis,
                "minor_axis_px": minor_axis,
                "aspect_ratio": aspect_ratio,
                "ellipse_angle_deg": ellipse_angle,
                "ellipse_cx": ellipse_cx,
                "ellipse_cy": ellipse_cy,
                "shape_radius_px": shape_radius,
            }
        )
    return out


def choose_candidate(
    candidates: list[dict[str, Any]],
    prev: BallResult | None,
    cfg: dict[str, Any],
    roi_shape: tuple[int, int] | None = None,
) -> dict[str, Any] | None:
    if not candidates:
        return None
    scored = []
    max_jump = float(cfg["max_center_jump_px"])
    roi_h = roi_shape[0] if roi_shape else None
    roi_w = roi_shape[1] if roi_shape else None
    for item in candidates:
        score = -item["area_px2"] * 0.01 - item["circularity"] * 20.0
        if roi_h and roi_w:
            y_edge_margin = float(cfg.get("candidate_edge_margin_fraction", 0.08)) * float(roi_h)
            x_edge_margin = float(cfg.get("candidate_edge_margin_fraction", 0.08)) * float(roi_w)
            if (
                item["cy"] < y_edge_margin
                or item["cy"] > float(roi_h) - y_edge_margin
                or item["cx"] < x_edge_margin
                or item["cx"] > float(roi_w) - x_edge_margin
            ):
                score += float(cfg.get("candidate_edge_penalty", 260.0))
            centerline_y = float(cfg.get("candidate_centerline_y_fraction", 0.68)) * float(roi_h)
            score += float(cfg.get("candidate_centerline_penalty_weight", 0.06)) * abs(item["cy"] - centerline_y)
        if prev and prev.found:
            jump = float(np.hypot(item["cx"] - prev.cx, item["cy"] - prev.cy))
            score += jump
            if jump > max_jump:
                score += 1000.0 + jump
            if np.isfinite(prev.radius_px) and prev.radius_px > 0:
                score += 40.0 * abs(np.log(max(item["radius_px"], 1e-6) / prev.radius_px))
        item = dict(item)
        item["score"] = float(score)
        scored.append(item)
    scored.sort(key=lambda x: x["score"])
    return scored[0]


def track_rigid_ball(stack: np.ndarray, roi: tuple[int, int, int, int], cfg: dict[str, Any]) -> tuple[list[BallResult], np.ndarray]:
    stack_roi = np.stack([crop_roi(frame, roi) for frame in stack], axis=0)
    background_roi = estimate_background(stack_roi, int(cfg["background_sample_count"]))
    results: list[BallResult] = []
    prev: BallResult | None = None
    x0, y0, _, _ = roi

    for frame_idx, frame_roi in enumerate(stack_roi):
        mask = build_motion_mask(frame_roi, background_roi, cfg)
        candidates = contour_candidates(mask, cfg)
        selected = choose_candidate(candidates, prev, cfg, roi_shape=frame_roi.shape[:2])
        if selected is None:
            result = BallResult(frame_idx=frame_idx, found=False)
        else:
            result = BallResult(
                frame_idx=frame_idx,
                found=True,
                cx=selected["cx"] + x0,
                cy=selected["cy"] + y0,
                radius_px=selected["radius_px"],
                area_px2=selected["area_px2"],
                circularity=selected["circularity"],
                score=selected["score"],
                major_axis_px=selected.get("major_axis_px", np.nan),
                minor_axis_px=selected.get("minor_axis_px", np.nan),
                aspect_ratio=selected.get("aspect_ratio", np.nan),
                ellipse_angle_deg=selected.get("ellipse_angle_deg", np.nan),
                ellipse_cx=selected.get("ellipse_cx", np.nan) + x0
                if np.isfinite(selected.get("ellipse_cx", np.nan))
                else np.nan,
                ellipse_cy=selected.get("ellipse_cy", np.nan) + y0
                if np.isfinite(selected.get("ellipse_cy", np.nan))
                else np.nan,
                shape_radius_px=selected.get("shape_radius_px", np.nan),
            )
            prev = result
        results.append(result)

    return results, background_roi


def valid_slice(results: list[BallResult], frame_range: list[int] | tuple[int, int] | None) -> list[BallResult]:
    if not results:
        return []
    if frame_range is None:
        f0, f1 = 0, len(results) - 1
    else:
        f0, f1 = int(frame_range[0]), int(frame_range[1])
    f0 = max(0, f0)
    f1 = min(len(results) - 1, f1)
    return results[f0 : f1 + 1]


def results_arrays(results: list[BallResult], fps: float, pixel_per_mm: float | None) -> dict[str, np.ndarray]:
    frame = np.array([r.frame_idx for r in results], dtype=float)
    found = np.array([r.found for r in results], dtype=bool)
    cx = np.array([r.cx for r in results], dtype=float)
    cy = np.array([r.cy for r in results], dtype=float)
    radius_px = np.array([r.radius_px for r in results], dtype=float)
    major_axis_px = np.array([r.major_axis_px for r in results], dtype=float)
    minor_axis_px = np.array([r.minor_axis_px for r in results], dtype=float)
    aspect_ratio = np.array([r.aspect_ratio for r in results], dtype=float)
    shape_radius_px = np.array([r.shape_radius_px for r in results], dtype=float)
    t = frame / fps
    scale = pixel_per_mm if pixel_per_mm and pixel_per_mm > 0 else None
    if scale:
        x = cx / scale
        y = cy / scale
        radius = radius_px / scale
        major_axis = major_axis_px / scale
        minor_axis = minor_axis_px / scale
        shape_radius = shape_radius_px / scale
        unit = "mm"
    else:
        x = cx.copy()
        y = cy.copy()
        radius = radius_px.copy()
        major_axis = major_axis_px.copy()
        minor_axis = minor_axis_px.copy()
        shape_radius = shape_radius_px.copy()
        unit = "px"
    return {
        "frame": frame,
        "t": t,
        "found": found,
        "x": x,
        "y": y,
        "radius": radius,
        "radius_px": radius_px,
        "major_axis": major_axis,
        "minor_axis": minor_axis,
        "major_axis_px": major_axis_px,
        "minor_axis_px": minor_axis_px,
        "aspect_ratio": aspect_ratio,
        "shape_radius": shape_radius,
        "shape_radius_px": shape_radius_px,
        "unit": np.array(unit),
    }


def radius_rel_std(results: list[BallResult], pixel_per_mm: float | None = None) -> float | None:
    radius = np.array([r.radius_px for r in results if r.found and np.isfinite(r.radius_px)], dtype=float)
    if pixel_per_mm and pixel_per_mm > 0:
        radius = radius / pixel_per_mm
    if len(radius) < 3:
        return None
    mean = float(np.nanmean(radius))
    std = float(np.nanstd(radius))
    if not np.isfinite(mean) or abs(mean) <= 1e-12:
        return None
    return safe_float(100.0 * std / mean)


def rel_std_values(values: np.ndarray) -> float | None:
    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    if len(finite) < 3:
        return None
    mean = float(np.nanmean(finite))
    std = float(np.nanstd(finite))
    if not np.isfinite(mean) or abs(mean) <= 1e-12:
        return None
    return safe_float(100.0 * std / mean)


def radius_source_for_correction(core: list[BallResult]) -> tuple[np.ndarray, str]:
    enclosing_radius = np.array([r.radius_px for r in core], dtype=float)
    shape_radius = np.array([r.shape_radius_px for r in core], dtype=float)
    use_shape_radius = len(shape_radius) and np.mean(np.isfinite(shape_radius)) >= 0.8
    if use_shape_radius:
        radius = np.where(np.isfinite(shape_radius), shape_radius, enclosing_radius)
        return radius, "ellipse_shape_radius_sqrt_ab_over_2"
    return enclosing_radius, "min_enclosing_circle"


def estimate_focus_coord_from_min_radius(q: np.ndarray, radius: np.ndarray) -> tuple[float | None, str, dict[str, Any]]:
    valid = np.isfinite(q) & np.isfinite(radius) & (radius > 0)
    if np.sum(valid) < 6:
        return None, "too_few_valid_points", {}
    qv = np.asarray(q[valid], dtype=float)
    rv = np.asarray(radius[valid], dtype=float)
    q_min = float(np.nanmin(qv))
    q_max = float(np.nanmax(qv))
    span = q_max - q_min
    if not np.isfinite(span) or span <= 1e-9:
        return None, "insufficient_coordinate_span", {}

    raw_focus = float(qv[int(np.nanargmin(rv))])
    raw_edge_fraction = min(abs(raw_focus - q_min), abs(q_max - raw_focus)) / span
    info: dict[str, Any] = {
        "raw_min_focus_coord": raw_focus,
        "raw_min_edge_fraction": safe_float(raw_edge_fraction),
    }

    if len(qv) >= 8:
        q0 = float(np.nanmedian(qv))
        qn = (qv - q0) / span
        try:
            coeffs = np.polyfit(qn, rv, 2)
        except np.linalg.LinAlgError:
            coeffs = None
        if coeffs is not None and np.all(np.isfinite(coeffs)) and coeffs[0] > 0:
            focus_n = -float(coeffs[1]) / (2.0 * float(coeffs[0]))
            focus = q0 + focus_n * span
            edge_fraction = min(abs(focus - q_min), abs(q_max - focus)) / span
            info.update(
                {
                    "quadratic_min_focus_coord": safe_float(focus),
                    "quadratic_min_edge_fraction": safe_float(edge_fraction),
                    "quadratic_coeffs": [float(c) for c in coeffs],
                }
            )
            if q_min <= focus <= q_max and edge_fraction >= 0.08:
                return safe_float(focus), "quadratic_min_radius", info

    if raw_edge_fraction < 0.08:
        return None, "radius_minimum_at_edge", info
    return raw_focus, "raw_min_radius", info


def focus_coord_value(cfg: dict[str, Any], unit: str, pixel_per_mm: float | None) -> tuple[float | None, str | None]:
    focus_mm = safe_float(cfg.get("focus_radius_coord_mm"))
    focus_px = safe_float(cfg.get("focus_radius_coord_px"))
    if unit == "mm":
        if focus_mm is not None:
            return focus_mm, "manual_mm"
        if focus_px is not None and pixel_per_mm and pixel_per_mm > 0:
            return focus_px / pixel_per_mm, "manual_px_converted_to_mm"
    else:
        if focus_px is not None:
            return focus_px, "manual_px"
        if focus_mm is not None and pixel_per_mm and pixel_per_mm > 0:
            return focus_mm * pixel_per_mm, "manual_mm_converted_to_px"
    return None, None


def camera_distance_value(cfg: dict[str, Any], unit: str, pixel_per_mm: float | None) -> tuple[float | None, str | None]:
    distance_mm = safe_float(cfg.get("focus_camera_distance_mm"))
    distance_px = safe_float(cfg.get("focus_camera_distance_px"))
    if unit == "mm":
        if distance_mm is not None:
            return distance_mm, "manual_mm"
        if distance_px is not None and pixel_per_mm and pixel_per_mm > 0:
            return distance_px / pixel_per_mm, "manual_px_converted_to_mm"
    else:
        if distance_px is not None:
            return distance_px, "manual_px"
        if distance_mm is not None and pixel_per_mm and pixel_per_mm > 0:
            return distance_mm * pixel_per_mm, "manual_mm_converted_to_px"
    return None, None


def cosine_radius_rel(radius: np.ndarray, q: np.ndarray, focus_coord: float, distance: float) -> float | None:
    if not np.isfinite(distance) or distance <= 0:
        return None
    angle = (q - focus_coord) / distance
    factor = np.cos(angle)
    if not np.all(np.isfinite(factor)) or np.nanmin(factor) <= 0:
        return None
    return rel_std_values(radius * factor)


def auto_camera_distance(
    radius: np.ndarray,
    q: np.ndarray,
    focus_coord: float,
    cfg: dict[str, Any],
) -> tuple[float | None, float | None, dict[str, Any]]:
    valid = np.isfinite(radius) & np.isfinite(q) & (radius > 0)
    if np.sum(valid) < 6:
        return None, None, {"reason": "too_few_valid_points"}
    rv = np.asarray(radius[valid], dtype=float)
    qv = np.asarray(q[valid], dtype=float)
    span = float(np.nanmax(qv) - np.nanmin(qv))
    max_delta = float(np.nanmax(np.abs(qv - focus_coord)))
    if not np.isfinite(span) or span <= 1e-9 or not np.isfinite(max_delta) or max_delta <= 1e-9:
        return None, None, {"reason": "insufficient_coordinate_span"}

    max_angle = max(0.05, float(cfg.get("focus_cosine_max_angle_rad", 1.2)))
    low = max(max_delta / max_angle, span * float(cfg.get("focus_camera_distance_span_ratio_min", 0.6)), 1e-6)
    high = max(
        low * 1.2,
        span * float(cfg.get("focus_camera_distance_span_ratio_max", 120.0)),
        max_delta * float(cfg.get("focus_camera_distance_span_ratio_max", 120.0)),
    )
    candidates = np.geomspace(low, high, 220)
    best_distance = None
    best_rel = None
    for distance in candidates:
        rel = cosine_radius_rel(rv, qv, focus_coord, float(distance))
        if rel is None:
            continue
        if best_rel is None or rel < best_rel:
            best_rel = rel
            best_distance = float(distance)
    return best_distance, best_rel, {"search_low": safe_float(low), "search_high": safe_float(high), "candidate_count": len(candidates)}


def focus_cosine_correct_results(
    results: list[BallResult],
    frame_range: list[int],
    cfg: dict[str, Any],
    pixel_per_mm: float | None,
) -> tuple[list[BallResult], dict[str, Any]]:
    f0, f1 = int(frame_range[0]), int(frame_range[1])
    core = [
        r
        for r in results
        if f0 <= r.frame_idx <= f1 and r.found and np.isfinite(r.cx) and np.isfinite(r.cy) and np.isfinite(r.radius_px)
    ]
    raw_rel = radius_rel_std(core, pixel_per_mm)
    min_raw_rel = float(cfg.get("focus_cosine_min_raw_radius_rel_percent", 1.0))
    max_raw_rel = float(cfg.get("focus_cosine_max_raw_radius_rel_percent", 20.0))
    if raw_rel is not None and raw_rel < min_raw_rel:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": "radius_already_stable",
            "raw_radius_rel_std_percent": raw_rel,
            "min_raw_radius_rel_std_percent": min_raw_rel,
        }
    if raw_rel is not None and raw_rel > max_raw_rel:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": "raw_radius_too_unstable_for_projection_model",
            "raw_radius_rel_std_percent": raw_rel,
            "max_raw_radius_rel_std_percent": max_raw_rel,
        }
    if len(core) < 12:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": "too_few_valid_points",
            "raw_radius_rel_std_percent": raw_rel,
        }

    axis_cfg = str(cfg.get("focus_radius_axis", "primary")).lower()
    if axis_cfg == "primary":
        axis_cfg = str(cfg.get("primary_axis", "x")).lower()
    axis = axis_cfg if axis_cfg in {"x", "y"} else "x"
    q_px = np.array([r.cx if axis == "x" else r.cy for r in core], dtype=float)
    unit = "mm" if pixel_per_mm and pixel_per_mm > 0 else "px"
    q = q_px / pixel_per_mm if unit == "mm" else q_px.copy()
    radius, radius_source = radius_source_for_correction(core)

    focus_coord, focus_source = focus_coord_value(cfg, unit, pixel_per_mm)
    focus_info: dict[str, Any] = {}
    if focus_coord is None:
        focus_coord, focus_source, focus_info = estimate_focus_coord_from_min_radius(q, radius)
    if focus_coord is None:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": focus_source or "focus_not_found",
            "raw_radius_rel_std_percent": raw_rel,
            "focus_estimation": focus_info,
        }

    distance, distance_source = camera_distance_value(cfg, unit, pixel_per_mm)
    trial_rel = None
    distance_info: dict[str, Any] = {}
    if distance is None:
        if not bool(cfg.get("focus_camera_distance_auto", True)):
            return results, {
                "enabled": True,
                "applied": False,
                "model": "focus_cosine_radius_correction",
                "reason": "camera_distance_missing",
                "raw_radius_rel_std_percent": raw_rel,
                "focus_coord": safe_float(focus_coord),
                "focus_coord_unit": unit,
            }
        distance, trial_rel, distance_info = auto_camera_distance(radius, q, focus_coord, cfg)
        distance_source = "auto_fit_radius_cv"
    if distance is None or not np.isfinite(distance) or distance <= 0:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": "invalid_camera_distance",
            "raw_radius_rel_std_percent": raw_rel,
            "focus_coord": safe_float(focus_coord),
            "focus_coord_unit": unit,
            "distance_estimation": distance_info,
        }
    if trial_rel is None:
        trial_rel = cosine_radius_rel(radius, q, focus_coord, distance)
    if trial_rel is None:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": "invalid_cosine_factor",
            "raw_radius_rel_std_percent": raw_rel,
            "focus_coord": safe_float(focus_coord),
            "focus_coord_unit": unit,
            "camera_distance": safe_float(distance),
            "camera_distance_unit": unit,
        }

    corrected: list[BallResult] = []
    factors = []
    apply_to_centers = bool(cfg.get("focus_cosine_apply_to_centers", False))
    for result in results:
        item = BallResult(**asdict(result))
        if item.found and np.isfinite(item.cx) and np.isfinite(item.cy) and np.isfinite(item.radius_px):
            q_item_px = float(item.cx if axis == "x" else item.cy)
            q_item = q_item_px / pixel_per_mm if unit == "mm" else q_item_px
            factor = float(np.cos((q_item - focus_coord) / distance))
            if np.isfinite(factor) and factor > 0:
                item.radius_px = float(item.radius_px) * factor
                item.area_px2 = float(item.area_px2) * factor**2 if np.isfinite(item.area_px2) else item.area_px2
                item.major_axis_px = (
                    float(item.major_axis_px) * factor if np.isfinite(item.major_axis_px) else item.major_axis_px
                )
                item.minor_axis_px = (
                    float(item.minor_axis_px) * factor if np.isfinite(item.minor_axis_px) else item.minor_axis_px
                )
                item.shape_radius_px = (
                    float(item.shape_radius_px) * factor if np.isfinite(item.shape_radius_px) else item.shape_radius_px
                )
                if apply_to_centers:
                    if axis == "x":
                        item.cx = focus_coord * (pixel_per_mm if unit == "mm" else 1.0) + (
                            float(item.cx) - focus_coord * (pixel_per_mm if unit == "mm" else 1.0)
                        ) * factor
                    else:
                        item.cy = focus_coord * (pixel_per_mm if unit == "mm" else 1.0) + (
                            float(item.cy) - focus_coord * (pixel_per_mm if unit == "mm" else 1.0)
                        ) * factor
                factors.append(factor)
        corrected.append(item)

    corrected_core = [r for r in corrected if f0 <= r.frame_idx <= f1 and r.found]
    corrected_rel = radius_rel_std(corrected_core, pixel_per_mm)
    improvement = None
    if raw_rel is not None and corrected_rel is not None and raw_rel > 0:
        improvement = safe_float((raw_rel - corrected_rel) / raw_rel)
    min_improvement = float(cfg.get("focus_cosine_min_radius_rel_improvement", 0.15))
    if improvement is not None and improvement < min_improvement:
        return results, {
            "enabled": True,
            "applied": False,
            "model": "focus_cosine_radius_correction",
            "reason": "radius_stability_improvement_too_small",
            "raw_radius_rel_std_percent": raw_rel,
            "trial_corrected_radius_rel_std_percent": corrected_rel,
            "trial_improvement_fraction": improvement,
            "focus_coord": safe_float(focus_coord),
            "focus_coord_unit": unit,
            "camera_distance": safe_float(distance),
            "camera_distance_unit": unit,
            "distance_source": distance_source,
        }

    return corrected, {
        "enabled": True,
        "applied": True,
        "model": "focus_cosine_radius_correction",
        "formula": "R_corrected = R_raw * cos((q - q_focus) / L)",
        "axis": axis,
        "unit": unit,
        "radius_source": radius_source,
        "focus_coord": safe_float(focus_coord),
        "focus_coord_unit": unit,
        "focus_source": focus_source,
        "focus_estimation": focus_info,
        "camera_distance": safe_float(distance),
        "camera_distance_unit": unit,
        "distance_source": distance_source,
        "distance_estimation": distance_info,
        "raw_radius_rel_std_percent": raw_rel,
        "trial_radius_rel_std_percent": trial_rel,
        "corrected_radius_rel_std_percent": corrected_rel,
        "radius_rel_improvement_fraction": improvement,
        "cos_factor_min": safe_float(np.nanmin(factors)) if factors else None,
        "cos_factor_max": safe_float(np.nanmax(factors)) if factors else None,
        "apply_to_centers": apply_to_centers,
    }


def perspective_correct_results(
    results: list[BallResult],
    frame_range: list[int],
    cfg: dict[str, Any],
    pixel_per_mm: float | None,
) -> tuple[list[BallResult], dict[str, Any]]:
    f0, f1 = int(frame_range[0]), int(frame_range[1])
    core = [r for r in results if f0 <= r.frame_idx <= f1 and r.found and np.isfinite(r.cx) and np.isfinite(r.radius_px)]
    raw_rel = radius_rel_std(core, pixel_per_mm)
    if len(core) < 12:
        return results, {"enabled": True, "applied": False, "reason": "too_few_valid_points", "raw_radius_rel_std_percent": raw_rel}

    x = np.array([r.cx for r in core], dtype=float)
    y = np.array([r.cy for r in core], dtype=float)
    enclosing_radius = np.array([r.radius_px for r in core], dtype=float)
    shape_radius = np.array([r.shape_radius_px for r in core], dtype=float)
    use_shape_radius = np.mean(np.isfinite(shape_radius)) >= 0.8
    radius = np.where(np.isfinite(shape_radius), shape_radius, enclosing_radius) if use_shape_radius else enclosing_radius
    x0 = float(np.nanmedian(x))
    span = float(np.nanmax(x) - np.nanmin(x))
    if not np.isfinite(span) or span <= 1e-6:
        return results, {"enabled": True, "applied": False, "reason": "insufficient_x_span", "raw_radius_rel_std_percent": raw_rel}

    order = min(int(cfg.get("perspective_radius_fit_order", 2)), max(1, len(core) - 3))
    xn = (x - x0) / span
    coeffs = np.polyfit(xn, radius, order)
    fit_radius = np.polyval(coeffs, xn)
    if not np.all(np.isfinite(fit_radius)) or np.nanmin(fit_radius) <= 0:
        return results, {"enabled": True, "applied": False, "reason": "invalid_radius_fit", "raw_radius_rel_std_percent": raw_rel}

    reference_mode = str(cfg.get("perspective_reference_radius", "median_fit")).lower()
    if reference_mode == "min_fit":
        ref_radius = float(np.nanmin(fit_radius))
    else:
        ref_radius = float(np.nanmedian(fit_radius))
    if not np.isfinite(ref_radius) or ref_radius <= 0:
        return results, {"enabled": True, "applied": False, "reason": "invalid_reference_radius", "raw_radius_rel_std_percent": raw_rel}

    y0 = float(np.nanmedian(y))
    corrected: list[BallResult] = []
    for result in results:
        item = BallResult(**asdict(result))
        if item.found and np.isfinite(item.cx) and np.isfinite(item.cy) and np.isfinite(item.radius_px):
            local_xn = (float(item.cx) - x0) / span
            local_fit_radius = float(np.polyval(coeffs, local_xn))
            if np.isfinite(local_fit_radius) and local_fit_radius > 0:
                scale_correction = ref_radius / local_fit_radius
                item.cx = x0 + (float(item.cx) - x0) * scale_correction
                item.cy = y0 + (float(item.cy) - y0) * scale_correction
                item.radius_px = float(item.radius_px) * scale_correction
                item.area_px2 = float(item.area_px2) * scale_correction**2 if np.isfinite(item.area_px2) else item.area_px2
                item.major_axis_px = (
                    float(item.major_axis_px) * scale_correction if np.isfinite(item.major_axis_px) else item.major_axis_px
                )
                item.minor_axis_px = (
                    float(item.minor_axis_px) * scale_correction if np.isfinite(item.minor_axis_px) else item.minor_axis_px
                )
                item.shape_radius_px = (
                    float(item.shape_radius_px) * scale_correction if np.isfinite(item.shape_radius_px) else item.shape_radius_px
                )
                item.ellipse_cx = (
                    x0 + (float(item.ellipse_cx) - x0) * scale_correction
                    if np.isfinite(item.ellipse_cx)
                    else item.ellipse_cx
                )
                item.ellipse_cy = (
                    y0 + (float(item.ellipse_cy) - y0) * scale_correction
                    if np.isfinite(item.ellipse_cy)
                    else item.ellipse_cy
                )
        corrected.append(item)

    corrected_core = [r for r in corrected if f0 <= r.frame_idx <= f1 and r.found]
    corrected_rel = radius_rel_std(corrected_core, pixel_per_mm)
    improvement = None
    if raw_rel is not None and corrected_rel is not None and raw_rel > 0:
        improvement = safe_float((raw_rel - corrected_rel) / raw_rel)
    min_improvement = float(cfg.get("perspective_min_radius_rel_improvement", 0.15))
    if improvement is not None and improvement < min_improvement:
        return results, {
            "enabled": True,
            "applied": False,
            "reason": "radius_stability_improvement_too_small",
            "raw_radius_rel_std_percent": raw_rel,
            "trial_corrected_radius_rel_std_percent": corrected_rel,
            "trial_improvement_fraction": improvement,
        }

    return corrected, {
        "enabled": True,
        "applied": True,
        "model": "radius_vs_x_magnification",
        "radius_source": "ellipse_shape_radius_sqrt_ab_over_2" if use_shape_radius else "min_enclosing_circle",
        "radius_fit_order": int(order),
        "radius_fit_coeffs": [float(c) for c in coeffs],
        "x_center_px": x0,
        "y_center_px": y0,
        "x_span_px": span,
        "reference_radius_px": ref_radius,
        "raw_radius_rel_std_percent": raw_rel,
        "corrected_radius_rel_std_percent": corrected_rel,
        "radius_rel_improvement_fraction": improvement,
    }


def interpolate_nan(t: np.ndarray, y: np.ndarray) -> np.ndarray:
    out = y.astype(float).copy()
    valid = np.isfinite(out)
    if np.sum(valid) >= 2:
        out[~valid] = np.interp(t[~valid], t[valid], out[valid])
    return out


def fit_poly(t: np.ndarray, y: np.ndarray, order: int) -> dict[str, Any] | None:
    valid = np.isfinite(t) & np.isfinite(y)
    if np.sum(valid) < order + 3:
        return None
    tt = t[valid]
    yy = y[valid]
    coeffs = np.polyfit(tt, yy, order)
    pred = np.polyval(coeffs, tt)
    residual = yy - pred
    ss_res = float(np.sum(residual**2))
    ss_tot = float(np.sum((yy - np.mean(yy)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan
    return {
        "coeffs": [float(c) for c in coeffs],
        "r2": safe_float(r2),
        "residual_rms": float(np.sqrt(np.mean(residual**2))),
        "t_fit": tt,
        "y_fit": yy,
        "pred": pred,
    }


def moving_average_reflect(y: np.ndarray, window: int) -> np.ndarray:
    y = y.astype(float)
    if window <= 1 or len(y) < 3:
        return y.copy()
    if window % 2 == 0:
        window += 1
    window = min(window, len(y) if len(y) % 2 == 1 else len(y) - 1)
    if window < 3:
        return y.copy()
    pad = window // 2
    padded = np.pad(y, pad_width=pad, mode="edge")
    kernel = np.ones(window, dtype=float) / window
    return np.convolve(padded, kernel, mode="valid")


def smooth_position_and_derivatives(
    t: np.ndarray,
    q: np.ndarray,
    fit_order: int = 3,
    smooth_window: int = 9,
) -> dict[str, np.ndarray | str | list[float] | None]:
    q_interp = interpolate_nan(t, q)
    valid = np.isfinite(t) & np.isfinite(q_interp)
    if np.sum(valid) < 5:
        v = np.gradient(q_interp, t) if len(t) >= 2 else np.full_like(t, np.nan)
        a = np.gradient(v, t) if len(t) >= 3 else np.full_like(t, np.nan)
        return {
            "q_smooth": q_interp,
            "v_smooth": v,
            "a_smooth": a,
            "method": "gradient_fallback",
            "coeffs": None,
        }

    order = min(int(fit_order), max(1, int(np.sum(valid)) - 2))
    if order >= 2:
        coeffs = np.polyfit(t[valid], q_interp[valid], order)
        q_smooth = np.polyval(coeffs, t)
        d1 = np.polyder(coeffs, 1)
        d2 = np.polyder(coeffs, 2)
        v_smooth = np.polyval(d1, t)
        a_smooth = np.polyval(d2, t)
        return {
            "q_smooth": q_smooth,
            "v_smooth": v_smooth,
            "a_smooth": a_smooth,
            "method": f"polyfit_order_{order}",
            "coeffs": [float(c) for c in coeffs],
        }

    q_smooth = moving_average_reflect(q_interp, int(smooth_window))
    v_smooth = np.gradient(q_smooth, t) if len(t) >= 2 else np.full_like(t, np.nan)
    v_smooth = moving_average_reflect(v_smooth, int(smooth_window))
    a_smooth = np.gradient(v_smooth, t) if len(t) >= 3 else np.full_like(t, np.nan)
    a_smooth = moving_average_reflect(a_smooth, int(smooth_window))
    return {
        "q_smooth": q_smooth,
        "v_smooth": v_smooth,
        "a_smooth": a_smooth,
        "method": f"moving_average_{smooth_window}",
        "coeffs": None,
    }


def estimate_bounces(t: np.ndarray, q: np.ndarray, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = merged_rigid_config(cfg)
    q_interp = interpolate_nan(t, q)
    if len(t) < 7 or not np.all(np.isfinite(q_interp)):
        return {"bounce_count": 0, "events": []}
    deriv = smooth_position_and_derivatives(
        t,
        q_interp,
        fit_order=int(cfg.get("derivative_fit_order", 3)),
        smooth_window=int(cfg.get("derivative_smooth_window", 9)),
    )
    v = np.asarray(deriv["v_smooth"], dtype=float)
    events = []
    for i in range(2, len(v) - 2):
        if v[i - 1] > 0 and v[i + 1] < 0:
            before = float(np.nanmedian(v[max(0, i - 4) : i]))
            after = float(np.nanmedian(v[i + 1 : min(len(v), i + 5)]))
            restitution = abs(after / before) if before != 0 else np.nan
            events.append(
                {
                    "frame_index": int(i),
                    "time_s": float(t[i]),
                    "v_before": before,
                    "v_after": after,
                    "restitution_estimate": safe_float(restitution),
                }
            )
    return {"bounce_count": len(events), "events": events[:10]}


def analyze_motion(
    results: list[BallResult],
    fps: float,
    pixel_per_mm: float | None,
    cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = merged_rigid_config(cfg)
    arr = results_arrays(results, fps=fps, pixel_per_mm=pixel_per_mm)
    t = arr["t"]
    x = arr["x"]
    y = arr["y"]
    found = arr["found"]
    unit = str(arr["unit"])

    x_range = float(np.nanmax(x) - np.nanmin(x)) if np.any(np.isfinite(x)) else 0.0
    y_range = float(np.nanmax(y) - np.nanmin(y)) if np.any(np.isfinite(y)) else 0.0
    configured_axis = str(cfg.get("primary_axis", "x")).lower()
    primary_axis = configured_axis if configured_axis in {"x", "y"} else ("x" if x_range >= y_range else "y")

    x_deriv = smooth_position_and_derivatives(
        t,
        x,
        fit_order=int(cfg.get("derivative_fit_order", 3)),
        smooth_window=int(cfg.get("derivative_smooth_window", 9)),
    )
    y_deriv = smooth_position_and_derivatives(
        t,
        y,
        fit_order=int(cfg.get("derivative_fit_order", 3)),
        smooth_window=int(cfg.get("derivative_smooth_window", 9)),
    )
    vx = np.asarray(x_deriv["v_smooth"], dtype=float)
    vy = np.asarray(y_deriv["v_smooth"], dtype=float)
    ax = np.asarray(x_deriv["a_smooth"], dtype=float)
    ay = np.asarray(y_deriv["a_smooth"], dtype=float)

    fit_x = fit_poly(t, x, 1)
    fit_y = fit_poly(t, y, 2)
    primary_values = x if primary_axis == "x" else y
    primary_fit_order = int(cfg.get("derivative_fit_order", 3))
    fit_primary = fit_poly(t, primary_values, primary_fit_order)
    fit_primary_quad = fit_poly(t, primary_values, 2)
    primary_quad_accel = None
    if fit_primary_quad is not None:
        primary_quad_accel = 2.0 * fit_primary_quad["coeffs"][0]
    gravity_like = None
    if fit_y is not None:
        c2 = fit_y["coeffs"][0]
        gravity_like = 2.0 * c2

    radius = arr["radius"]
    radius_mean = safe_float(np.nanmean(radius)) if np.any(np.isfinite(radius)) else None
    radius_std = safe_float(np.nanstd(radius)) if np.any(np.isfinite(radius)) else None
    radius_rel = safe_float(100.0 * radius_std / radius_mean) if radius_mean and radius_std is not None else None
    shape_radius = arr["shape_radius"]
    shape_radius_mean = safe_float(np.nanmean(shape_radius)) if np.any(np.isfinite(shape_radius)) else None
    shape_radius_std = safe_float(np.nanstd(shape_radius)) if np.any(np.isfinite(shape_radius)) else None
    shape_radius_rel = (
        safe_float(100.0 * shape_radius_std / shape_radius_mean)
        if shape_radius_mean and shape_radius_std is not None
        else None
    )
    aspect_ratio = arr["aspect_ratio"]
    aspect_ratio_mean = safe_float(np.nanmean(aspect_ratio)) if np.any(np.isfinite(aspect_ratio)) else None
    aspect_ratio_std = safe_float(np.nanstd(aspect_ratio)) if np.any(np.isfinite(aspect_ratio)) else None
    finite_centers = np.isfinite(x) & np.isfinite(y) & found
    center_step = np.array([], dtype=float)
    if np.sum(finite_centers) >= 2:
        center_step = np.hypot(np.diff(x[finite_centers]), np.diff(y[finite_centers]))
    center_step_median = safe_float(np.nanmedian(center_step)) if len(center_step) else None
    center_step_max = safe_float(np.nanmax(center_step)) if len(center_step) else None
    center_step_outlier_count = 0
    if len(center_step) and center_step_median is not None:
        threshold = max(center_step_median * 4.0, 2.0 if unit == "mm" else 64.0)
        center_step_outlier_count = int(np.sum(center_step > threshold))
    finite_radius = np.isfinite(radius) & found
    radius_step_rel_max = None
    radius_step_outlier_count = 0
    if np.sum(finite_radius) >= 2:
        r = radius[finite_radius]
        r_med = float(np.nanmedian(r))
        if np.isfinite(r_med) and r_med > 0:
            radius_step_rel = np.abs(np.diff(r)) / r_med * 100.0
            radius_step_rel_max = safe_float(np.nanmax(radius_step_rel)) if len(radius_step_rel) else None
            radius_step_outlier_count = int(np.sum(radius_step_rel > 12.0))

    return {
        "arrays": {
            "t": t,
            "x": x,
            "y": y,
            "x_smooth": np.asarray(x_deriv["q_smooth"], dtype=float),
            "y_smooth": np.asarray(y_deriv["q_smooth"], dtype=float),
            "vx": vx,
            "vy": vy,
            "ax": ax,
            "ay": ay,
            "radius": radius,
            "major_axis": arr["major_axis"],
            "minor_axis": arr["minor_axis"],
            "aspect_ratio": aspect_ratio,
            "shape_radius": shape_radius,
            "found": found,
        },
        "summary": {
            "valid_found_ratio": safe_float(np.mean(found.astype(float))) if len(found) else None,
            "radius_mean_mm" if unit == "mm" else "radius_mean_px": radius_mean,
            "radius_std_mm" if unit == "mm" else "radius_std_px": radius_std,
            "radius_rel_std_percent": radius_rel,
            "shape_radius_mean_mm" if unit == "mm" else "shape_radius_mean_px": shape_radius_mean,
            "shape_radius_rel_std_percent": shape_radius_rel,
            "major_axis_mean_mm" if unit == "mm" else "major_axis_mean_px": safe_float(np.nanmean(arr["major_axis"]))
            if np.any(np.isfinite(arr["major_axis"]))
            else None,
            "minor_axis_mean_mm" if unit == "mm" else "minor_axis_mean_px": safe_float(np.nanmean(arr["minor_axis"]))
            if np.any(np.isfinite(arr["minor_axis"]))
            else None,
            "aspect_ratio_mean": aspect_ratio_mean,
            "aspect_ratio_std": aspect_ratio_std,
            "center_step_median_mm" if unit == "mm" else "center_step_median_px": center_step_median,
            "center_step_max_mm" if unit == "mm" else "center_step_max_px": center_step_max,
            "center_step_outlier_count": center_step_outlier_count,
            "radius_step_rel_max_percent": radius_step_rel_max,
            "radius_step_outlier_count": radius_step_outlier_count,
            "x_linear_r2": fit_x["r2"] if fit_x else None,
            "y_parabola_r2": fit_y["r2"] if fit_y else None,
            "primary_fit_r2": fit_primary["r2"] if fit_primary else None,
            "primary_fit_order": primary_fit_order if fit_primary else None,
            "primary_quad_r2": fit_primary_quad["r2"] if fit_primary_quad else None,
            "primary_quad_accel_mm_s2" if unit == "mm" else "primary_quad_accel_px_s2": safe_float(primary_quad_accel),
            "gravity_fit_mm_s2" if unit == "mm" else "gravity_fit_px_s2": safe_float(gravity_like),
            "primary_axis": primary_axis,
            "primary_range_mm" if unit == "mm" else "primary_range_px": safe_float(x_range if primary_axis == "x" else y_range),
            "derivative_method": x_deriv["method"] if primary_axis == "x" else y_deriv["method"],
            "unit": unit,
            **estimate_bounces(t, x if primary_axis == "x" else y, cfg=cfg),
        },
        "fit_x": fit_x,
        "fit_y": fit_y,
    }


def save_fig(fig: plt.Figure, path: Path, dpi: int = 180) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def plot_perspective_correction(
    raw_results: list[BallResult],
    corrected_results: list[BallResult],
    frame_range: list[int],
    correction_info: dict[str, Any],
    fps: float,
    pixel_per_mm: float | None,
    output_dir: Path,
    dpi: int = 180,
) -> None:
    if not correction_info.get("applied"):
        return
    raw = results_arrays(valid_slice(raw_results, frame_range), fps=fps, pixel_per_mm=pixel_per_mm)
    corrected = results_arrays(valid_slice(corrected_results, frame_range), fps=fps, pixel_per_mm=pixel_per_mm)
    unit = str(raw["unit"])
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=False)
    axes[0, 0].plot(raw["t"], raw["radius"], "o-", ms=3, label="raw")
    axes[0, 0].plot(corrected["t"], corrected["radius"], "o-", ms=3, label="corrected")
    axes[0, 0].set_title("R(t) correction")
    axes[0, 0].set_ylabel(f"R [{unit}]")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].plot(raw["x"], raw["radius"], "o", ms=3, label="raw")
    axes[0, 1].plot(corrected["x"], corrected["radius"], "o", ms=3, label="corrected")
    axes[0, 1].set_title("R vs x")
    axes[0, 1].set_xlabel(f"x [{unit}]")
    axes[0, 1].set_ylabel(f"R [{unit}]")
    axes[0, 1].legend(fontsize=8)
    axes[0, 1].grid(alpha=0.3)

    axes[1, 0].plot(raw["t"], raw["x"], "o-", ms=3, label="raw x")
    axes[1, 0].plot(corrected["t"], corrected["x"], "o-", ms=3, label="corrected x")
    axes[1, 0].set_title("x(t): center unchanged" if not correction_info.get("apply_to_centers") else "x(t) after center correction")
    axes[1, 0].set_xlabel("t [s]")
    axes[1, 0].set_ylabel(f"x [{unit}]")
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].grid(alpha=0.3)

    raw_rel = correction_info.get("raw_radius_rel_std_percent")
    corrected_rel = correction_info.get("corrected_radius_rel_std_percent")
    info_lines = [
        "Radius correction",
        f"model: {correction_info.get('model')}",
        f"formula: {correction_info.get('formula', '-')}",
        f"raw R rel std: {raw_rel:.3f}%" if isinstance(raw_rel, (float, int)) else f"raw R rel std: {raw_rel}",
        f"corrected R rel std: {corrected_rel:.3f}%"
        if isinstance(corrected_rel, (float, int))
        else f"corrected R rel std: {corrected_rel}",
    ]
    if correction_info.get("focus_coord") is not None:
        info_lines.append(
            f"focus {correction_info.get('axis', 'q')}: {correction_info.get('focus_coord'):.3f} {correction_info.get('focus_coord_unit', unit)}"
        )
    if correction_info.get("camera_distance") is not None:
        info_lines.append(
            f"camera distance: {correction_info.get('camera_distance'):.3f} {correction_info.get('camera_distance_unit', unit)}"
        )
    if correction_info.get("x_center_px") is not None:
        info_lines.append(f"x center px: {correction_info.get('x_center_px'):.1f}")
    if correction_info.get("reference_radius_px") is not None:
        info_lines.append(f"reference R px: {correction_info.get('reference_radius_px'):.2f}")
    axes[1, 1].axis("off")
    axes[1, 1].text(
        0.0,
        0.92,
        "\n".join(info_lines),
        va="top",
        fontsize=10,
    )
    fig.tight_layout()
    save_fig(fig, output_dir / "radius_correction_diagnostics.png", dpi)


def plot_shape_axes(analysis: dict[str, Any], output_dir: Path, dpi: int = 180) -> None:
    arr = analysis["arrays"]
    summary = analysis["summary"]
    unit = summary["unit"]
    t = arr["t"]
    if not np.any(np.isfinite(arr.get("major_axis", np.array([])))):
        return
    fig, axes = plt.subplots(2, 2, figsize=(11, 7), sharex=False)
    axes[0, 0].plot(t, arr["major_axis"], "o-", ms=3, label="a major")
    axes[0, 0].plot(t, arr["minor_axis"], "o-", ms=3, label="b minor")
    axes[0, 0].set_title("Ellipse axes vs time")
    axes[0, 0].set_ylabel(f"axis length [{unit}]")
    axes[0, 0].legend(fontsize=8)
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].plot(t, arr["aspect_ratio"], "o-", ms=3)
    axes[0, 1].set_title("a/b aspect ratio")
    axes[0, 1].set_ylabel("a / b")
    axes[0, 1].grid(alpha=0.3)

    axes[1, 0].plot(t, arr["radius"], "o-", ms=3, label="enclosing R")
    axes[1, 0].plot(t, arr["shape_radius"], "o-", ms=3, label="sqrt(a b) / 2")
    axes[1, 0].set_title("Radius estimates")
    axes[1, 0].set_xlabel("t [s]")
    axes[1, 0].set_ylabel(f"R [{unit}]")
    axes[1, 0].legend(fontsize=8)
    axes[1, 0].grid(alpha=0.3)

    axes[1, 1].plot(arr["x"], arr["aspect_ratio"], "o", ms=3)
    axes[1, 1].set_title("aspect ratio vs x")
    axes[1, 1].set_xlabel(f"x [{unit}]")
    axes[1, 1].set_ylabel("a / b")
    axes[1, 1].grid(alpha=0.3)

    fig.suptitle(
        "Rigid ball shape axes: "
        f"a/b mean={summary.get('aspect_ratio_mean')}, "
        f"shape R rel std={summary.get('shape_radius_rel_std_percent')}"
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    save_fig(fig, output_dir / "rigid_ball_shape_axes.png", dpi)


def plot_outputs(analysis: dict[str, Any], output_dir: Path, dpi: int = 180) -> None:
    arr = analysis["arrays"]
    summary = analysis["summary"]
    unit = summary["unit"]
    t = arr["t"]

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot(arr["x"], arr["y"], "o-", ms=3)
    ax.invert_yaxis()
    ax.set_xlabel(f"x [{unit}]")
    ax.set_ylabel(f"y [{unit}]")
    ax.set_title("Rigid ball trajectory")
    ax.grid(alpha=0.3)
    save_fig(fig, output_dir / "rigid_ball_trajectory.png", dpi)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, arr["x"], "o-", ms=3)
    axes[0].set_ylabel(f"x [{unit}]")
    axes[0].grid(alpha=0.3)
    axes[1].plot(t, arr["y"], "o-", ms=3)
    axes[1].set_xlabel("Time [s]")
    axes[1].set_ylabel(f"y [{unit}]")
    axes[1].grid(alpha=0.3)
    fig.suptitle("Position vs time")
    save_fig(fig, output_dir / "rigid_ball_position_xy.png", dpi)

    fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True)
    axes[0].plot(t, arr["vx"], "-", lw=1.8)
    axes[0].set_ylabel(f"vx [{unit}/s]")
    axes[0].grid(alpha=0.3)
    axes[1].plot(t, arr["vy"], "-", lw=1.8)
    axes[1].set_xlabel("Time [s]")
    axes[1].set_ylabel(f"vy [{unit}/s]")
    axes[1].grid(alpha=0.3)
    fig.suptitle("Velocity vs time")
    save_fig(fig, output_dir / "rigid_ball_velocity_xy.png", dpi)

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(t, arr["radius"], "o-", ms=3)
    mean_key = "radius_mean_mm" if unit == "mm" else "radius_mean_px"
    if summary.get(mean_key) is not None:
        ax.axhline(summary[mean_key], ls="--", lw=1.5)
    ax.set_xlabel("Time [s]")
    ax.set_ylabel(f"radius [{unit}]")
    ax.set_title(f"Detected radius, rel std = {summary.get('radius_rel_std_percent')}")
    ax.grid(alpha=0.3)
    save_fig(fig, output_dir / "rigid_ball_radius.png", dpi)

    primary_axis = summary.get("primary_axis", "x")
    if primary_axis == "y":
        raw_q = arr["y"]
        q = arr.get("y_smooth", arr["y"])
        v = arr["vy"]
        a = arr["ay"]
    else:
        raw_q = arr["x"]
        q = arr.get("x_smooth", arr["x"])
        v = arr["vx"]
        a = arr["ax"]

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), sharex=True)
    axes[0, 0].plot(t, raw_q, "o", ms=3, alpha=0.45, label="raw")
    axes[0, 0].plot(t, q, "-", lw=1.9, label="smoothed fit")
    axes[0, 0].set_title(f"{primary_axis}(t): primary position")
    axes[0, 0].set_ylabel(f"{primary_axis} [{unit}]")
    axes[0, 0].legend(loc="best", fontsize=8)
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].plot(t, v, "-", lw=1.8)
    axes[0, 1].set_title(f"v(t): primary velocity")
    axes[0, 1].set_ylabel(f"v_{primary_axis} [{unit}/s]")
    axes[0, 1].grid(alpha=0.3)

    axes[1, 0].plot(t, a, "-", lw=1.8)
    axes[1, 0].set_title(f"a(t): primary acceleration")
    axes[1, 0].set_xlabel("t [s]")
    axes[1, 0].set_ylabel(f"a_{primary_axis} [{unit}/s^2]")
    axes[1, 0].grid(alpha=0.3)

    raw_radius_for_correction = analysis.get("raw_arrays_for_radius_correction", {}).get("radius")
    if raw_radius_for_correction is not None and len(raw_radius_for_correction) == len(t):
        axes[1, 1].plot(t, raw_radius_for_correction, "o-", ms=2.5, lw=1.2, alpha=0.45, label="raw")
        axes[1, 1].plot(t, arr["radius"], "o-", ms=3, lw=1.6, label="corrected")
        axes[1, 1].legend(loc="best", fontsize=8)
        axes[1, 1].set_title("R(t): raw vs corrected radius")
    else:
        axes[1, 1].plot(t, arr["radius"], "o-", ms=3, lw=1.6)
        axes[1, 1].set_title("R(t): detected radius")
    axes[1, 1].set_xlabel("t [s]")
    axes[1, 1].set_ylabel(f"R [{unit}]")
    axes[1, 1].grid(alpha=0.3)

    fig.suptitle(
        f"Rigid ball summary: {primary_axis}/v/a/R vs t, "
        f"tracking={summary.get('valid_found_ratio')}, "
        f"R rel std={summary.get('radius_rel_std_percent')}, "
        f"derivative={summary.get('derivative_method')}"
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    save_fig(fig, output_dir / "rigid_ball_summary_panel.png", dpi)
    plot_shape_axes(analysis, output_dir=output_dir, dpi=dpi)


def draw_result_on_frame(frame: np.ndarray, roi: tuple[int, int, int, int], result: BallResult) -> np.ndarray:
    disp = draw_roi_on_frame(frame, roi)
    if result.found:
        center = (int(round(result.cx)), int(round(result.cy)))
        cv2.circle(disp, center, int(round(result.radius_px)), (0, 255, 0), 2)
        cv2.circle(disp, center, 4, (0, 255, 255), -1)
    return disp


def save_tracking_previews(
    stack: np.ndarray,
    roi: tuple[int, int, int, int],
    results: list[BallResult],
    frame_range: list[int],
    output_dir: Path,
    sample_count: int,
    dpi: int = 180,
) -> None:
    indices = np.linspace(0, len(stack) - 1, min(sample_count, len(stack)), dtype=int)
    fig = plt.figure(figsize=(15, 8))
    for j, idx in enumerate(indices, start=1):
        plt.subplot(int(np.ceil(len(indices) / 3)), min(3, len(indices)), j)
        disp = draw_result_on_frame(stack[idx], roi, results[idx])
        plt.imshow(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB))
        plt.title(f"frame {idx}")
        plt.axis("off")
    plt.tight_layout()
    save_fig(fig, output_dir / "tracking_preview.png", dpi)

    f0, f1 = frame_range
    f0 = max(0, int(f0))
    f1 = min(len(stack) - 1, int(f1))
    valid_indices = np.linspace(f0, f1, min(sample_count, max(1, f1 - f0 + 1)), dtype=int)
    fig = plt.figure(figsize=(15, 8))
    for j, idx in enumerate(valid_indices, start=1):
        plt.subplot(int(np.ceil(len(valid_indices) / 3)), min(3, len(valid_indices)), j)
        disp = draw_result_on_frame(stack[idx], roi, results[idx])
        plt.imshow(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB))
        plt.title(f"valid frame {idx}")
        plt.axis("off")
    plt.tight_layout()
    save_fig(fig, output_dir / "valid_window_tracking_preview.png", dpi)


def export_monitor_video(
    stack: np.ndarray,
    roi: tuple[int, int, int, int],
    results: list[BallResult],
    frame_range: list[int],
    output_dir: Path,
    filename: str,
    fps_out: float,
) -> str | None:
    f0, f1 = int(frame_range[0]), int(frame_range[1])
    f0 = max(0, f0)
    f1 = min(len(stack) - 1, f1)
    if f1 < f0:
        return None

    first = crop_roi(stack[f0], roi)
    first_bgr = cv2.cvtColor(normalize_to_uint8(first), cv2.COLOR_GRAY2BGR)
    h, w = first_bgr.shape[:2]
    requested_path = output_dir / filename
    stem = requested_path.stem
    candidates = [
        (output_dir / f"{stem}.webm", "VP90"),
        (output_dir / f"{stem}.webm", "VP80"),
        (requested_path.with_suffix(".mp4"), "avc1"),
        (requested_path.with_suffix(".mp4"), "mp4v"),
    ]

    x0, y0, _, _ = roi

    def write_with_codec(target_path: Path, fourcc: str) -> bool:
        try:
            target_path.unlink(missing_ok=True)
        except OSError:
            pass
        writer = cv2.VideoWriter(str(target_path), cv2.VideoWriter_fourcc(*fourcc), fps_out, (w, h))
        if not writer.isOpened():
            return False
        trajectory: list[tuple[int, int]] = []
        for idx in range(f0, f1 + 1):
            frame_roi = crop_roi(stack[idx], roi)
            disp = cv2.cvtColor(normalize_to_uint8(frame_roi), cv2.COLOR_GRAY2BGR)
            result = results[idx]
            if result.found:
                cx = int(round(result.cx - x0))
                cy = int(round(result.cy - y0))
                radius = int(round(result.radius_px))
                trajectory.append((cx, cy))
                trajectory = trajectory[-80:]
                cv2.circle(disp, (cx, cy), radius, (0, 255, 0), 2)
                cv2.circle(disp, (cx, cy), 3, (0, 255, 255), -1)
            for a, b in zip(trajectory[:-1], trajectory[1:]):
                cv2.line(disp, a, b, (0, 255, 255), 2, cv2.LINE_AA)
            cv2.putText(disp, f"frame={idx}", (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            writer.write(disp)
        writer.release()
        return target_path.exists() and target_path.stat().st_size > 1024

    for out_path, fourcc in candidates:
        if write_with_codec(out_path, fourcc):
            return str(out_path)
    return None


def clamp_roi(roi: dict[str, int], shape: tuple[int, int]) -> dict[str, int]:
    h, w = shape
    x = max(0, min(int(roi["x"]), w - 1))
    y = max(0, min(int(roi["y"]), h - 1))
    rw = max(1, min(int(roi["w"]), w - x))
    rh = max(1, min(int(roi["h"]), h - y))
    return {"x": x, "y": y, "w": rw, "h": rh}


def estimate_motion_bbox(stack: np.ndarray, cfg: dict[str, Any]) -> dict[str, Any] | None:
    n = stack.shape[0]
    sample_count = min(max(12, int(cfg.get("background_sample_count", 25))), n)
    sample_indices = np.linspace(0, n - 1, sample_count, dtype=int)
    sampled = stack[sample_indices]
    background = np.median(sampled.astype(np.float32), axis=0)

    union = np.zeros(stack.shape[1:], dtype=np.uint8)
    for idx in sample_indices:
        diff = np.abs(stack[idx].astype(np.float32) - background)
        diff_u8 = normalize_to_uint8(diff)
        _, mask = cv2.threshold(diff_u8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        k = max(3, int(cfg.get("morph_kernel_size", 5)))
        if k % 2 == 0:
            k += 1
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
        union = cv2.bitwise_or(union, mask)

    contours, _ = cv2.findContours(union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < float(cfg.get("min_area_px2", 20)):
            continue
        x, y, w, h = cv2.boundingRect(contour)
        boxes.append((x, y, x + w, y + h, area))
    if not boxes:
        return None

    x0 = min(box[0] for box in boxes)
    y0 = min(box[1] for box in boxes)
    x1 = max(box[2] for box in boxes)
    y1 = max(box[3] for box in boxes)
    return {
        "bbox": {"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)},
        "union_area_px2": float(sum(box[4] for box in boxes)),
        "sample_count": int(sample_count),
    }


def roi_with_padding(bbox: dict[str, int], padding: int, shape: tuple[int, int]) -> dict[str, int]:
    return clamp_roi(
        {
            "x": int(bbox["x"]) - padding,
            "y": int(bbox["y"]) - padding,
            "w": int(bbox["w"]) + 2 * padding,
            "h": int(bbox["h"]) + 2 * padding,
        },
        shape,
    )


def guarded_channel_roi(shape: tuple[int, int], cfg: dict[str, Any]) -> dict[str, int]:
    h, w = shape
    left = float(cfg.get("auto_guarded_roi_left_fraction", 0.16))
    right = float(cfg.get("auto_guarded_roi_right_fraction", 0.94))
    top = float(cfg.get("auto_guarded_roi_top_fraction", 0.07))
    bottom = float(cfg.get("auto_guarded_roi_bottom_fraction", 0.90))
    x0 = int(round(w * max(0.0, min(0.95, left))))
    x1 = int(round(w * max(left + 0.05, min(1.0, right))))
    y0 = int(round(h * max(0.0, min(0.95, top))))
    y1 = int(round(h * max(top + 0.05, min(1.0, bottom))))
    return clamp_roi({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}, shape)


def auto_valid_frame_range_from_results(results: list[BallResult], max_gap: int) -> list[int]:
    found = [bool(r.found) for r in results]
    best = (0, len(results) - 1, -1)
    start = None
    last_found = None
    gap = 0
    for idx, is_found in enumerate(found):
        if is_found:
            if start is None:
                start = idx
            last_found = idx
            gap = 0
        elif start is not None:
            gap += 1
            if gap > max_gap:
                end = last_found if last_found is not None else idx - gap
                length = end - start + 1
                if length > best[2]:
                    best = (start, end, length)
                start = None
                last_found = None
                gap = 0
    if start is not None:
        end = last_found if last_found is not None else len(results) - 1
        length = end - start + 1
        if length > best[2]:
            best = (start, end, length)
    if best[2] <= 0:
        return [0, max(0, len(results) - 1)]
    return [int(best[0]), int(best[1])]


def robust_zscore(values: np.ndarray) -> np.ndarray:
    values = values.astype(float)
    med = np.nanmedian(values)
    mad = np.nanmedian(np.abs(values - med))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale <= 1e-12:
        scale = np.nanstd(values)
    if not np.isfinite(scale) or scale <= 1e-12:
        return np.zeros_like(values, dtype=float)
    return np.abs((values - med) / scale)


def refine_core_valid_frame_range(
    results: list[BallResult],
    frame_range: list[int],
    fps: float,
    pixel_per_mm: float | None,
    cfg: dict[str, Any],
) -> tuple[list[int], dict[str, Any]]:
    if not cfg.get("core_trim_enabled", True):
        return frame_range, {"enabled": False}

    f0, f1 = int(frame_range[0]), int(frame_range[1])
    f0 = max(0, f0)
    f1 = min(len(results) - 1, f1)
    if f1 - f0 + 1 < int(cfg.get("core_window_min_frames", 12)):
        return [f0, f1], {"enabled": True, "reason": "too_short_to_trim"}

    segment = results[f0 : f1 + 1]
    arr = results_arrays(segment, fps=fps, pixel_per_mm=pixel_per_mm)
    found = arr["found"]
    radius = arr["radius"]
    t = arr["t"]
    axis = str(cfg.get("primary_axis", "x")).lower()
    q_key = "y" if axis == "y" else "x"
    deriv = smooth_position_and_derivatives(
        t,
        arr[q_key],
        fit_order=int(cfg.get("derivative_fit_order", 3)),
        smooth_window=int(cfg.get("derivative_smooth_window", 9)),
    )
    v_primary = np.asarray(deriv["v_smooth"], dtype=float)

    stable = found.copy()
    if np.any(np.isfinite(radius)):
        radius_med = np.nanmedian(radius)
        if np.isfinite(radius_med) and radius_med > 0:
            radius_dev_percent = np.abs(radius - radius_med) / radius_med * 100.0
            stable &= radius_dev_percent <= float(cfg.get("core_radius_rel_std_max", 2.5)) * 2.0
    if np.any(np.isfinite(v_primary)):
        stable &= robust_zscore(v_primary) <= float(cfg.get("core_velocity_zscore_max", 3.5))

    min_len = int(cfg.get("core_window_min_frames", 12))
    best = None
    start = None
    for idx, ok in enumerate(stable):
        if ok and start is None:
            start = idx
        if (not ok or idx == len(stable) - 1) and start is not None:
            end = idx if ok and idx == len(stable) - 1 else idx - 1
            if end - start + 1 >= min_len:
                candidate = segment[start : end + 1]
                analysis = analyze_motion(candidate, fps=fps, pixel_per_mm=pixel_per_mm, cfg=cfg)
                score = candidate_score(analysis["summary"])
                item = {
                    "local_start": int(start),
                    "local_end": int(end),
                    "frame_range": [int(f0 + start), int(f0 + end)],
                    "score": float(score),
                    "summary": analysis["summary"],
                }
                if best is None or item["score"] > best["score"]:
                    best = item
            start = None

    if best is None:
        return [f0, f1], {
            "enabled": True,
            "reason": "no_stable_core_found",
            "stable_fraction": float(np.mean(stable.astype(float))) if len(stable) else 0.0,
        }

    return best["frame_range"], {
        "enabled": True,
        "original_frame_range": [f0, f1],
        "selected_frame_range": best["frame_range"],
        "stable_fraction": float(np.mean(stable.astype(float))) if len(stable) else 0.0,
        "selected_score": best["score"],
        "selected_summary": {
            k: v
            for k, v in best["summary"].items()
            if k not in {"events"} and isinstance(v, (int, float, str, type(None)))
        },
    }


def candidate_score(summary: dict[str, Any]) -> float:
    found = safe_float(summary.get("valid_found_ratio")) or 0.0
    radius_rel = safe_float(summary.get("radius_rel_std_percent"))
    r2 = safe_float(summary.get("primary_fit_r2"))
    radius_step = safe_float(summary.get("radius_step_rel_max_percent"))
    center_outliers = safe_float(summary.get("center_step_outlier_count")) or 0.0
    radius_outliers = safe_float(summary.get("radius_step_outlier_count")) or 0.0
    if r2 is None:
        r2 = safe_float(summary.get("x_linear_r2"))
    if r2 is None:
        r2 = safe_float(summary.get("y_parabola_r2"))
    radius_score = 1.0 if radius_rel is None else max(0.0, min(1.0, 1.0 - radius_rel / 8.0))
    fit_score = 0.5 if r2 is None else max(0.0, min(1.0, (r2 - 0.90) / 0.095))
    continuity_score = 1.0
    if radius_step is not None:
        continuity_score = min(continuity_score, max(0.0, min(1.0, 1.0 - radius_step / 25.0)))
    continuity_score = max(0.0, continuity_score - 0.18 * center_outliers - 0.12 * radius_outliers)
    return 45.0 * found + 25.0 * radius_score + 20.0 * fit_score + 10.0 * continuity_score


def select_auto_roi_and_vfr(
    stack: np.ndarray,
    cfg: dict[str, Any],
    fps: float,
    pixel_per_mm: float | None,
) -> dict[str, Any]:
    bbox_info = estimate_motion_bbox(stack, cfg)
    shape = stack.shape[1:]
    if bbox_info is None:
        full_roi = {"x": 0, "y": 0, "w": int(shape[1]), "h": int(shape[0])}
        bbox_info = {"bbox": full_roi, "union_area_px2": None, "sample_count": 0, "fallback": "full_frame"}

    roi_candidates = []
    for padding in cfg.get("auto_roi_paddings", [30, 60, 100]):
        roi = roi_with_padding(bbox_info["bbox"], int(padding), shape)
        roi_candidates.append((f"motion_padding_{int(padding)}", int(padding), roi))
    if cfg.get("auto_guarded_roi_enabled", True):
        roi_candidates.append(("guarded_channel", 0, guarded_channel_roi(shape, cfg)))

    candidates = []
    seen_rois: set[tuple[int, int, int, int]] = set()
    for source, padding, roi in roi_candidates:
        roi_key = (roi["x"], roi["y"], roi["w"], roi["h"])
        if roi_key in seen_rois:
            continue
        seen_rois.add(roi_key)
        roi_tuple = (roi["x"], roi["y"], roi["w"], roi["h"])
        try:
            results, _ = track_rigid_ball(stack, roi_tuple, cfg)
            frame_range = auto_valid_frame_range_from_results(results, int(cfg.get("auto_valid_max_gap", 3)))
            core_range, core_info = refine_core_valid_frame_range(
                results=results,
                frame_range=frame_range,
                fps=fps,
                pixel_per_mm=pixel_per_mm,
                cfg=cfg,
            )
            valid_results = valid_slice(results, core_range)
            analysis = analyze_motion(valid_results, fps=fps, pixel_per_mm=pixel_per_mm, cfg=cfg)
            summary = analysis["summary"]
            score = candidate_score(summary)
            candidates.append(
                {
                    "padding": int(padding),
                    "source": source,
                    "roi": roi,
                    "valid_frame_range": core_range,
                    "raw_valid_frame_range": frame_range,
                    "core_trim": core_info,
                    "score": float(score),
                    "valid_found_ratio": summary.get("valid_found_ratio"),
                    "radius_rel_std_percent": summary.get("radius_rel_std_percent"),
                    "primary_fit_r2": summary.get("primary_fit_r2"),
                    "primary_axis": summary.get("primary_axis"),
                    "radius_step_rel_max_percent": summary.get("radius_step_rel_max_percent"),
                    "center_step_outlier_count": summary.get("center_step_outlier_count"),
                    "radius_step_outlier_count": summary.get("radius_step_outlier_count"),
                }
            )
        except Exception as exc:  # noqa: BLE001 - one bad candidate should not stop selection.
            candidates.append({"padding": int(padding), "source": source, "roi": roi, "error": str(exc), "score": -1.0})

    candidates.sort(key=lambda item: item.get("score", -1.0), reverse=True)
    best = candidates[0]
    return {
        "motion_bbox": bbox_info,
        "candidates": candidates,
        "selected_roi": best["roi"],
        "selected_valid_frame_range": best.get("valid_frame_range", [0, int(stack.shape[0] - 1)]),
        "selected_score": best.get("score"),
    }


def run_rigid_ball_case(
    tiff_path: Path,
    output_dir: Path,
    roi: dict[str, int] | None,
    valid_frame_range: list[int] | None,
    fps: float,
    pixel_per_mm: float | None,
    rigid_cfg: dict[str, Any] | None = None,
    subjective_experience: str = "",
    review_criteria: str = "",
) -> dict[str, Any]:
    cfg = merged_rigid_config(rigid_cfg)
    output_dir.mkdir(parents=True, exist_ok=True)
    stack = read_tiff_stack(tiff_path)
    original_valid_frame_range = valid_frame_range[:] if valid_frame_range is not None else None

    auto_selection = None
    if roi is None or (valid_frame_range is None and cfg.get("auto_valid_frame_range", True)):
        auto_selection = select_auto_roi_and_vfr(
            stack=stack,
            cfg=cfg,
            fps=fps,
            pixel_per_mm=pixel_per_mm,
        )
        if roi is None:
            roi = auto_selection["selected_roi"]
        if valid_frame_range is None and cfg.get("auto_valid_frame_range", True):
            valid_frame_range = auto_selection["selected_valid_frame_range"]

    roi = clamp_roi(roi, stack.shape[1:])
    roi_tuple = (int(roi["x"]), int(roi["y"]), int(roi["w"]), int(roi["h"]))
    if valid_frame_range is None:
        valid_frame_range = [0, int(stack.shape[0] - 1)]
    valid_frame_range = [max(0, int(valid_frame_range[0])), min(int(stack.shape[0] - 1), int(valid_frame_range[1]))]

    track_context = int(cfg.get("track_window_context_frames", 8))
    track_slice = [0, int(stack.shape[0] - 1)]
    if original_valid_frame_range is not None and roi is not None:
        track_slice = [
            max(0, int(valid_frame_range[0]) - track_context),
            min(int(stack.shape[0] - 1), int(valid_frame_range[1]) + track_context),
        ]
    if track_slice == [0, int(stack.shape[0] - 1)]:
        results, background_roi = track_rigid_ball(stack, roi_tuple, cfg)
    else:
        partial_results, background_roi = track_rigid_ball(stack[track_slice[0] : track_slice[1] + 1], roi_tuple, cfg)
        results = [BallResult(frame_idx=idx, found=False) for idx in range(len(stack))]
        for item in partial_results:
            item.frame_idx += track_slice[0]
            results[item.frame_idx] = item

    core_trim_info = None
    if cfg.get("core_trim_enabled", True):
        refined_range, core_trim_info = refine_core_valid_frame_range(
            results=results,
            frame_range=valid_frame_range,
            fps=fps,
            pixel_per_mm=pixel_per_mm,
            cfg=cfg,
        )
        valid_frame_range = refined_range
    raw_valid_results = valid_slice(results, valid_frame_range)
    raw_analysis = analyze_motion(raw_valid_results, fps=fps, pixel_per_mm=pixel_per_mm, cfg=cfg)
    corrected_results = results
    radius_correction = {"enabled": False, "applied": False}
    perspective_correction = {"enabled": False, "applied": False}
    if cfg.get("focus_radius_correction_enabled", False):
        corrected_results, radius_correction = focus_cosine_correct_results(
            results=results,
            frame_range=valid_frame_range,
            cfg=cfg,
            pixel_per_mm=pixel_per_mm,
        )
    elif cfg.get("perspective_correction_enabled", False):
        corrected_results, perspective_correction = perspective_correct_results(
            results=results,
            frame_range=valid_frame_range,
            cfg=cfg,
            pixel_per_mm=pixel_per_mm,
        )
        radius_correction = perspective_correction

    valid_results = valid_slice(corrected_results, valid_frame_range)
    analysis = analyze_motion(valid_results, fps=fps, pixel_per_mm=pixel_per_mm, cfg=cfg)
    if radius_correction.get("applied"):
        analysis["raw_arrays_for_radius_correction"] = raw_analysis.get("arrays", {})
    summary = analysis["summary"]
    if radius_correction.get("enabled"):
        summary["radius_correction"] = radius_correction
        summary["radius_correction_applied"] = bool(radius_correction.get("applied"))
        summary["raw_radius_rel_std_percent"] = raw_analysis["summary"].get("radius_rel_std_percent")
        if radius_correction.get("model"):
            summary["radius_correction_model"] = radius_correction.get("model")
        if radius_correction.get("focus_coord") is not None:
            summary["radius_focus_coord"] = radius_correction.get("focus_coord")
            summary["radius_focus_coord_unit"] = radius_correction.get("focus_coord_unit")
        if radius_correction.get("camera_distance") is not None:
            summary["radius_focus_camera_distance"] = radius_correction.get("camera_distance")
            summary["radius_focus_camera_distance_unit"] = radius_correction.get("camera_distance_unit")
        if radius_correction.get("applied"):
            summary["processed_by"] = (
                "rigid_ball_focus_cosine_radius_correction"
                if radius_correction.get("model") == "focus_cosine_radius_correction"
                else "rigid_ball_perspective_correction"
            )
    if perspective_correction.get("enabled"):
        summary["perspective_correction"] = perspective_correction
        summary["perspective_correction_applied"] = bool(perspective_correction.get("applied"))
        if perspective_correction.get("applied"):
            summary["processed_by"] = "rigid_ball_perspective_correction"

    save_tracking_previews(
        stack=stack,
        roi=roi_tuple,
        results=results,
        frame_range=valid_frame_range,
        output_dir=output_dir,
        sample_count=int(cfg["preview_sample_count"]),
    )
    plot_outputs(analysis, output_dir=output_dir)
    plot_perspective_correction(
        raw_results=results,
        corrected_results=corrected_results,
        frame_range=valid_frame_range,
        correction_info=radius_correction,
        fps=fps,
        pixel_per_mm=pixel_per_mm,
        output_dir=output_dir,
    )
    video_path = None
    if cfg.get("export_video", True):
        video_path = export_monitor_video(
            stack=stack,
            roi=roi_tuple,
            results=results,
            frame_range=valid_frame_range,
            output_dir=output_dir,
            filename=f"{output_dir.name}_monitor.mp4",
            fps_out=float(cfg["video_fps_out"]),
        )

    fig = plt.figure(figsize=(12, 3))
    plt.imshow(normalize_to_uint8(background_roi), cmap="gray")
    plt.title("Rigid ball background ROI")
    plt.axis("off")
    plt.tight_layout()
    save_fig(fig, output_dir / "background_roi.png")

    result_payload = {
        "case": tiff_path.stem,
        "case_id": output_dir.parent.name,
        "experiment_type": "rigid_ball",
        "material": infer_material_from_name(tiff_path.name),
        "processed_by": "rigid_ball_processing",
        "processed_at": now_iso(),
        "raw_tiff_path": str(tiff_path.resolve()),
        "output_dir": str(output_dir.resolve()),
        "valid_frame_range": valid_frame_range,
        "roi": {"x": roi_tuple[0], "y": roi_tuple[1], "w": roi_tuple[2], "h": roi_tuple[3]},
        "fps": fps,
        "pixel_per_mm": pixel_per_mm,
        "subjective_experience": subjective_experience,
        "review_criteria": review_criteria,
        "track_slice": track_slice,
        "auto_selection": auto_selection,
        "core_trim": core_trim_info,
        "figure": str((output_dir / "rigid_ball_summary_panel.png").resolve()),
        "monitor_video": video_path,
        **summary,
        "results": [asdict(item) for item in results],
        "corrected_results": [asdict(item) for item in corrected_results] if radius_correction.get("applied") else [],
    }

    case_summary = {k: v for k, v in result_payload.items() if k not in {"results", "corrected_results"}}
    write_json(output_dir / "case_summary.json", case_summary)
    write_json(output_dir / "rigid_ball_summary.json", result_payload)
    write_json(
        output_dir / "group_meeting_final_metrics.json",
        {
            "case": tiff_path.stem,
            "experiment_type": "rigid_ball",
            "figure": str((output_dir / "rigid_ball_summary_panel.png").resolve()),
            **summary,
        },
    )
    return case_summary


def parse_roi(text: str) -> dict[str, int]:
    values = [int(v.strip()) for v in text.split(",")]
    if len(values) != 4:
        raise ValueError("ROI must be x,y,w,h")
    return {"x": values[0], "y": values[1], "w": values[2], "h": values[3]}


def parse_frame_range(text: str | None) -> list[int] | None:
    if not text:
        return None
    values = [int(v.strip()) for v in text.split(",")]
    if len(values) != 2:
        raise ValueError("frame range must be start,end")
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description="Process a rigid solid ball TIFF experiment.")
    parser.add_argument("--tiff", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--roi", help="x,y,w,h; omit to auto-select")
    parser.add_argument("--valid-frame-range", help="start,end")
    parser.add_argument("--fps", type=float, default=2000.0)
    parser.add_argument("--pixel-per-mm", type=float)
    parser.add_argument("--manual-threshold", type=int)
    parser.add_argument("--min-radius-px", type=float)
    parser.add_argument("--max-radius-px", type=float)
    parser.add_argument("--perspective-correction", action="store_true", help="Enable radius-vs-x perspective correction.")
    parser.add_argument("--focus-radius-correction", action="store_true", help="Enable focus-cosine radius correction.")
    parser.add_argument("--focus-radius-axis", choices=["x", "y", "primary"], default=None)
    parser.add_argument("--focus-radius-coord-px", type=float)
    parser.add_argument("--focus-radius-coord-mm", type=float)
    parser.add_argument("--focus-camera-distance-px", type=float)
    parser.add_argument("--focus-camera-distance-mm", type=float)
    parser.add_argument("--no-focus-camera-distance-auto", action="store_true")
    args = parser.parse_args()

    rigid_cfg = {}
    if args.manual_threshold is not None:
        rigid_cfg["threshold_mode"] = "manual"
        rigid_cfg["manual_threshold"] = args.manual_threshold
    if args.min_radius_px is not None:
        rigid_cfg["min_radius_px"] = args.min_radius_px
    if args.max_radius_px is not None:
        rigid_cfg["max_radius_px"] = args.max_radius_px
    if args.perspective_correction:
        rigid_cfg["perspective_correction_enabled"] = True
        if not args.focus_radius_correction:
            rigid_cfg["focus_radius_correction_enabled"] = False
    if args.focus_radius_correction:
        rigid_cfg["focus_radius_correction_enabled"] = True
    if args.focus_radius_axis is not None:
        rigid_cfg["focus_radius_axis"] = args.focus_radius_axis
    if args.focus_radius_coord_px is not None:
        rigid_cfg["focus_radius_coord_px"] = args.focus_radius_coord_px
    if args.focus_radius_coord_mm is not None:
        rigid_cfg["focus_radius_coord_mm"] = args.focus_radius_coord_mm
    if args.focus_camera_distance_px is not None:
        rigid_cfg["focus_camera_distance_px"] = args.focus_camera_distance_px
    if args.focus_camera_distance_mm is not None:
        rigid_cfg["focus_camera_distance_mm"] = args.focus_camera_distance_mm
    if args.no_focus_camera_distance_auto:
        rigid_cfg["focus_camera_distance_auto"] = False

    summary = run_rigid_ball_case(
        tiff_path=Path(args.tiff),
        output_dir=Path(args.output_dir),
        roi=parse_roi(args.roi) if args.roi else None,
        valid_frame_range=parse_frame_range(args.valid_frame_range),
        fps=args.fps,
        pixel_per_mm=args.pixel_per_mm,
        rigid_cfg=rigid_cfg,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
