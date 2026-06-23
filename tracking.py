import numpy as np
from dataclasses import dataclass
import cv2

from image_utils import (
    crop_roi,
    normalize_to_uint8,
    estimate_background,
    build_foreground_mask,
)


@dataclass
class TargetResult:
    frame_idx: int
    found: bool
    cx: float = np.nan
    cy: float = np.nan
    x_left: float = np.nan
    x_right: float = np.nan
    y_top: float = np.nan
    y_bottom: float = np.nan
    area: float = np.nan
    radius_eq: float = np.nan
    volume_px3: float = np.nan
    radius_volume_eq_px: float = np.nan


def estimate_axisymmetric_volume_from_mask(component_mask):
    volume_px3 = 0.0

    for x in range(component_mask.shape[1]):
        ys = np.where(component_mask[:, x] > 0)[0]
        if len(ys) == 0:
            continue

        radius_px = 0.5 * float(ys.max() - ys.min() + 1)
        volume_px3 += np.pi * radius_px ** 2

    if volume_px3 <= 0:
        return np.nan, np.nan

    radius_volume_eq_px = (3.0 * volume_px3 / (4.0 * np.pi)) ** (1.0 / 3.0)
    return float(volume_px3), float(radius_volume_eq_px)


def get_component_candidates(mask, roi_shape, min_area):
    """
    返回当前二值图中的所有候选连通域，供调试可视化。
    """
    _h, _w = roi_shape
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )

    candidates = []
    for label in range(1, num_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < min_area:
            continue

        x = stats[label, cv2.CC_STAT_LEFT]
        y = stats[label, cv2.CC_STAT_TOP]
        w = stats[label, cv2.CC_STAT_WIDTH]
        h = stats[label, cv2.CC_STAT_HEIGHT]
        cx, cy = centroids[label]
        comp_mask = (labels == label).astype(np.uint8) * 255

        candidates.append(
            {
                "label": label,
                "area": float(area),
                "bbox": (x, y, w, h),
                "centroid": (float(cx), float(cy)),
                "mask": comp_mask,
            }
        )

    return candidates


def select_main_component(
    mask,
    roi_shape,
    tracking_cfg,
    prev_center=None,
    prev_area=None,
    init_mode=False,
    return_all_scored=False,
):
    """
    主目标选择：
    - 初始化阶段优先选大液滴
    - 正常阶段综合考虑面积、连续性、边界惩罚、向左回跳惩罚
    """
    h, w = roi_shape

    min_area = tracking_cfg["min_area"]
    edge_margin = tracking_cfg["edge_margin"]
    max_center_jump = tracking_cfg["max_center_jump"]
    min_area_ratio_change = tracking_cfg["min_area_ratio_change"]
    max_area_ratio_change = tracking_cfg["max_area_ratio_change"]
    min_main_area = tracking_cfg["min_main_area"]
    max_backward_jump_x = tracking_cfg["max_backward_jump_x"]

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8
    )

    candidates = []
    for label in range(1, num_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < min_area:
            continue

        x = stats[label, cv2.CC_STAT_LEFT]
        y = stats[label, cv2.CC_STAT_TOP]
        bw = stats[label, cv2.CC_STAT_WIDTH]
        bh = stats[label, cv2.CC_STAT_HEIGHT]
        cx, cy = centroids[label]
        comp_mask = (labels == label).astype(np.uint8) * 255

        radius_eq = np.sqrt(area / np.pi)
        dist_to_edge = min(cx, cy, w - 1 - cx, h - 1 - cy)

        candidates.append(
            {
                "label": label,
                "area": float(area),
                "bbox": (x, y, bw, bh),
                "centroid": (float(cx), float(cy)),
                "mask": comp_mask,
                "radius_eq": float(radius_eq),
                "dist_to_edge": float(dist_to_edge),
            }
        )

    if len(candidates) == 0:
        return (None, []) if return_all_scored else None

    if init_mode:
        big_candidates = [c for c in candidates if c["area"] >= min_main_area]
        if len(big_candidates) > 0:
            big_candidates.sort(key=lambda c: c["area"], reverse=True)
            selected = big_candidates[0]
        else:
            candidates.sort(key=lambda c: c["area"], reverse=True)
            selected = candidates[0]

        selected["score"] = 0.0
        if return_all_scored:
            return selected, sorted(candidates, key=lambda c: c["area"], reverse=True)
        return selected

    scored = []
    for c in candidates:
        score = 0.0
        cx, cy = c["centroid"]
        area = c["area"]

        if area < min_main_area:
            score += 2000.0 + (min_main_area - area)

        if prev_center is not None:
            px, py = prev_center
            jump = np.sqrt((cx - px) ** 2 + (cy - py) ** 2)
            score += jump

            dx = cx - px
            if dx < -max_backward_jump_x:
                score += 3000.0 + abs(dx) * 10.0

            if jump > max_center_jump:
                score += 1500.0 + jump

        if prev_area is not None and prev_area > 0:
            ratio = area / float(prev_area)
            if ratio < min_area_ratio_change or ratio > max_area_ratio_change:
                score += 1000.0 + abs(np.log(max(ratio, 1e-6)))
            else:
                score += 50.0 * abs(np.log(ratio))

        if c["dist_to_edge"] < edge_margin:
            score += 500.0 + 50.0 * (edge_margin - c["dist_to_edge"])

        score += -0.01 * area

        c["score"] = score
        scored.append(c)

    scored.sort(key=lambda c: c["score"])
    if return_all_scored:
        return scored[0], scored
    return scored[0]


def refine_component_by_thickness(component, tracking_cfg):
    if component is None or not tracking_cfg.get("refine_thin_connections", False):
        return component

    min_dist = float(tracking_cfg.get("refine_min_distance_px", 4.0))
    dilate_size = int(tracking_cfg.get("refine_dilate_size", 7))
    clip_to_original = bool(tracking_cfg.get("refine_clip_to_original", True))
    final_erode_px = int(tracking_cfg.get("refine_final_erode_px", 0))

    mask = component["mask"]
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    core = (dist >= min_dist).astype(np.uint8) * 255

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        core, connectivity=8
    )
    if num_labels <= 1:
        return component

    prev_cx, prev_cy = component["centroid"]
    best_label = None
    best_score = np.inf

    for label in range(1, num_labels):
        area = stats[label, cv2.CC_STAT_AREA]
        if area <= 0:
            continue
        cx, cy = centroids[label]
        dist_to_original = np.sqrt((cx - prev_cx) ** 2 + (cy - prev_cy) ** 2)
        score = dist_to_original - 0.02 * area
        if score < best_score:
            best_label = label
            best_score = score

    if best_label is None:
        return component

    refined = (labels == best_label).astype(np.uint8) * 255
    if dilate_size > 1:
        if dilate_size % 2 == 0:
            dilate_size += 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (dilate_size, dilate_size)
        )
        refined = cv2.dilate(refined, kernel, iterations=1)

    if clip_to_original:
        refined = cv2.bitwise_and(refined, mask)

    if final_erode_px > 0:
        erode_size = 2 * final_erode_px + 1
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (erode_size, erode_size)
        )
        eroded = cv2.erode(refined, kernel, iterations=1)
        if np.any(eroded > 0):
            refined = eroded

    ys, xs = np.where(refined > 0)
    if len(xs) == 0:
        return component

    x = int(xs.min())
    y = int(ys.min())
    w = int(xs.max() - x + 1)
    h = int(ys.max() - y + 1)
    area = float(len(xs))
    cx = float(xs.mean())
    cy = float(ys.mean())

    updated = component.copy()
    updated["mask"] = refined
    updated["area"] = area
    updated["bbox"] = (x, y, w, h)
    updated["centroid"] = (cx, cy)
    updated["radius_eq"] = float(np.sqrt(area / np.pi))
    return updated


