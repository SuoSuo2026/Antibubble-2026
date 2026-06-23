# -*- coding: utf-8 -*-
"""
main_old.py

用途：
1. 读取多页 TIFF 实验数据
2. 在给定 ROI 内提取主目标（大液滴）
3. 输出质心、边界极值、面积、等效半径
4. 基于真实帧率与标定，计算位置、速度、加速度
5. 输出调试图，帮助检查初始化和分割问题

当前版本主要针对：
- 大液滴主目标跟踪
- 有效帧区间内运动学分析
- 起始若干帧调试可视化
"""

from pathlib import Path
from dataclasses import dataclass
import numpy as np
import tifffile
import cv2
import matplotlib.pyplot as plt


# ============================================================
# 1. 参数区：优先修改这里
# ============================================================

TIFF_PATH = r"D:\Program Files (x86)\pythonProject\0407-2.tif"
OUTPUT_DIR = Path(r"D:\Program Files (x86)\pythonProject\tiff_tracking_demo_output")

# 红框 ROI: (x, y, w, h)
ROI = (0, 160, 1870, 190)

# ===== 相机真实帧率 =====
FPS = 2000.0

# ===== 标定：60 mm / 1532 pixel =====
PIXEL_PER_MM = 1532.0 / 60.0
MM_PER_PIXEL = 60.0 / 1532.0

# ===== 有效实验区间：用帧号 =====
VALID_FRAME_RANGE = (54, 186)

# 背景估计
BACKGROUND_SAMPLE_COUNT = 25

# 阈值
THRESHOLD_MODE = 'otsu'   # 'otsu' 或 'manual'
MANUAL_THRESHOLD = 25

# 形态学与基本连通域
MIN_AREA = 80
MORPH_KERNEL_SIZE = 5

# ===== 主目标（大液滴）约束 =====
MIN_MAIN_AREA = 1200

# ===== 不确定度参数 =====
CENTROID_SIGMA_PX = 0.8
FPS_REL_ERROR = 1e-4

# 核心动力学展示窗口
CORE_TIME_RANGE = (0.035, 0.085)

# 主运动方向
MOTION_AXIS = 'x'   # 'x' 或 'y'

# 平滑窗口
SMOOTH_WINDOW = 9

# 是否使用轴对称旋转体的体积形心，而不是二维面积质心
USE_AXISYMMETRIC_VOLUME_CENTROID = False

# ===== 连续性判据参数 =====
EDGE_MARGIN = 15
MAX_CENTER_JUMP = 120
MAX_BACKWARD_JUMP_X = 20
MAX_AREA_RATIO_CHANGE = 2.5
MIN_AREA_RATIO_CHANGE = 0.4

# ===== 二次拟合与稳健性分析 =====
QUAD_FIT_TIME_RANGE = (0.035, 0.085)

# 用于稳健估计 a_fit 的多组平滑窗口与时间窗
FIT_SMOOTH_WINDOWS = [7, 9, 11]
FIT_TIME_WINDOWS = [
    (0.036, 0.084),
    (0.038, 0.082),
    (0.040, 0.080),
]

# ===== 几何振荡频率分析 =====
GEOM_ANALYSIS_TIME_RANGE = (0.035, 0.085)

# ===== 加速度频谱与低通滤波 =====
ACC_FFT_TIME_RANGE = (0.035, 0.085)

# 低通滤波截止频率（Hz）
# 若主形变频率约 40 Hz，这里先取 10 Hz，只保留低频平动
LOWPASS_CUTOFF_HZ = 10.0

# ===== 二次 + 振动同步拟合 =====
USE_QUAD_OSC_FIT = True

# 若固定使用几何FFT识别到的主频
SHAPE_FREQ_HZ = 39.604

# 是否在窄频带内搜索最优频率
USE_FREQ_SCAN = True
FREQ_SCAN_RANGE = (20.0, 80.0)
FREQ_SCAN_NUM = 1201

# ===== 固定主频 + 二次谐波联合拟合 =====
USE_QUAD_OSC_HARMONIC_FIT = True

# 几何FFT得到的主频
SHAPE_FREQ_HZ = 39.604

# ============================================================
# 2. 数据结构
# ============================================================

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


# ============================================================
# 3. TIFF 读取
# ============================================================

def read_tiff_stack(tiff_path):
    """
    读取 TIFF 文件，统一返回 shape=(N,H,W) 的灰度栈。
    """
    tiff_path = Path(tiff_path)
    if not tiff_path.exists():
        raise FileNotFoundError("TIFF 文件不存在: {}".format(tiff_path))

    data = tifffile.imread(str(tiff_path))

    if data.ndim == 2:
        stack = data[None, :, :]
    elif data.ndim == 3:
        stack = data
    elif data.ndim == 4:
        gray_frames = []
        for i in range(data.shape[0]):
            frame = data[i]
            if frame.shape[-1] == 3:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
            elif frame.shape[-1] == 4:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGBA2GRAY)
            else:
                raise ValueError("无法识别的彩色帧通道数: {}".format(frame.shape))
            gray_frames.append(gray)
        stack = np.stack(gray_frames, axis=0)
    else:
        raise ValueError("不支持的 TIFF 数据维度: {}".format(data.shape))

    return stack


# ============================================================
# 4. ROI 与基础图像工具
# ============================================================

def crop_roi(frame, roi):
    x, y, w, h = roi
    return frame[y:y+h, x:x+w]


def draw_roi_on_frame(frame, roi):
    x, y, w, h = roi
    if frame.ndim == 2:
        disp = cv2.cvtColor(normalize_to_uint8(frame), cv2.COLOR_GRAY2BGR)
    else:
        disp = frame.copy()
    cv2.rectangle(disp, (x, y), (x+w, y+h), (0, 0, 255), 3)
    return disp


def normalize_to_uint8(img):
    """
    任意位深图像归一化到 uint8，便于显示和 OpenCV 操作。
    """
    img = img.astype(np.float32)
    p1, p99 = np.percentile(img, [1, 99])
    if p99 <= p1:
        p1, p99 = img.min(), img.max() + 1e-6
    img = (img - p1) / (p99 - p1)
    img = np.clip(img, 0, 1)
    return (img * 255).astype(np.uint8)


# ============================================================
# 5. 背景与前景分割
# ============================================================

def estimate_background(stack_roi, sample_count=25):
    """
    用若干帧的中值图像估计背景。
    """
    n = stack_roi.shape[0]
    if sample_count >= n:
        indices = np.arange(n)
    else:
        indices = np.linspace(0, n - 1, sample_count, dtype=int)

    sampled = stack_roi[indices].astype(np.float32)
    background = np.median(sampled, axis=0)
    return background.astype(stack_roi.dtype)


def build_foreground_mask(frame_roi,
                          background_roi,
                          threshold_mode='otsu',
                          manual_threshold=25,
                          morph_kernel_size=5):
    """
    背景差分 + 阈值 + 形态学，得到前景 mask。
    """
    frame_u8 = normalize_to_uint8(frame_roi)
    bg_u8 = normalize_to_uint8(background_roi)

    diff = cv2.absdiff(frame_u8, bg_u8)

    if threshold_mode == 'otsu':
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif threshold_mode == 'manual':
        _, mask = cv2.threshold(diff, manual_threshold, 255, cv2.THRESH_BINARY)
    else:
        raise ValueError("threshold_mode 只能是 'otsu' 或 'manual'")

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    return mask


# ============================================================
# 6. 候选目标与主目标选择
# ============================================================

def get_component_candidates(mask, roi_shape, min_area=80):
    """
    返回当前二值图中的所有候选连通域，供调试可视化。
    """
    H, W = roi_shape
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

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

        candidates.append({
            "label": label,
            "area": float(area),
            "bbox": (x, y, w, h),
            "centroid": (float(cx), float(cy)),
            "mask": comp_mask
        })

    return candidates


def select_main_component(mask,
                          roi_shape,
                          min_area=80,
                          prev_center=None,
                          prev_area=None,
                          edge_margin=15,
                          max_center_jump=120,
                          min_area_ratio_change=0.4,
                          max_area_ratio_change=2.5,
                          min_main_area=1200,
                          max_backward_jump_x=20,
                          init_mode=False,
                          return_all_scored=False):
    """
    主目标选择：
    - 初始化阶段优先选大液滴
    - 正常阶段综合考虑面积、连续性、边界惩罚、向左回跳惩罚
    """
    H, W = roi_shape

    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)

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

        radius_eq = np.sqrt(area / np.pi)
        dist_to_edge = min(cx, cy, W - 1 - cx, H - 1 - cy)

        candidates.append({
            "label": label,
            "area": float(area),
            "bbox": (x, y, w, h),
            "centroid": (float(cx), float(cy)),
            "mask": comp_mask,
            "radius_eq": float(radius_eq),
            "dist_to_edge": float(dist_to_edge)
        })

    if len(candidates) == 0:
        return (None, []) if return_all_scored else None

    # 初始化阶段：优先选大液滴
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

        # 面积太小：强惩罚，避免选小液滴
        if area < min_main_area:
            score += 2000.0 + (min_main_area - area)

        # 与上一帧质心连续性
        if prev_center is not None:
            px, py = prev_center
            jump = np.sqrt((cx - px) ** 2 + (cy - py) ** 2)
            score += jump

            dx = cx - px
            if dx < -max_backward_jump_x:
                score += 3000.0 + abs(dx) * 10.0

            if jump > max_center_jump:
                score += 1500.0 + jump

        # 面积连续性
        if prev_area is not None and prev_area > 0:
            ratio = area / float(prev_area)
            if ratio < min_area_ratio_change or ratio > max_area_ratio_change:
                score += 1000.0 + abs(np.log(max(ratio, 1e-6)))
            else:
                score += 50.0 * abs(np.log(ratio))

        # 边界惩罚
        if c["dist_to_edge"] < edge_margin:
            score += 500.0 + 50.0 * (edge_margin - c["dist_to_edge"])

        # 大面积轻微奖励
        score += -0.01 * area

        c["score"] = score
        scored.append(c)

    scored.sort(key=lambda c: c["score"])
    if return_all_scored:
        return scored[0], scored
    return scored[0]


# ============================================================
# 7. 几何量提取
# ============================================================

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

    result = TargetResult(
        frame_idx=frame_idx,
        found=True,
        cx=float(cx_roi + x0),
        cy=float(cy_roi + y0),
        x_left=float(x_left_roi + x0),
        x_right=float(x_right_roi + x0),
        y_top=float(y_top_roi + y0),
        y_bottom=float(y_bottom_roi + y0),
        area=area,
        radius_eq=float(radius_eq)
    )
    return result


def extract_axisymmetric_volume_centroid(component_mask, roi, frame_idx):
    """
    基于轴对称假设，从二维轮廓估计三维旋转体体积形心。

    假设液滴绕“水平对称轴”旋转形成轴对称体。
    对每一个 x 列，取上下边界得到局部半径 r(x)，
    体积形心的 x 坐标用 r(x)^2 加权。

    返回格式与 TargetResult 保持一致。
    """
    H, W = component_mask.shape
    x0, y0, _, _ = roi

    xs_valid = []
    r2_valid = []
    y_axis_valid = []

    for x in range(W):
        ys = np.where(component_mask[:, x] > 0)[0]
        if len(ys) == 0:
            continue

        y_top = ys.min()
        y_bottom = ys.max()

        # 局部轴线与半径
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

    # 三维体积形心（轴对称体）
    cx_roi = np.sum(xs_valid * r2_valid) / np.sum(r2_valid)
    cy_roi = np.sum(y_axis_valid * r2_valid) / np.sum(r2_valid)

    # 几何边界仍然保留
    ys_all, xs_all = np.where(component_mask > 0)
    x_left_roi = xs_all.min()
    x_right_roi = xs_all.max()
    y_top_roi = ys_all.min()
    y_bottom_roi = ys_all.max()
    area = float(len(xs_all))
    radius_eq = np.sqrt(area / np.pi)

    result = TargetResult(
        frame_idx=frame_idx,
        found=True,
        cx=float(cx_roi + x0),
        cy=float(cy_roi + y0),
        x_left=float(x_left_roi + x0),
        x_right=float(x_right_roi + x0),
        y_top=float(y_top_roi + y0),
        y_bottom=float(y_bottom_roi + y0),
        area=area,
        radius_eq=float(radius_eq)
    )

    return result


# ============================================================
# 8. 初始化主目标
# ============================================================


def find_initial_main_target(stack,
                             roi,
                             background_roi,
                             valid_frame_range,
                             threshold_mode,
                             manual_threshold,
                             morph_kernel_size,
                             min_area,
                             min_main_area):
    """
    在有效帧区间起始附近初始化主目标（大液滴）。
    """
    init_idx = valid_frame_range[0]
    candidate_indices = list(range(init_idx, min(init_idx + 5, stack.shape[0])))

    best = None
    best_area = -1.0

    for idx in candidate_indices:
        roi_frame = crop_roi(stack[idx], roi)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            threshold_mode=threshold_mode,
            manual_threshold=manual_threshold,
            morph_kernel_size=morph_kernel_size
        )

        comp = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            min_area=min_area,
            prev_center=None,
            prev_area=None,
            edge_margin=EDGE_MARGIN,
            max_center_jump=MAX_CENTER_JUMP,
            min_area_ratio_change=MIN_AREA_RATIO_CHANGE,
            max_area_ratio_change=MAX_AREA_RATIO_CHANGE,
            min_main_area=min_main_area,
            max_backward_jump_x=MAX_BACKWARD_JUMP_X,
            init_mode=True
        )

        if comp is not None and comp["area"] > best_area:
            best = (idx, comp)
            best_area = comp["area"]

    return best


# ============================================================
# 9. 整段追踪
# ============================================================