def extract_target_geometry(component_mask, roi, frame_idx):
    ys, xs = np.where(component_mask > 0)

    if len(xs) == 0:
        return TargetResult(frame_idx=frame_idx, found=False)

    x0, y0, _, _ = roi

    x_left_roi = xs.min()
    x_right_roi = xs.max()
    y_top_roi = ys.min()
    y_bottom_roi = ys.max()

    cx_roi = xs.mean()
    cy_roi = ys.mean()

    area = float(len(xs))
    radius_eq = np.sqrt(area / np.pi)
    volume_px3, radius_volume_eq_px = estimate_axisymmetric_volume_from_mask(
        component_mask
    )

    return TargetResult(
        frame_idx=frame_idx,
        found=True,
        cx=float(cx_roi + x0),
        cy=float(cy_roi + y0),
        x_left=float(x_left_roi + x0),
        x_right=float(x_right_roi + x0),
        y_top=float(y_top_roi + y0),
        y_bottom=float(y_bottom_roi + y0),
        area=area,
        radius_eq=float(radius_eq),
        volume_px3=volume_px3,
        radius_volume_eq_px=radius_volume_eq_px,
    )


def extract_axisymmetric_volume_centroid(component_mask, roi, frame_idx):
    """
    基于轴对称假设，从二维轮廓估计三维旋转体体积形心。
    """
    _h, w = component_mask.shape
    x0, y0, _, _ = roi

    xs_valid = []
    r2_valid = []
    y_axis_valid = []

    for x in range(w):
        ys = np.where(component_mask[:, x] > 0)[0]
        if len(ys) == 0:
            continue

        y_top = ys.min()
        y_bottom = ys.max()

        y_axis = 0.5 * (y_top + y_bottom)
        r = 0.5 * (y_bottom - y_top)

        if r <= 0:
            continue

        xs_valid.append(x)
        r2_valid.append(r ** 2)
        y_axis_valid.append(y_axis)

    if len(xs_valid) == 0:
        return TargetResult(frame_idx=frame_idx, found=False)

    xs_valid = np.array(xs_valid, dtype=float)
    r2_valid = np.array(r2_valid, dtype=float)
    y_axis_valid = np.array(y_axis_valid, dtype=float)

    cx_roi = np.sum(xs_valid * r2_valid) / np.sum(r2_valid)
    cy_roi = np.sum(y_axis_valid * r2_valid) / np.sum(r2_valid)

    ys_all, xs_all = np.where(component_mask > 0)
    x_left_roi = xs_all.min()
    x_right_roi = xs_all.max()
    y_top_roi = ys_all.min()
    y_bottom_roi = ys_all.max()
    area = float(len(xs_all))
    radius_eq = np.sqrt(area / np.pi)
    volume_px3, radius_volume_eq_px = estimate_axisymmetric_volume_from_mask(
        component_mask
    )

    return TargetResult(
        frame_idx=frame_idx,
        found=True,
        cx=float(cx_roi + x0),
        cy=float(cy_roi + y0),
        x_left=float(x_left_roi + x0),
        x_right=float(x_right_roi + x0),
        y_top=float(y_top_roi + y0),
        y_bottom=float(y_bottom_roi + y0),
        area=area,
        radius_eq=float(radius_eq),
        volume_px3=volume_px3,
        radius_volume_eq_px=radius_volume_eq_px,
    )