def track_target_over_stack(stack,
                            roi,
                            threshold_mode='otsu',
                            manual_threshold=25,
                            background_sample_count=25,
                            min_area=80,
                            morph_kernel_size=5,
                            edge_margin=15,
                            max_center_jump=120,
                            min_area_ratio_change=0.4,
                            max_area_ratio_change=2.5,
                            min_main_area=1200,
                            max_backward_jump_x=20):
    """
    整段追踪：
    - 先建立背景
    - 在有效区间起始附近初始化大液滴
    - 从初始化帧开始向后追踪
    """
    roi_stack = np.stack([crop_roi(frame, roi) for frame in stack], axis=0)
    background_roi = estimate_background(roi_stack, sample_count=background_sample_count)

    results = []
    overlays = []

    # 先把所有帧初始化为空结果
    for i in range(stack.shape[0]):
        results.append(TargetResult(frame_idx=i, found=False))
        roi_frame = crop_roi(stack[i], roi)
        roi_u8 = normalize_to_uint8(roi_frame)
        overlays.append(cv2.cvtColor(roi_u8, cv2.COLOR_GRAY2BGR))

    init_info = find_initial_main_target(
        stack=stack,
        roi=roi,
        background_roi=background_roi,
        valid_frame_range=VALID_FRAME_RANGE,
        threshold_mode=threshold_mode,
        manual_threshold=manual_threshold,
        morph_kernel_size=morph_kernel_size,
        min_area=min_area,
        min_main_area=min_main_area
    )

    if init_info is None:
        print("警告：未能在有效区间起始附近找到合适的大液滴初始化目标。")
        return results, background_roi, overlays

    init_idx, init_comp = init_info
    prev_center_roi = init_comp["centroid"]
    prev_area = init_comp["area"]
    # ===== 先把初始化帧本身写入结果 =====
    if USE_AXISYMMETRIC_VOLUME_CENTROID:
        init_result = extract_axisymmetric_volume_centroid(init_comp["mask"], roi, init_idx)
    else:
        init_result = extract_target_geometry(init_comp["mask"], roi, init_idx)

    results[init_idx] = init_result

    init_roi_frame = crop_roi(stack[init_idx], roi)
    init_roi_u8 = normalize_to_uint8(init_roi_frame)
    init_overlay_bgr = cv2.cvtColor(init_roi_u8, cv2.COLOR_GRAY2BGR)

    init_contours, _ = cv2.findContours(init_comp["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(init_overlay_bgr, init_contours, -1, (0, 0, 255), 2)

    cx_roi, cy_roi = init_comp["centroid"]
    cv2.circle(init_overlay_bgr, (int(round(cx_roi)), int(round(cy_roi))), 4, (0, 255, 0), -1)

    x, y, w, h = init_comp["bbox"]
    cv2.rectangle(init_overlay_bgr, (x, y), (x + w, y + h), (255, 0, 0), 1)

    overlays[init_idx] = init_overlay_bgr

    # ===== 向前短程回填几帧，改善起始几帧可视化 =====
    backfill_start = max(VALID_FRAME_RANGE[0], init_idx - 5)

    back_prev_center = init_comp["centroid"]
    back_prev_area = init_comp["area"]

    for i in range(init_idx - 1, backfill_start - 1, -1):
        roi_frame = crop_roi(stack[i], roi)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            threshold_mode=threshold_mode,
            manual_threshold=manual_threshold,
            morph_kernel_size=morph_kernel_size
        )

        component = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            min_area=min_area,
            prev_center=back_prev_center,
            prev_area=back_prev_area,
            edge_margin=edge_margin,
            max_center_jump=max_center_jump,
            min_area_ratio_change=min_area_ratio_change,
            max_area_ratio_change=max_area_ratio_change,
            min_main_area=min_main_area,
            max_backward_jump_x=max_backward_jump_x,
            init_mode=False
        )

        roi_u8 = normalize_to_uint8(roi_frame)
        overlay_bgr = cv2.cvtColor(roi_u8, cv2.COLOR_GRAY2BGR)

        if component is None:
            continue

        if USE_AXISYMMETRIC_VOLUME_CENTROID:
            result = extract_axisymmetric_volume_centroid(component["mask"], roi, i)
        else:
            result = extract_target_geometry(component["mask"], roi, i)
        results[i] = result

        contours, _ = cv2.findContours(component["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(overlay_bgr, contours, -1, (0, 0, 255), 2)

        cx_roi, cy_roi = component["centroid"]
        cv2.circle(overlay_bgr, (int(round(cx_roi)), int(round(cy_roi))), 4, (0, 255, 0), -1)

        x, y, w, h = component["bbox"]
        cv2.rectangle(overlay_bgr, (x, y), (x + w, y + h), (255, 0, 0), 1)

        overlays[i] = overlay_bgr

        back_prev_center = component["centroid"]
        back_prev_area = component["area"]

    for i in range(init_idx, stack.shape[0]):
        roi_frame = crop_roi(stack[i], roi)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            threshold_mode=threshold_mode,
            manual_threshold=manual_threshold,
            morph_kernel_size=morph_kernel_size
        )

        component = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            min_area=min_area,
            prev_center=prev_center_roi,
            prev_area=prev_area,
            edge_margin=edge_margin,
            max_center_jump=max_center_jump,
            min_area_ratio_change=min_area_ratio_change,
            max_area_ratio_change=max_area_ratio_change,
            min_main_area=min_main_area,
            max_backward_jump_x=max_backward_jump_x,
            init_mode=False
        )

        roi_u8 = normalize_to_uint8(roi_frame)
        overlay_bgr = cv2.cvtColor(roi_u8, cv2.COLOR_GRAY2BGR)

        if component is None:
            results[i] = TargetResult(frame_idx=i, found=False)
            overlays[i] = overlay_bgr
            continue

        if USE_AXISYMMETRIC_VOLUME_CENTROID:
            result = extract_axisymmetric_volume_centroid(component["mask"], roi, i)
        else:
            result = extract_target_geometry(component["mask"], roi, i)
        results[i] = result

        contours, _ = cv2.findContours(component["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(overlay_bgr, contours, -1, (0, 0, 255), 2)

        cx_roi, cy_roi = component["centroid"]
        cv2.circle(overlay_bgr, (int(round(cx_roi)), int(round(cy_roi))), 4, (0, 255, 0), -1)

        x, y, w, h = component["bbox"]
        cv2.rectangle(overlay_bgr, (x, y), (x + w, y + h), (255, 0, 0), 1)

        overlays[i] = overlay_bgr

        prev_center_roi = component["centroid"]
        prev_area = component["area"]

    return results, background_roi, overlays


# ============================================================
# 10. 结果整理
# ============================================================

def results_to_dict(results):
    data = {
        "frame": np.array([r.frame_idx for r in results], dtype=float),
        "found": np.array([r.found for r in results], dtype=bool),
        "cx": np.array([r.cx for r in results], dtype=float),
        "cy": np.array([r.cy for r in results], dtype=float),
        "x_left": np.array([r.x_left for r in results], dtype=float),
        "x_right": np.array([r.x_right for r in results], dtype=float),
        "y_top": np.array([r.y_top for r in results], dtype=float),
        "y_bottom": np.array([r.y_bottom for r in results], dtype=float),
        "area": np.array([r.area for r in results], dtype=float),
        "radius_eq": np.array([r.radius_eq for r in results], dtype=float),
    }
    return data


def apply_valid_frame_window(data, frame_range):
    """
    只保留指定帧号区间内的数据。
    """
    f0, f1 = frame_range
    frame = data["frame"]
    mask = (frame >= f0) & (frame <= f1)

    filtered = {}
    for key, value in data.items():
        filtered[key] = value[mask]

    return filtered


# ============================================================
# 11. 平滑与运动学
# ============================================================

def moving_average_nan(x, window):
    """
    对含 NaN 的一维序列做简单滑动平均。
    """
    if window < 1:
        return x.copy()
    if window % 2 == 0:
        window += 1

    half = window // 2
    y = np.full_like(x, np.nan, dtype=float)

    for i in range(len(x)):
        left = max(0, i - half)
        right = min(len(x), i + half + 1)
        segment = x[left:right]
        if np.all(np.isnan(segment)):
            y[i] = np.nan
        else:
            y[i] = np.nanmean(segment)

    return y


def compute_kinematics(data,
                       fps,
                       motion_axis='x',
                       smooth_window=9,
                       pixel_per_mm=None):
    """
    计算位置、速度、加速度。
    """
    if motion_axis == 'x':
        pos_raw = data["cx"].copy()
    elif motion_axis == 'y':
        pos_raw = data["cy"].copy()
    else:
        raise ValueError("motion_axis 只能是 'x' 或 'y'")

    t = data["frame"] / fps

    valid = ~np.isnan(pos_raw)
    pos_interp = pos_raw.copy()

    if np.sum(valid) >= 2:
        pos_interp[~valid] = np.interp(t[~valid], t[valid], pos_raw[valid])

    pos_smooth = moving_average_nan(pos_interp, smooth_window)

    vel = np.gradient(pos_smooth, t)
    acc = np.gradient(vel, t)

    if pixel_per_mm is not None and pixel_per_mm > 0:
        pos_raw = pos_raw / pixel_per_mm
        pos_smooth = pos_smooth / pixel_per_mm
        vel = vel / pixel_per_mm
        acc = acc / pixel_per_mm
        unit = "mm"
    else:
        unit = "pixel"

    return {
        "t": t,
        "pos_raw": pos_raw,
        "pos_smooth": pos_smooth,
        "vel": vel,
        "acc": acc,
        "unit": unit
    }


def estimate_kinematic_uncertainty(kin, pixel_per_mm, fps,
                                   centroid_sigma_px=0.8,
                                   fps_rel_error=1e-4):
    """
    根据像素误差 + 平滑残差 + 帧率误差，估计速度和加速度的不确定度。

    返回：
        sigma_v, sigma_a
    单位与 kin 中一致（若 kin 为 mm，则这里也是 mm/s, mm/s^2）。
    """
    dt = 1.0 / fps

    pos_raw = kin["pos_raw"]
    pos_smooth = kin["pos_smooth"]
    vel = kin["vel"]
    acc = kin["acc"]

    # 1) 固定像素误差换算到物理单位
    sigma_x_pix = centroid_sigma_px / pixel_per_mm

    # 2) 原始位置和平滑位置的残差，作为附加拟合误差
    residual = pos_raw - pos_smooth
    residual = residual[~np.isnan(residual)]
    if len(residual) > 0:
        sigma_x_fit = np.sqrt(np.mean(residual ** 2))
    else:
        sigma_x_fit = 0.0

    sigma_x_tot = np.sqrt(sigma_x_pix ** 2 + sigma_x_fit ** 2)

    # 3) 传播到速度、加速度
    sigma_v_meas = sigma_x_tot / (np.sqrt(2.0) * dt)
    sigma_a_meas = np.sqrt(6.0) * sigma_x_tot / (dt ** 2)

    # 4) 帧率误差传播
    sigma_v_time = np.abs(vel) * fps_rel_error
    sigma_a_time = 2.0 * np.abs(acc) * fps_rel_error

    sigma_v = np.sqrt(sigma_v_meas ** 2 + sigma_v_time ** 2)
    sigma_a = np.sqrt(sigma_a_meas ** 2 + sigma_a_time ** 2)

    return sigma_v, sigma_a


def summarize_acceleration(kin):
    """
    输出加速度的：
    - 全区间值域
    - 主体部分（去掉前后各10%）的均值/中位数/标准差
    """
    acc = kin["acc"]
    t = kin["t"]

    valid = ~np.isnan(acc)
    acc = acc[valid]
    t = t[valid]

    if len(acc) == 0:
        return None

    acc_min = np.min(acc)
    acc_max = np.max(acc)

    n = len(acc)
    i0 = int(np.floor(0.1 * n))
    i1 = int(np.ceil(0.9 * n))
    acc_core = acc[i0:i1] if i1 > i0 else acc

    summary = {
        "acc_min": float(acc_min),
        "acc_max": float(acc_max),
        "acc_core_mean": float(np.mean(acc_core)),
        "acc_core_median": float(np.median(acc_core)),
        "acc_core_std": float(np.std(acc_core)),
    }
    return summary


def select_time_window(t, y, t_range):
    """
    截取指定时间窗内的数据，并自动去除 NaN。
    """
    t0, t1 = t_range
    mask = (t >= t0) & (t <= t1) & (~np.isnan(y))
    return t[mask], y[mask]


def fit_quadratic_motion(kin, fit_time_range=(0.035, 0.085)):
    """
    对位置曲线 x(t) 在核心时间段内做二次拟合：
        x(t) = c0 + c1 t + c2 t^2
    返回：
        a_fit = 2*c2
        coeffs
        residual_rms
        r2
        t_fit, x_fit_data, x_fit_curve
    """
    t = kin["t"]
    x = kin["pos_smooth"]

    t_fit, x_fit_data = select_time_window(t, x, fit_time_range)

    if len(t_fit) < 5:
        return None

    coeffs = np.polyfit(t_fit, x_fit_data, 2)
    x_pred = np.polyval(coeffs, t_fit)

    residual = x_fit_data - x_pred
    residual_rms = np.sqrt(np.mean(residual ** 2))

    ss_res = np.sum((x_fit_data - x_pred) ** 2)
    ss_tot = np.sum((x_fit_data - np.mean(x_fit_data)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    a_fit = 2.0 * coeffs[0]

    return {
        "a_fit": float(a_fit),
        "coeffs": coeffs,
        "residual_rms": float(residual_rms),
        "r2": float(r2),
        "t_fit": t_fit,
        "x_fit_data": x_fit_data,
        "x_fit_curve": x_pred,
    }


def fit_quadratic_motion_robust(data,
                                fps,
                                pixel_per_mm,
                                motion_axis='x',
                                smooth_windows=(7, 9, 11),
                                fit_time_windows=((0.036, 0.084),
                                                  (0.038, 0.082),
                                                  (0.040, 0.080))):
    """
    用多组平滑窗口 + 多组拟合时间窗，重复计算 a_fit，
    作为更稳健的敏感性分析。

    返回：
        summary: 统计结果
        fit_results: 每次拟合的详细结果
    """
    fit_results = []

    for sw in smooth_windows:
        kin_local = compute_kinematics(
            data=data,
            fps=fps,
            motion_axis=motion_axis,
            smooth_window=sw,
            pixel_per_mm=pixel_per_mm
        )

        for t_range in fit_time_windows:
            res = fit_quadratic_motion(kin_local, fit_time_range=t_range)
            if res is None:
                continue

            res["smooth_window"] = sw
            res["fit_time_range"] = t_range
            fit_results.append(res)

    if len(fit_results) == 0:
        return None, []

    a_values = np.array([r["a_fit"] for r in fit_results], dtype=float)

    summary = {
        "a_fit_mean": float(np.mean(a_values)),
        "a_fit_std": float(np.std(a_values)),
        "a_fit_median": float(np.median(a_values)),
        "a_fit_min": float(np.min(a_values)),
        "a_fit_max": float(np.max(a_values)),
        "n_fits": int(len(a_values)),
    }

    return summary, fit_results


def fit_quadratic_plus_oscillation(kin, fit_time_range=(0.035, 0.085), freq_hz=39.604):
    """
    固定频率下拟合：
        x(t) = c0 + c1*tau + c2*tau^2 + B*cos(2*pi*f*tau) + C*sin(2*pi*f*tau)

    其中：
        a_fit = 2*c2

    返回：
        a_fit
        freq_hz
        振荡幅值 amp
        相位 phase
        拟合残差 RMS
        R^2
    """
    t = kin["t"]
    x = kin["pos_smooth"]

    t_fit, x_fit = select_time_window(t, x, fit_time_range)
    if len(t_fit) < 8:
        return None

    # 时间中心化，减少参数相关性
    t_ref = np.mean(t_fit)
    tau = t_fit - t_ref
    w = 2.0 * np.pi * freq_hz

    # 线性最小二乘矩阵
    M = np.column_stack([
        np.ones_like(tau),
        tau,
        tau**2,
        np.cos(w * tau),
        np.sin(w * tau)
    ])

    coeffs, _, _, _ = np.linalg.lstsq(M, x_fit, rcond=None)
    c0, c1, c2, B, C = coeffs

    x_pred = M @ coeffs
    residual = x_fit - x_pred

    residual_rms = np.sqrt(np.mean(residual**2))
    ss_res = np.sum((x_fit - x_pred)**2)
    ss_tot = np.sum((x_fit - np.mean(x_fit))**2)
    r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else np.nan

    a_fit = 2.0 * c2
    amp = np.sqrt(B**2 + C**2)
    phase = np.arctan2(C, B)

    return {
        "a_fit": float(a_fit),
        "freq_hz": float(freq_hz),
        "amp": float(amp),
        "phase_rad": float(phase),
        "coeffs": coeffs,
        "t_fit": t_fit,
        "tau": tau,
        "x_fit_data": x_fit,
        "x_fit_curve": x_pred,
        "residual_rms": float(residual_rms),
        "r2": float(r2),
        "t_ref": float(t_ref)
    }


def fit_quadratic_plus_harmonics(kin, fit_time_range=(0.035, 0.085), base_freq_hz=39.604):
    """
    固定主频 + 二次谐波联合拟合：

        x(t) = c0 + c1*tau + c2*tau^2
             + B1*cos(w*tau) + C1*sin(w*tau)
             + B2*cos(2*w*tau) + C2*sin(2*w*tau)

    其中：
        a_fit = 2*c2

    返回：
        a_fit
        base_freq_hz
        amp1, phase1     # 主频分量
        amp2, phase2     # 二次谐波分量
        residual_rms
        r2
    """
    t = kin["t"]
    x = kin["pos_smooth"]

    t_fit, x_fit = select_time_window(t, x, fit_time_range)
    if len(t_fit) < 8:
        return None

    t_ref = np.mean(t_fit)
    tau = t_fit - t_ref
    w = 2.0 * np.pi * base_freq_hz

    M = np.column_stack([
        np.ones_like(tau),
        tau,
        tau**2,
        np.cos(w * tau),
        np.sin(w * tau),
        np.cos(2.0 * w * tau),
        np.sin(2.0 * w * tau),
    ])

    coeffs, _, _, _ = np.linalg.lstsq(M, x_fit, rcond=None)
    c0, c1, c2, B1, C1, B2, C2 = coeffs

    x_pred = M @ coeffs
    residual = x_fit - x_pred

    residual_rms = np.sqrt(np.mean(residual**2))
    ss_res = np.sum((x_fit - x_pred)**2)
    ss_tot = np.sum((x_fit - np.mean(x_fit))**2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    a_fit = 2.0 * c2

    amp1 = np.sqrt(B1**2 + C1**2)
    phase1 = np.arctan2(C1, B1)

    amp2 = np.sqrt(B2**2 + C2**2)
    phase2 = np.arctan2(C2, B2)

    return {
        "a_fit": float(a_fit),
        "base_freq_hz": float(base_freq_hz),
        "harmonic_freq_hz": float(2.0 * base_freq_hz),
        "amp1": float(amp1),
        "phase1_rad": float(phase1),
        "amp2": float(amp2),
        "phase2_rad": float(phase2),
        "coeffs": coeffs,
        "t_fit": t_fit,
        "tau": tau,
        "x_fit_data": x_fit,
        "x_fit_curve": x_pred,
        "residual": residual,
        "residual_rms": float(residual_rms),
        "r2": float(r2),
        "t_ref": float(t_ref)
    }


def fit_quadratic_plus_oscillation_scan(kin,
                                        fit_time_range=(0.035, 0.085),
                                        freq_range=(30.0, 50.0),
                                        n_freq=401):
    """
    在给定频率范围内扫描，寻找残差最小的二次+正弦联合拟合。
    """
    t = kin["t"]
    x = kin["pos_smooth"]

    t_fit, x_fit = select_time_window(t, x, fit_time_range)
    if len(t_fit) < 8:
        return None

    t_ref = np.mean(t_fit)
    tau = t_fit - t_ref

    freqs = np.linspace(freq_range[0], freq_range[1], n_freq)

    best = None
    best_rms = np.inf

    for freq_hz in freqs:
        w = 2.0 * np.pi * freq_hz
        M = np.column_stack([
            np.ones_like(tau),
            tau,
            tau**2,
            np.cos(w * tau),
            np.sin(w * tau)
        ])

        coeffs, _, _, _ = np.linalg.lstsq(M, x_fit, rcond=None)
        x_pred = M @ coeffs
        residual = x_fit - x_pred
        rms = np.sqrt(np.mean(residual**2))

        if rms < best_rms:
            c0, c1, c2, B, C = coeffs
            ss_res = np.sum((x_fit - x_pred)**2)
            ss_tot = np.sum((x_fit - np.mean(x_fit))**2)
            r2 = 1.0 - ss_res/ss_tot if ss_tot > 0 else np.nan

            best_rms = rms
            best = {
                "a_fit": float(2.0 * c2),
                "freq_hz": float(freq_hz),
                "amp": float(np.sqrt(B**2 + C**2)),
                "phase_rad": float(np.arctan2(C, B)),
                "coeffs": coeffs,
                "t_fit": t_fit,
                "tau": tau,
                "x_fit_data": x_fit,
                "x_fit_curve": x_pred,
                "residual_rms": float(rms),
                "r2": float(r2),
                "t_ref": float(t_ref),
                "scan_freqs": freqs
            }

    return best


def detrend_signal(t, y, order=2):
    """
    对一维信号做低阶多项式去趋势。
    """
    valid = ~np.isnan(y)
    t_valid = t[valid]
    y_valid = y[valid]

    if len(t_valid) < 5:
        return t_valid, y_valid, y_valid, np.zeros_like(y_valid)

    coeffs = np.polyfit(t_valid, y_valid, order)
    trend = np.polyval(coeffs, t_valid)
    y_detrended = y_valid - trend

    return t_valid, y_valid, trend, y_detrended


def dominant_frequency_fft(t, y):
    """
    对等间隔时间序列做 FFT，返回主频。
    """
    if len(t) < 8:
        return None

    dt = np.mean(np.diff(t))
    y0 = y - np.mean(y)

    Y = np.fft.rfft(y0)
    f = np.fft.rfftfreq(len(y0), d=dt)

    # 去掉 0 频
    if len(f) <= 1:
        return None

    amp = np.abs(Y)
    amp[0] = 0.0

    idx = np.argmax(amp)
    return {
        "freq": float(f[idx]),
        "amp": float(amp[idx]),
        "freq_axis": f,
        "amp_spectrum": amp
    }


def analyze_geometry_oscillation(data, fps, time_range=(0.035, 0.085)):
    """
    对 L(t), W(t), A(t) 做去趋势与主频分析。
    """
    t = data["frame"] / fps
    L = data["y_bottom"] - data["y_top"]
    W = data["x_right"] - data["x_left"]
    A = data["area"]

    result = {}

    for name, signal in [("L", L), ("W", W), ("A", A)]:
        t_sel, y_sel = select_time_window(t, signal, time_range)
        if len(t_sel) < 8:
            result[name] = None
            continue

        t_d, y_raw, trend, y_det = detrend_signal(t_sel, y_sel, order=2)
        fft_res = dominant_frequency_fft(t_d, y_det)

        result[name] = {
            "t": t_d,
            "raw": y_raw,
            "trend": trend,
            "detrended": y_det,
            "fft": fft_res
        }

    return result


def analyze_signal_fft(t, y, time_range=None):
    """
    对指定时间窗内的一维信号做 FFT，返回主频和频谱。
    """
    y = np.asarray(y, dtype=float)
    t = np.asarray(t, dtype=float)

    if time_range is not None:
        t, y = select_time_window(t, y, time_range)

    valid = ~np.isnan(y)
    t = t[valid]
    y = y[valid]

    if len(t) < 8:
        return None

    dt = np.mean(np.diff(t))
    y0 = y - np.mean(y)

    Y = np.fft.rfft(y0)
    f = np.fft.rfftfreq(len(y0), d=dt)
    amp = np.abs(Y)

    if len(amp) > 0:
        amp[0] = 0.0

    idx = np.argmax(amp)
    return {
        "t": t,
        "y": y,
        "freq": float(f[idx]),
        "amp": float(amp[idx]),
        "freq_axis": f,
        "amp_spectrum": amp
    }


def analyze_acceleration_fft(kin, time_range=(0.035, 0.085)):
    """
    分析加速度信号在核心时间窗内的频谱。
    """
    return analyze_signal_fft(
        t=kin["t"],
        y=kin["acc"],
        time_range=time_range
    )


def plot_acceleration_fft(acc_fft_result, output_dir):
    """
    绘制加速度频谱图。
    """
    if acc_fft_result is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 4))
    plt.plot(acc_fft_result["freq_axis"], acc_fft_result["amp_spectrum"])
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Acceleration amplitude")
    plt.title("Acceleration FFT (dominant frequency = {:.2f} Hz)".format(acc_fft_result["freq"]))
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "acceleration_fft.png", dpi=200)
    plt.close()


def lowpass_filter_fft(t, y, cutoff_hz):
    """
    使用 FFT 实现简单低通滤波。
    输入信号应近似等间隔采样。
    """
    y = np.asarray(y, dtype=float)
    t = np.asarray(t, dtype=float)

    valid = ~np.isnan(y)
    if np.sum(valid) < 8:
        return y.copy()

    # 若有 NaN，先线性插值
    y_filled = y.copy()
    if np.any(~valid):
        y_filled[~valid] = np.interp(t[~valid], t[valid], y[valid])

    dt = np.mean(np.diff(t))
    Y = np.fft.rfft(y_filled)
    f = np.fft.rfftfreq(len(y_filled), d=dt)

    Y_filtered = Y.copy()
    Y_filtered[f > cutoff_hz] = 0.0

    y_low = np.fft.irfft(Y_filtered, n=len(y_filled))
    return y_low


def compute_kinematics_lowpass(data,
                               fps,
                               motion_axis='x',
                               pixel_per_mm=None,
                               cutoff_hz=10.0):
    """
    基于位置低通滤波的运动学重建：
    1) 取位置
    2) 低通滤波
    3) 再求速度和加速度
    """
    if motion_axis == 'x':
        pos_raw = data["cx"].copy()
    elif motion_axis == 'y':
        pos_raw = data["cy"].copy()
    else:
        raise ValueError("motion_axis 只能是 'x' 或 'y'")

    t = data["frame"] / fps

    valid = ~np.isnan(pos_raw)
    pos_interp = pos_raw.copy()

    if np.sum(valid) >= 2:
        pos_interp[~valid] = np.interp(t[~valid], t[valid], pos_raw[valid])

    # 单位换算前低通 or 后低通都可以；这里先换成物理量更直观
    if pixel_per_mm is not None and pixel_per_mm > 0:
        pos_interp_phys = pos_interp / pixel_per_mm
        pos_raw_phys = pos_raw / pixel_per_mm
        unit = "mm"
    else:
        pos_interp_phys = pos_interp
        pos_raw_phys = pos_raw
        unit = "pixel"

    pos_low = lowpass_filter_fft(t, pos_interp_phys, cutoff_hz=cutoff_hz)

    vel_low = np.gradient(pos_low, t)
    acc_low = np.gradient(vel_low, t)

    return {
        "t": t,
        "pos_raw": pos_raw_phys,
        "pos_lowpass": pos_low,
        "vel_lowpass": vel_low,
        "acc_lowpass": acc_low,
        "unit": unit,
        "cutoff_hz": cutoff_hz
    }


# ============================================================
# 12. 可视化输出
# ============================================================

def save_preview_images(stack, roi, background_roi, overlays, output_dir):
    """
    保存全图 ROI、背景图、全段抽样追踪预览。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    full0 = draw_roi_on_frame(stack[0], roi)
    plt.figure(figsize=(14, 6))
    plt.imshow(cv2.cvtColor(full0, cv2.COLOR_BGR2RGB))
    plt.title("Frame 0 with ROI")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_dir / "frame0_with_roi.png", dpi=200, bbox_inches="tight")
    plt.close()

    plt.figure(figsize=(12, 3))
    plt.imshow(normalize_to_uint8(background_roi), cmap='gray')
    plt.title("Estimated background in ROI")
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_dir / "background_roi.png", dpi=200, bbox_inches="tight")
    plt.close()

    n = len(overlays)
    idx_list = np.linspace(0, n - 1, min(6, n), dtype=int)

    plt.figure(figsize=(15, 8))
    for j, idx in enumerate(idx_list, start=1):
        plt.subplot(2, 3, j)
        plt.imshow(cv2.cvtColor(overlays[idx], cv2.COLOR_BGR2RGB))
        plt.title("Tracked ROI - frame {}".format(idx))
        plt.axis("off")
    plt.tight_layout()
    plt.savefig(output_dir / "tracking_preview.png", dpi=200, bbox_inches="tight")
    plt.close()


def save_valid_window_preview(stack, results, roi, fps, frame_range, output_dir):
    """
    只导出有效帧区间内的若干帧跟踪预览。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    f0, f1 = frame_range
    valid_indices = np.arange(max(0, f0), min(len(results), f1 + 1))

    if len(valid_indices) == 0:
        return

    show_indices = np.linspace(valid_indices[0], valid_indices[-1], min(6, len(valid_indices)), dtype=int)

    plt.figure(figsize=(15, 8))
    for j, idx in enumerate(show_indices, start=1):
        frame = stack[idx]
        roi_frame = crop_roi(frame, roi)
        roi_u8 = normalize_to_uint8(roi_frame)
        disp = cv2.cvtColor(roi_u8, cv2.COLOR_GRAY2BGR)

        r = results[idx]
        if r.found:
            x0, y0, _, _ = roi
            cx = int(round(r.cx - x0))
            cy = int(round(r.cy - y0))
            xl = int(round(r.x_left - x0))
            xr = int(round(r.x_right - x0))
            yt = int(round(r.y_top - y0))
            yb = int(round(r.y_bottom - y0))

            cv2.circle(disp, (cx, cy), 4, (0, 255, 0), -1)
            cv2.rectangle(disp, (xl, yt), (xr, yb), (255, 0, 0), 2)

        plt.subplot(2, 3, j)
        plt.imshow(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB))
        plt.title("Valid-window frame {}\nt={:.4f}s".format(idx, idx/fps))
        plt.axis("off")

    plt.tight_layout()
    plt.savefig(output_dir / "valid_window_tracking_preview.png", dpi=200, bbox_inches="tight")
    plt.close()


def plot_target_area(data, fps, output_dir):
    """
    绘制主目标面积（像素数）随时间变化。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = data["frame"] / fps
    area = data["area"]

    plt.figure(figsize=(10, 4))
    plt.plot(t, area, 'o-', ms=3, lw=1.5)
    plt.xlabel("Time (s)")
    plt.ylabel("Target area [pixels]")
    plt.title("Main target area")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "target_area.png", dpi=200)
    plt.close()


def plot_kinematics(data, kin, motion_axis, output_dir):
    """
    绘制位置、速度、加速度、几何量。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = kin["t"]
    unit = kin["unit"]

    plt.figure(figsize=(10, 4))
    plt.plot(t, kin["pos_raw"], 'o-', ms=3, label="raw position")
    plt.plot(t, kin["pos_smooth"], '-', lw=2, label="smoothed position")
    plt.xlabel("Time (s)")
    plt.ylabel("{}(centroid) [{}]".format(motion_axis, unit))
    plt.title("Position")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "position.png", dpi=200)
    plt.close()

    plt.figure(figsize=(10, 4))
    plt.plot(t, kin["vel"], '-', lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel("Velocity [{}/s]".format(unit))
    plt.title("Velocity")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "velocity.png", dpi=200)
    plt.close()

    plt.figure(figsize=(10, 4))
    plt.plot(t, kin["acc"], '-', lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel("Acceleration [{}/s$^2$]".format(unit))
    plt.title("Acceleration")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "acceleration.png", dpi=200)
    plt.close()

    length = data["y_bottom"] - data["y_top"]
    width = data["x_right"] - data["x_left"]

    plt.figure(figsize=(10, 4))
    plt.plot(t, length, label="length = y_bottom - y_top")
    plt.plot(t, width, label="width = x_right - x_left")
    plt.xlabel("Time (s)")
    plt.ylabel("Pixels")
    plt.title("Basic geometry")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "geometry.png", dpi=200)
    plt.close()


def plot_core_kinematics_zoom(kin, output_dir, core_time_range=(0.035, 0.085)):
    """
    对主流时间段输出速度/加速度放大图，避免被起始尖峰和末端异常拉伸纵轴。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = kin["t"]
    vel = kin["vel"]
    acc = kin["acc"]
    unit = kin["unit"]

    t0, t1 = core_time_range
    mask = (t >= t0) & (t <= t1)

    if np.sum(mask) < 5:
        return

    t_core = t[mask]
    vel_core = vel[mask]
    acc_core = acc[mask]

    # ---- 速度放大图 ----
    plt.figure(figsize=(10, 4))
    plt.plot(t_core, vel_core, '-', lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Velocity [{unit}/s]")
    plt.title("Velocity (core window zoom)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "velocity_core_zoom.png", dpi=200)
    plt.close()

    # ---- 加速度放大图 ----
    plt.figure(figsize=(10, 4))
    plt.plot(t_core, acc_core, '-', lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Acceleration (core window zoom)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "acceleration_core_zoom.png", dpi=200)
    plt.close()


def plot_core_kinematics_with_band(kin, output_dir,
                                   core_time_range=(0.035, 0.085),
                                   pixel_per_mm=None,
                                   fps=2000.0,
                                   centroid_sigma_px=0.8,
                                   fps_rel_error=1e-4):
    """
    输出带不确定度条带的核心段速度/加速度图。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = kin["t"]
    vel = kin["vel"]
    acc = kin["acc"]
    unit = kin["unit"]

    sigma_v, sigma_a = estimate_kinematic_uncertainty(
        kin=kin,
        pixel_per_mm=pixel_per_mm,
        fps=fps,
        centroid_sigma_px=centroid_sigma_px,
        fps_rel_error=fps_rel_error
    )

    t0, t1 = core_time_range
    mask = (t >= t0) & (t <= t1)

    if np.sum(mask) < 5:
        return

    t_core = t[mask]
    vel_core = vel[mask]
    acc_core = acc[mask]
    sv_core = sigma_v[mask]
    sa_core = sigma_a[mask]

    # 速度图 + 条带
    plt.figure(figsize=(10, 4))
    plt.plot(t_core, vel_core, '-', lw=2, label="velocity")
    plt.fill_between(t_core,
                     vel_core - 2.0 * sv_core,
                     vel_core + 2.0 * sv_core,
                     alpha=0.25,
                     label="~95% uncertainty band")
    plt.xlabel("Time (s)")
    plt.ylabel(f"Velocity [{unit}/s]")
    plt.title("Velocity (core window, with uncertainty band)")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "velocity_core_band.png", dpi=200)
    plt.close()

    # 加速度图 + 条带
    plt.figure(figsize=(10, 4))
    plt.plot(t_core, acc_core, '-', lw=2, label="acceleration")
    plt.fill_between(t_core,
                     acc_core - 2.0 * sa_core,
                     acc_core + 2.0 * sa_core,
                     alpha=0.25,
                     label="~95% uncertainty band")
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Acceleration (core window, with uncertainty band)")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "acceleration_core_band.png", dpi=200)
    plt.close()