def _build_overlay_from_component(roi_frame, component):
    """
    根据当前 roi_frame 和选中的 component 构造调试 overlay。
    """
    roi_u8 = normalize_to_uint8(roi_frame)
    overlay_bgr = cv2.cvtColor(roi_u8, cv2.COLOR_GRAY2BGR)

    if component is None:
        return overlay_bgr

    contours, _ = cv2.findContours(
        component["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    cv2.drawContours(overlay_bgr, contours, -1, (0, 0, 255), 2)

    cx_roi, cy_roi = component["centroid"]
    cv2.circle(
        overlay_bgr,
        (int(round(cx_roi)), int(round(cy_roi))),
        4,
        (0, 255, 0),
        -1,
    )

    x, y, w, h = component["bbox"]
    cv2.rectangle(overlay_bgr, (x, y), (x + w, y + h), (255, 0, 0), 1)

    return overlay_bgr


def _extract_result_from_component(component, roi, frame_idx, use_axisymmetric):
    if component is None:
        return TargetResult(frame_idx=frame_idx, found=False)

    if use_axisymmetric:
        return extract_axisymmetric_volume_centroid(component["mask"], roi, frame_idx)
    return extract_target_geometry(component["mask"], roi, frame_idx)


def find_initial_main_target(stack, roi, background_roi, exp_cfg, pre_cfg, trk_cfg):
    """
    在有效帧区间起始附近初始化主目标（大液滴）。
    """
    valid_frame_range = tuple(exp_cfg["valid_frame_range"])

    init_idx = valid_frame_range[0]
    candidate_indices = list(range(init_idx, min(init_idx + 5, stack.shape[0])))

    best = None
    best_area = -1.0

    for idx in candidate_indices:
        roi_frame = crop_roi(stack[idx], roi)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            preprocess_cfg=pre_cfg,
        )

        comp = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            tracking_cfg=trk_cfg,
            prev_center=None,
            prev_area=None,
            init_mode=True,
        )
        comp = refine_component_by_thickness(comp, trk_cfg)

        if comp is not None and comp["area"] > best_area:
            best = (idx, comp)
            best_area = comp["area"]

    return best