def plot_core_acceleration_robust(kin, output_dir, core_time_range=(0.035, 0.085)):
    """
    输出主流段加速度的稳健纵轴图：
    用分位数而不是全局极值设定 y 轴，避免少数尖峰压扁主流波动。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = kin["t"]
    acc = kin["acc"]
    unit = kin["unit"]

    t0, t1 = core_time_range
    mask = (t >= t0) & (t <= t1)

    if np.sum(mask) < 5:
        return

    t_core = t[mask]
    acc_core = acc[mask]

    # 用 2% 和 98% 分位数设置纵轴，再留一点边
    q_low, q_high = np.percentile(acc_core, [2, 98])
    pad = 0.1 * max(1e-12, q_high - q_low)

    plt.figure(figsize=(10, 4))
    plt.plot(t_core, acc_core, '-', lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Acceleration (core window, robust y-limit)")
    plt.ylim(q_low - pad, q_high + pad)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "acceleration_core_robust.png", dpi=200)
    plt.close()


def plot_quadratic_fit(kin, fit_result, output_dir):
    """
    绘制核心段位置与二次拟合曲线。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = kin["t"]
    x = kin["pos_smooth"]

    plt.figure(figsize=(10, 4))
    plt.plot(t, x, '-', lw=1.5, label="smoothed position")
    plt.plot(fit_result["t_fit"], fit_result["x_fit_curve"], '--', lw=2, label="quadratic fit")
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic fit of centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "quadratic_fit_position.png", dpi=200)
    plt.close()


def plot_quadratic_fit_robust_summary(fit_results, summary, output_dir):
    """
    可视化不同参数组合得到的 a_fit 分布。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    a_values = np.array([r["a_fit"] for r in fit_results], dtype=float)
    idx = np.arange(len(a_values))

    plt.figure(figsize=(10, 4))
    plt.plot(idx, a_values, 'o-', label="a_fit from each setting")
    plt.axhline(summary["a_fit_mean"], linestyle='--', label="mean")
    plt.axhline(summary["a_fit_median"], linestyle=':', label="median")
    plt.fill_between(idx,
                     summary["a_fit_mean"] - summary["a_fit_std"],
                     summary["a_fit_mean"] + summary["a_fit_std"],
                     alpha=0.2,
                     label="mean ± std")
    plt.xlabel("Fit case index")
    plt.ylabel("a_fit [mm/s$^2$]")
    plt.title("Robustness of quadratic-fit acceleration")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "quadratic_fit_robust_summary.png", dpi=200)
    plt.close()


def plot_quadratic_plus_oscillation_fit(kin, fit_result, output_dir):
    """
    绘制位置曲线与“二次+振动”同步拟合结果。
    """
    if fit_result is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 4))
    plt.plot(kin["t"], kin["pos_smooth"], '-', lw=1.5, label="smoothed position")
    plt.plot(fit_result["t_fit"], fit_result["x_fit_curve"], '--', lw=2,
             label="quadratic + oscillation fit")
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic + oscillation fit of centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "quadratic_plus_oscillation_fit.png", dpi=200)
    plt.close()


def plot_quadratic_plus_harmonics_fit(kin, fit_result, output_dir):
    """
    绘制位置曲线与“二次 + 主频 + 二次谐波”联合拟合结果。
    """
    if fit_result is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 4))
    plt.plot(kin["t"], kin["pos_smooth"], '-', lw=1.5, label="smoothed position")
    plt.plot(fit_result["t_fit"], fit_result["x_fit_curve"], '--', lw=2,
             label="quadratic + fundamental + 2nd harmonic")
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic + harmonic-constrained fit of centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "quadratic_plus_harmonics_fit.png", dpi=200)
    plt.close()


def plot_oscillation_component(fit_result, output_dir):
    """
    绘制振动部分与残差，用于检查同步拟合是否合理。
    """
    if fit_result is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    coeffs = fit_result["coeffs"]
    tau = fit_result["tau"]
    x_data = fit_result["x_fit_data"]
    x_pred = fit_result["x_fit_curve"]

    c0, c1, c2, B, C = coeffs
    quad_part = c0 + c1*tau + c2*tau**2
    osc_part = B*np.cos(2*np.pi*fit_result["freq_hz"]*tau) + C*np.sin(2*np.pi*fit_result["freq_hz"]*tau)
    residual = x_data - x_pred

    plt.figure(figsize=(10, 6))

    plt.subplot(2, 1, 1)
    plt.plot(fit_result["t_fit"], osc_part, lw=2, label="fitted oscillation component")
    plt.xlabel("Time (s)")
    plt.ylabel("Oscillation [mm]")
    plt.title("Oscillation component")
    plt.grid(alpha=0.3)
    plt.legend()

    plt.subplot(2, 1, 2)
    plt.plot(fit_result["t_fit"], residual, lw=1.5, label="residual")
    plt.xlabel("Time (s)")
    plt.ylabel("Residual [mm]")
    plt.title("Fit residual")
    plt.grid(alpha=0.3)
    plt.legend()

    plt.tight_layout()
    plt.savefig(output_dir / "oscillation_component_and_residual.png", dpi=200)
    plt.close()


def plot_harmonic_components_and_residual(fit_result, output_dir):
    """
    绘制：
    1) 主频分量
    2) 二次谐波分量
    3) 残差
    """
    if fit_result is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    coeffs = fit_result["coeffs"]
    tau = fit_result["tau"]
    t_fit = fit_result["t_fit"]
    residual = fit_result["residual"]

    c0, c1, c2, B1, C1, B2, C2 = coeffs
    f0 = fit_result["base_freq_hz"]
    w = 2.0 * np.pi * f0

    osc1 = B1 * np.cos(w * tau) + C1 * np.sin(w * tau)
    osc2 = B2 * np.cos(2.0 * w * tau) + C2 * np.sin(2.0 * w * tau)

    plt.figure(figsize=(10, 8))

    plt.subplot(3, 1, 1)
    plt.plot(t_fit, osc1, lw=2, label="fundamental component")
    plt.xlabel("Time (s)")
    plt.ylabel("Fundamental [mm]")
    plt.title("Fundamental component ({:.3f} Hz)".format(f0))
    plt.grid(alpha=0.3)
    plt.legend()

    plt.subplot(3, 1, 2)
    plt.plot(t_fit, osc2, lw=2, label="2nd harmonic component")
    plt.xlabel("Time (s)")
    plt.ylabel("2nd harmonic [mm]")
    plt.title("Second harmonic component ({:.3f} Hz)".format(2.0 * f0))
    plt.grid(alpha=0.3)
    plt.legend()

    plt.subplot(3, 1, 3)
    plt.plot(t_fit, residual, lw=1.5, label="residual")
    plt.xlabel("Time (s)")
    plt.ylabel("Residual [mm]")
    plt.title("Fit residual")
    plt.grid(alpha=0.3)
    plt.legend()

    plt.tight_layout()
    plt.savefig(output_dir / "harmonic_components_and_residual.png", dpi=200)
    plt.close()


def plot_geometry_detrended(geom_result, output_dir):
    """
    绘制 L/W/A 的去趋势结果。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(12, 8))

    plot_id = 1
    for name in ["L", "W", "A"]:
        if geom_result.get(name) is None:
            continue

        res = geom_result[name]

        plt.subplot(3, 1, plot_id)
        plt.plot(res["t"], res["raw"], label=f"{name} raw")
        plt.plot(res["t"], res["trend"], '--', label=f"{name} trend")
        plt.plot(res["t"], res["detrended"], label=f"{name} detrended")
        plt.xlabel("Time (s)")
        plt.ylabel(name)
        plt.grid(alpha=0.3)
        plt.legend()
        plot_id += 1

    plt.tight_layout()
    plt.savefig(output_dir / "geometry_detrended.png", dpi=200)
    plt.close()