def track_target_over_stack(stack, roi, config):
    """
    整段追踪：
    - 先建立背景
    - 在有效区间起始附近初始化大液滴
    - 从初始化帧开始向后追踪
    """
    exp_cfg = config["experiment"]
    pre_cfg = config["preprocess"]
    trk_cfg = config["tracking"]

    valid_frame_range = tuple(exp_cfg["valid_frame_range"])
    use_axisymmetric = exp_cfg["use_axisymmetric_volume_centroid"]

    roi_stack = np.stack([crop_roi(frame, roi) for frame in stack], axis=0)
    background_roi = estimate_background(
        roi_stack, sample_count=pre_cfg["background_sample_count"]
    )

    results = []
    overlays = []

    for i in range(stack.shape[0]):
        results.append(TargetResult(frame_idx=i, found=False))
        roi_frame = crop_roi(stack[i], roi)
        roi_u8 = normalize_to_uint8(roi_frame)
        overlays.append(cv2.cvtColor(roi_u8, cv2.COLOR_GRAY2BGR))

    init_info = find_initial_main_target(
        stack=stack,
        roi=roi,
        background_roi=background_roi,
        exp_cfg=exp_cfg,
        pre_cfg=pre_cfg,
        trk_cfg=trk_cfg,
    )

    if init_info is None:
        print("警告：未能在有效区间起始附近找到合适的大液滴初始化目标。")
        return results, background_roi, overlays

    init_idx, init_comp = init_info
    prev_center_roi = init_comp["centroid"]
    prev_area = init_comp["area"]

    results[init_idx] = _extract_result_from_component(
        init_comp, roi, init_idx, use_axisymmetric
    )
    overlays[init_idx] = _build_overlay_from_component(
        crop_roi(stack[init_idx], roi), init_comp
    )

    backfill_start = max(valid_frame_range[0], init_idx - 5)

    back_prev_center = init_comp["centroid"]
    back_prev_area = init_comp["area"]

    for i in range(init_idx - 1, backfill_start - 1, -1):
        roi_frame = crop_roi(stack[i], roi)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            preprocess_cfg=pre_cfg,
        )

        component = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            tracking_cfg=trk_cfg,
            prev_center=back_prev_center,
            prev_area=back_prev_area,
            init_mode=False,
        )
        component = refine_component_by_thickness(component, trk_cfg)

        if component is None:
            continue

        results[i] = _extract_result_from_component(
            component, roi, i, use_axisymmetric
        )
        overlays[i] = _build_overlay_from_component(roi_frame, component)

        back_prev_center = component["centroid"]
        back_prev_area = component["area"]

    for i in range(init_idx, stack.shape[0]):
        roi_frame = crop_roi(stack[i], roi)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            preprocess_cfg=pre_cfg,
        )

        component = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            tracking_cfg=trk_cfg,
            prev_center=prev_center_roi,
            prev_area=prev_area,
            init_mode=False,
        )
        component = refine_component_by_thickness(component, trk_cfg)

        if component is None:
            results[i] = TargetResult(frame_idx=i, found=False)
            overlays[i] = _build_overlay_from_component(roi_frame, None)
            continue

        results[i] = _extract_result_from_component(
            component, roi, i, use_axisymmetric
        )
        overlays[i] = _build_overlay_from_component(roi_frame, component)

        prev_center_roi = component["centroid"]
        prev_area = component["area"]

    return results, background_roi, overlays