def plot_geometry_fft(geom_result, output_dir):
    """
    绘制 L/W/A 的频谱图。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(12, 8))

    plot_id = 1
    for name in ["L", "W", "A"]:
        if geom_result.get(name) is None:
            continue
        if geom_result[name]["fft"] is None:
            continue

        fft_res = geom_result[name]["fft"]

        plt.subplot(3, 1, plot_id)
        plt.plot(fft_res["freq_axis"], fft_res["amp_spectrum"])
        plt.xlabel("Frequency (Hz)")
        plt.ylabel(f"{name} amplitude")
        plt.title(f"{name} dominant frequency = {fft_res['freq']:.2f} Hz")
        plt.grid(alpha=0.3)
        plot_id += 1

    plt.tight_layout()
    plt.savefig(output_dir / "geometry_fft.png", dpi=200)
    plt.close()


def plot_lowpass_kinematics(kin_low, output_dir, core_time_range=(0.035, 0.085)):
    """
    绘制低通后的位置、速度、加速度核心段图。
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    t = kin_low["t"]
    unit = kin_low["unit"]
    cutoff = kin_low["cutoff_hz"]

    t0, t1 = core_time_range
    mask = (t >= t0) & (t <= t1)

    if np.sum(mask) < 5:
        return

    t_core = t[mask]
    pos_core = kin_low["pos_lowpass"][mask]
    vel_core = kin_low["vel_lowpass"][mask]
    acc_core = kin_low["acc_lowpass"][mask]

    plt.figure(figsize=(10, 4))
    plt.plot(t_core, pos_core, lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Position [{unit}]")
    plt.title(f"Low-pass position (cutoff = {cutoff:.1f} Hz)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "position_lowpass_core.png", dpi=200)
    plt.close()

    plt.figure(figsize=(10, 4))
    plt.plot(t_core, vel_core, lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Velocity [{unit}/s]")
    plt.title(f"Low-pass velocity (cutoff = {cutoff:.1f} Hz)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "velocity_lowpass_core.png", dpi=200)
    plt.close()

    plt.figure(figsize=(10, 4))
    plt.plot(t_core, acc_core, lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title(f"Low-pass acceleration (cutoff = {cutoff:.1f} Hz)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(output_dir / "acceleration_lowpass_core.png", dpi=200)
    plt.close()


def fit_quadratic_motion_lowpass(kin_low, fit_time_range=(0.035, 0.085)):
    """
    对低通后的位置曲线做二次拟合。
    """
    t = kin_low["t"]
    x = kin_low["pos_lowpass"]

    t_fit, x_fit_data = select_time_window(t, x, fit_time_range)

    if len(t_fit) < 5:
        return None

    coeffs = np.polyfit(t_fit, x_fit_data, 2)
    x_pred = np.polyval(coeffs, t_fit)

    residual = x_fit_data - x_pred
    residual_rms = np.sqrt(np.mean(residual ** 2))

    ss_res = np.sum((x_fit_data - x_pred) ** 2)
    ss_tot = np.sum((x_fit_data - np.mean(x_fit_data)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    a_fit = 2.0 * coeffs[0]

    return {
        "a_fit": float(a_fit),
        "coeffs": coeffs,
        "residual_rms": float(residual_rms),
        "r2": float(r2),
        "t_fit": t_fit,
        "x_fit_data": x_fit_data,
        "x_fit_curve": x_pred,
    }


def plot_quadratic_fit_lowpass(kin_low, fit_result, output_dir):
    """
    绘制低通位置与二次拟合曲线。
    """
    if fit_result is None:
        return

    output_dir.mkdir(parents=True, exist_ok=True)

    plt.figure(figsize=(10, 4))
    plt.plot(kin_low["t"], kin_low["pos_lowpass"], '-', lw=1.5, label="low-pass position")
    plt.plot(fit_result["t_fit"], fit_result["x_fit_curve"], '--', lw=2, label="quadratic fit")
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic fit of low-pass centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(output_dir / "quadratic_fit_lowpass_position.png", dpi=200)
    plt.close()


def save_initial_debug_panels(stack,
                              roi,
                              background_roi,
                              output_dir,
                              frame_range,
                              threshold_mode,
                              manual_threshold,
                              morph_kernel_size,
                              min_area,
                              min_main_area):
    """
    输出有效区间起始附近若干帧的四联调试图：
    1) 原始 ROI
    2) 差分图
    3) 二值 mask
    4) 候选目标与评分
    """
    debug_dir = output_dir / "debug_init_frames"
    debug_dir.mkdir(parents=True, exist_ok=True)

    f0, f1 = frame_range
    end_frame = min(f0 + 12, stack.shape[0])

    prev_center = None
    prev_area = None

    for idx in range(f0, end_frame):
        roi_frame = crop_roi(stack[idx], roi)

        frame_u8 = normalize_to_uint8(roi_frame)
        bg_u8 = normalize_to_uint8(background_roi)
        diff = cv2.absdiff(frame_u8, bg_u8)

        mask = build_foreground_mask(
            frame_roi=roi_frame,
            background_roi=background_roi,
            threshold_mode=threshold_mode,
            manual_threshold=manual_threshold,
            morph_kernel_size=morph_kernel_size
        )

        selected, scored = select_main_component(
            mask=mask,
            roi_shape=roi_frame.shape,
            min_area=min_area,
            prev_center=prev_center,
            prev_area=prev_area,
            edge_margin=EDGE_MARGIN,
            max_center_jump=MAX_CENTER_JUMP,
            min_area_ratio_change=MIN_AREA_RATIO_CHANGE,
            max_area_ratio_change=MAX_AREA_RATIO_CHANGE,
            min_main_area=min_main_area,
            max_backward_jump_x=MAX_BACKWARD_JUMP_X,
            init_mode=(idx == f0),
            return_all_scored=True
        )

        overlay = cv2.cvtColor(frame_u8, cv2.COLOR_GRAY2BGR)

        for i, c in enumerate(scored):
            x, y, w, h = c["bbox"]
            cx, cy = c["centroid"]
            score = c.get("score", 0.0)
            area = c["area"]

            color = (0, 255, 255)
            if i == 0:
                color = (0, 0, 255)

            cv2.rectangle(overlay, (x, y), (x+w, y+h), color, 2)
            cv2.circle(overlay, (int(round(cx)), int(round(cy))), 3, color, -1)
            text = "A={:.0f}, S={:.1f}".format(area, score)
            cv2.putText(overlay, text, (x, max(12, y-4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

        plt.figure(figsize=(14, 8))

        plt.subplot(2, 2, 1)
        plt.imshow(frame_u8, cmap='gray')
        plt.title("Raw ROI - frame {}".format(idx))
        plt.axis("off")

        plt.subplot(2, 2, 2)
        plt.imshow(diff, cmap='gray')
        plt.title("Background difference")
        plt.axis("off")

        plt.subplot(2, 2, 3)
        plt.imshow(mask, cmap='gray')
        plt.title("Binary mask")
        plt.axis("off")

        plt.subplot(2, 2, 4)
        plt.imshow(cv2.cvtColor(overlay, cv2.COLOR_BGR2RGB))
        plt.title("Candidates and selected component")
        plt.axis("off")

        plt.tight_layout()
        plt.savefig(debug_dir / "debug_frame_{:04d}.png".format(idx), dpi=200, bbox_inches="tight")
        plt.close()

        if selected is not None:
            prev_center = selected["centroid"]
            prev_area = selected["area"]
        else:
            prev_center = None
            prev_area = None


# ============================================================
# 13. 主程序
# ============================================================

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("Step 1: 读取 TIFF")
    stack = read_tiff_stack(TIFF_PATH)
    print("TIFF shape = {}".format(stack.shape))

    print("=" * 60)
    print("Step 2: 追踪 ROI 内主目标")
    results, background_roi, overlays = track_target_over_stack(
        stack=stack,
        roi=ROI,
        threshold_mode=THRESHOLD_MODE,
        manual_threshold=MANUAL_THRESHOLD,
        background_sample_count=BACKGROUND_SAMPLE_COUNT,
        min_area=MIN_AREA,
        morph_kernel_size=MORPH_KERNEL_SIZE,
        edge_margin=EDGE_MARGIN,
        max_center_jump=MAX_CENTER_JUMP,
        min_area_ratio_change=MIN_AREA_RATIO_CHANGE,
        max_area_ratio_change=MAX_AREA_RATIO_CHANGE,
        min_main_area=MIN_MAIN_AREA,
        max_backward_jump_x=MAX_BACKWARD_JUMP_X
    )

    print("=" * 60)
    print("Step 3: 整理结果并计算运动学")
    data = results_to_dict(results)

    data_valid = apply_valid_frame_window(
        data=data,
        frame_range=VALID_FRAME_RANGE
    )

    kin = compute_kinematics(
        data=data_valid,
        fps=FPS,
        motion_axis=MOTION_AXIS,
        smooth_window=SMOOTH_WINDOW,
        pixel_per_mm=PIXEL_PER_MM
    )

    # ===== 低通滤波版运动学（尽量去掉约40 Hz形变模态） =====
    kin_low = compute_kinematics_lowpass(
        data=data_valid,
        fps=FPS,
        motion_axis=MOTION_AXIS,
        pixel_per_mm=PIXEL_PER_MM,
        cutoff_hz=LOWPASS_CUTOFF_HZ
    )

    print("=" * 60)
    print("Step 4: 导出预览图与曲线")

    # ===== 二次拟合：主结果 =====
    quad_fit = fit_quadratic_motion(
        kin=kin,
        fit_time_range=QUAD_FIT_TIME_RANGE
    )

    if quad_fit is not None:
        plot_quadratic_fit(
            kin=kin,
            fit_result=quad_fit,
            output_dir=OUTPUT_DIR
        )

    # ===== 二次拟合：稳健敏感性分析 =====
    quad_summary, quad_fit_results = fit_quadratic_motion_robust(
        data=data_valid,
        fps=FPS,
        pixel_per_mm=PIXEL_PER_MM,
        motion_axis=MOTION_AXIS,
        smooth_windows=FIT_SMOOTH_WINDOWS,
        fit_time_windows=FIT_TIME_WINDOWS
    )

    if quad_summary is not None:
        plot_quadratic_fit_robust_summary(
            fit_results=quad_fit_results,
            summary=quad_summary,
            output_dir=OUTPUT_DIR
        )

    # ===== 几何振荡频率分析 =====
    geom_result = analyze_geometry_oscillation(
        data=data_valid,
        fps=FPS,
        time_range=GEOM_ANALYSIS_TIME_RANGE
    )

    plot_geometry_detrended(
        geom_result=geom_result,
        output_dir=OUTPUT_DIR
    )

    plot_geometry_fft(
        geom_result=geom_result,
        output_dir=OUTPUT_DIR
    )

    save_preview_images(
        stack=stack,
        roi=ROI,
        background_roi=background_roi,
        overlays=overlays,
        output_dir=OUTPUT_DIR
    )

    save_valid_window_preview(
        stack=stack,
        results=results,
        roi=ROI,
        fps=FPS,
        frame_range=VALID_FRAME_RANGE,
        output_dir=OUTPUT_DIR
    )

    plot_target_area(
        data=data_valid,
        fps=FPS,
        output_dir=OUTPUT_DIR
    )

    plot_kinematics(
        data=data_valid,
        kin=kin,
        motion_axis=MOTION_AXIS,
        output_dir=OUTPUT_DIR
    )

    plot_lowpass_kinematics(
        kin_low=kin_low,
        output_dir=OUTPUT_DIR,
        core_time_range=CORE_TIME_RANGE
    )

    plot_core_kinematics_zoom(
        kin=kin,
        output_dir=OUTPUT_DIR,
        core_time_range=(0.035, 0.085)
    )

    plot_core_acceleration_robust(
        kin=kin,
        output_dir=OUTPUT_DIR,
        core_time_range=(0.035, 0.085)
    )

    # ===== 加速度频谱分析 =====
    acc_fft_result = analyze_acceleration_fft(
        kin=kin,
        time_range=ACC_FFT_TIME_RANGE
    )

    plot_acceleration_fft(
        acc_fft_result=acc_fft_result,
        output_dir=OUTPUT_DIR
    )

    # ===== 低通后二次拟合 =====
    quad_fit_low = fit_quadratic_motion_lowpass(
        kin_low=kin_low,
        fit_time_range=QUAD_FIT_TIME_RANGE
    )

    if quad_fit_low is not None:
        plot_quadratic_fit_lowpass(
            kin_low=kin_low,
            fit_result=quad_fit_low,
            output_dir=OUTPUT_DIR
        )

    # ===== 二次 + 振动同步拟合 =====
    quad_osc_fit = None

    if USE_QUAD_OSC_FIT:
        if USE_FREQ_SCAN:
            quad_osc_fit = fit_quadratic_plus_oscillation_scan(
                kin=kin,
                fit_time_range=QUAD_FIT_TIME_RANGE,
                freq_range=FREQ_SCAN_RANGE,
                n_freq=FREQ_SCAN_NUM
            )
        else:
            quad_osc_fit = fit_quadratic_plus_oscillation(
                kin=kin,
                fit_time_range=QUAD_FIT_TIME_RANGE,
                freq_hz=SHAPE_FREQ_HZ
            )

        if quad_osc_fit is not None:
            plot_quadratic_plus_oscillation_fit(
                kin=kin,
                fit_result=quad_osc_fit,
                output_dir=OUTPUT_DIR
            )

            plot_oscillation_component(
                fit_result=quad_osc_fit,
                output_dir=OUTPUT_DIR
            )

    # ===== 固定主频 + 二次谐波联合拟合 =====
    quad_harm_fit = None

    if USE_QUAD_OSC_HARMONIC_FIT:
        quad_harm_fit = fit_quadratic_plus_harmonics(
            kin=kin,
            fit_time_range=QUAD_FIT_TIME_RANGE,
            base_freq_hz=SHAPE_FREQ_HZ
        )

        if quad_harm_fit is not None:
            plot_quadratic_plus_harmonics_fit(
                kin=kin,
                fit_result=quad_harm_fit,
                output_dir=OUTPUT_DIR
            )

            plot_harmonic_components_and_residual(
                fit_result=quad_harm_fit,
                output_dir=OUTPUT_DIR
            )

    # plot_core_kinematics_with_band(
    #     kin=kin,
    #     output_dir=OUTPUT_DIR,
    #     core_time_range=CORE_TIME_RANGE,
    #     pixel_per_mm=PIXEL_PER_MM,
    #     fps=FPS,
    #     centroid_sigma_px=CENTROID_SIGMA_PX,
    #     fps_rel_error=FPS_REL_ERROR
    # )

    save_initial_debug_panels(
        stack=stack,
        roi=ROI,
        background_roi=background_roi,
        output_dir=OUTPUT_DIR,
        frame_range=VALID_FRAME_RANGE,
        threshold_mode=THRESHOLD_MODE,
        manual_threshold=MANUAL_THRESHOLD,
        morph_kernel_size=MORPH_KERNEL_SIZE,
        min_area=MIN_AREA,
        min_main_area=MIN_MAIN_AREA
    )

    found_count = int(np.sum(data["found"]))
    total_count = len(data["found"])
    print("成功识别帧数: {} / {}".format(found_count, total_count))

    valid_vel = ~np.isnan(kin["vel"])
    if np.any(valid_vel):
        print("有效区间速度范围: {:.4f} ~ {:.4f} {}/s".format(
            np.nanmin(kin["vel"]), np.nanmax(kin["vel"]), kin["unit"])
        )

    acc_summary = summarize_acceleration(kin)
    if acc_summary is not None:
        print("有效区间加速度范围: {:.4f} ~ {:.4f} {}/s^2".format(
            acc_summary["acc_min"], acc_summary["acc_max"], kin["unit"])
        )
        print("主体部分加速度均值: {:.4f} {}/s^2".format(
            acc_summary["acc_core_mean"], kin["unit"])
        )
        print("主体部分加速度中位数: {:.4f} {}/s^2".format(
            acc_summary["acc_core_median"], kin["unit"])
        )
        print("主体部分加速度标准差: {:.4f} {}/s^2".format(
            acc_summary["acc_core_std"], kin["unit"])
        )

    # ===== 打印二次拟合结果 =====
    if quad_fit is not None:
        print("二次拟合加速度 a_fit: {:.4f} mm/s^2".format(quad_fit["a_fit"]))
        print("二次拟合残差 RMS: {:.6f} mm".format(quad_fit["residual_rms"]))
        print("二次拟合 R^2: {:.6f}".format(quad_fit["r2"]))

    if quad_summary is not None:
        print("稳健 a_fit 均值: {:.4f} mm/s^2".format(quad_summary["a_fit_mean"]))
        print("稳健 a_fit 标准差: {:.4f} mm/s^2".format(quad_summary["a_fit_std"]))
        print("稳健 a_fit 中位数: {:.4f} mm/s^2".format(quad_summary["a_fit_median"]))
        print("稳健 a_fit 范围: {:.4f} ~ {:.4f} mm/s^2".format(
            quad_summary["a_fit_min"], quad_summary["a_fit_max"]))

    # ===== 打印加速度频谱结果 =====
    if acc_fft_result is not None:
        print("加速度主频: {:.4f} Hz".format(acc_fft_result["freq"]))

    # ===== 打印低通后二次拟合结果 =====
    if quad_fit_low is not None:
        print("低通后二次拟合加速度 a_fit_lowpass: {:.4f} mm/s^2".format(quad_fit_low["a_fit"]))
        print("低通后二次拟合残差 RMS: {:.6f} mm".format(quad_fit_low["residual_rms"]))
        print("低通后二次拟合 R^2: {:.6f}".format(quad_fit_low["r2"]))

    # ===== 打印二次+振动同步拟合结果 =====
    if quad_osc_fit is not None:
        print("二次+振动同步拟合加速度 a_fit_osc: {:.4f} mm/s^2".format(quad_osc_fit["a_fit"]))
        print("同步拟合频率 f_fit: {:.4f} Hz".format(quad_osc_fit["freq_hz"]))
        print("同步拟合振幅 amp: {:.6f} mm".format(quad_osc_fit["amp"]))
        print("同步拟合残差 RMS: {:.6f} mm".format(quad_osc_fit["residual_rms"]))
        print("同步拟合 R^2: {:.6f}".format(quad_osc_fit["r2"]))

    # ===== 打印固定主频 + 二次谐波拟合结果 =====
    if quad_harm_fit is not None:
        print("固定主频+二次谐波拟合加速度 a_fit_harm: {:.4f} mm/s^2".format(quad_harm_fit["a_fit"]))
        print("主频 f0: {:.4f} Hz".format(quad_harm_fit["base_freq_hz"]))
        print("二次谐波 2f0: {:.4f} Hz".format(quad_harm_fit["harmonic_freq_hz"]))
        print("主频振幅 amp1: {:.6f} mm".format(quad_harm_fit["amp1"]))
        print("二次谐波振幅 amp2: {:.6f} mm".format(quad_harm_fit["amp2"]))
        print("固定主频+二次谐波拟合残差 RMS: {:.6f} mm".format(quad_harm_fit["residual_rms"]))
        print("固定主频+二次谐波拟合 R^2: {:.6f}".format(quad_harm_fit["r2"]))

    # ===== 打印几何主频 =====
    for name in ["L", "W", "A"]:
        if geom_result.get(name) is not None and geom_result[name]["fft"] is not None:
            print("{} 主频: {:.4f} Hz".format(name, geom_result[name]["fft"]["freq"]))

    print("=" * 60)
    print("输出目录: {}".format(OUTPUT_DIR.resolve()))
    print("完成。")


if __name__ == "__main__":
    main()
