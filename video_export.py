from pathlib import Path
import cv2
import numpy as np

from image_utils import crop_roi, normalize_to_uint8


# ============================================================
# A. 下层：基础工具
# ============================================================

def ensure_output_dir(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def _to_bgr(frame):
    if frame.ndim == 2:
        frame_u8 = normalize_to_uint8(frame)
        return cv2.cvtColor(frame_u8, cv2.COLOR_GRAY2BGR)
    if frame.ndim == 3 and frame.shape[2] == 3:
        return frame.copy()
    raise ValueError(f"不支持的图像 shape: {frame.shape}")


def _get_export_indices(n_frames, frame_range_mode, valid_frame_range):
    if frame_range_mode == "all":
        return np.arange(n_frames, dtype=int)

    if frame_range_mode == "valid":
        f0, f1 = valid_frame_range
        f0 = max(0, int(f0))
        f1 = min(n_frames - 1, int(f1))
        if f1 < f0:
            return np.array([], dtype=int)
        return np.arange(f0, f1 + 1, dtype=int)

    raise ValueError("video_export.frame_range_mode 只能是 'all' 或 'valid'")


def _convert_result_to_local_coords(result, roi, crop_to_roi):
    if not result.found:
        return None

    x0, y0, _, _ = roi

    if crop_to_roi:
        return {
            "cx": int(round(result.cx - x0)),
            "cy": int(round(result.cy - y0)),
            "x_left": int(round(result.x_left - x0)),
            "x_right": int(round(result.x_right - x0)),
            "y_top": int(round(result.y_top - y0)),
            "y_bottom": int(round(result.y_bottom - y0)),
        }

    return {
        "cx": int(round(result.cx)),
        "cy": int(round(result.cy)),
        "x_left": int(round(result.x_left)),
        "x_right": int(round(result.x_right)),
        "y_top": int(round(result.y_top)),
        "y_bottom": int(round(result.y_bottom)),
    }


# ============================================================
# B. 中层：单帧叠加绘制
# ============================================================

def draw_time_text(frame_bgr, frame_idx, fps, video_cfg):
    if not video_cfg["show_time_text"]:
        return

    unit = video_cfg["time_text_unit"]
    x = int(video_cfg["time_text_x"])
    y = int(video_cfg["time_text_y"])

    t = frame_idx / fps
    if unit == "ms":
        text = f"t = {1000.0 * t:.2f} ms"
    elif unit == "s":
        text = f"t = {t:.4f} s"
    else:
        raise ValueError("video_export.time_text_unit 只能是 'ms' 或 's'")

    cv2.putText(
        frame_bgr,
        text,
        (x, y),
        cv2.FONT_HERSHEY_SIMPLEX,
        float(video_cfg["font_scale"]),
        (255, 255, 255),
        int(video_cfg["font_thickness"]),
        cv2.LINE_AA,
    )


def draw_scale_bar(frame_bgr, mm_per_pixel, video_cfg):
    if not video_cfg["show_scale_bar"]:
        return

    if mm_per_pixel is None or mm_per_pixel <= 0:
        return

    bar_mm = float(video_cfg["scale_bar_mm"])
    bar_px = int(round(bar_mm / mm_per_pixel))

    x = int(video_cfg["scale_bar_x"])
    y = int(video_cfg["scale_bar_y"])
    thickness = int(video_cfg["scale_bar_thickness"])
    text_gap = int(video_cfg["scale_bar_text_gap"])

    cv2.line(
        frame_bgr,
        (x, y),
        (x + bar_px, y),
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )

    cv2.putText(
        frame_bgr,
        f"{bar_mm:g} mm",
        (x, y - text_gap),
        cv2.FONT_HERSHEY_SIMPLEX,
        float(video_cfg["font_scale"]),
        (255, 255, 255),
        int(video_cfg["font_thickness"]),
        cv2.LINE_AA,
    )


def draw_target_overlay(frame_bgr, result_local, trajectory_local, video_cfg):
    if result_local is not None:
        if video_cfg["show_bbox"]:
            cv2.rectangle(
                frame_bgr,
                (result_local["x_left"], result_local["y_top"]),
                (result_local["x_right"], result_local["y_bottom"]),
                (255, 0, 0),
                2,
            )

        if video_cfg["show_centroid"]:
            cv2.circle(
                frame_bgr,
                (result_local["cx"], result_local["cy"]),
                int(video_cfg["centroid_radius"]),
                (0, 255, 0),
                -1,
            )

    if video_cfg["show_trajectory"] and len(trajectory_local) >= 2:
        for i in range(1, len(trajectory_local)):
            cv2.line(
                frame_bgr,
                trajectory_local[i - 1],
                trajectory_local[i],
                (0, 255, 255),
                2,
                cv2.LINE_AA,
            )


# ============================================================
# C. 上层：配置驱动视频导出
# ============================================================

def export_presentation_video(
    stack,
    roi,
    results,
    exp_cfg,
    video_cfg,
    output_dir,
):
    if not video_cfg.get("enabled", False):
        return None

    output_dir = ensure_output_dir(output_dir)

    fps = float(exp_cfg["fps"])
    mm_per_pixel = exp_cfg.get("mm_per_pixel", None)
    valid_frame_range = tuple(exp_cfg["valid_frame_range"])

    frame_range_mode = video_cfg["frame_range_mode"]
    crop_to_roi = bool(video_cfg["crop_to_roi"])

    export_indices = _get_export_indices(
        n_frames=stack.shape[0],
        frame_range_mode=frame_range_mode,
        valid_frame_range=valid_frame_range,
    )

    if len(export_indices) == 0:
        print("警告：video_export 没有可导出的帧。")
        return None

    first_idx = int(export_indices[0])
    first_frame = crop_roi(stack[first_idx], roi) if crop_to_roi else stack[first_idx]
    first_bgr = _to_bgr(first_frame)
    h, w = first_bgr.shape[:2]

    out_path = Path(output_dir) / video_cfg["filename"]
    fourcc = cv2.VideoWriter_fourcc(*video_cfg["codec"])
    writer = cv2.VideoWriter(
        str(out_path),
        fourcc,
        float(video_cfg["fps_out"]),
        (w, h),
    )

    if not writer.isOpened():
        raise RuntimeError(f"无法创建视频文件: {out_path}")

    trajectory_local = []
    max_traj = int(video_cfg["trajectory_length"])

    for idx in export_indices:
        frame = crop_roi(stack[idx], roi) if crop_to_roi else stack[idx]
        frame_bgr = _to_bgr(frame)

        result_local = _convert_result_to_local_coords(
            results[idx], roi, crop_to_roi
        )

        if result_local is not None:
            trajectory_local.append((result_local["cx"], result_local["cy"]))
            if len(trajectory_local) > max_traj:
                trajectory_local.pop(0)

        draw_target_overlay(frame_bgr, result_local, trajectory_local, video_cfg)
        draw_time_text(frame_bgr, idx, fps, video_cfg)
        draw_scale_bar(frame_bgr, mm_per_pixel, video_cfg)

        writer.write(frame_bgr)

    writer.release()
    print(f"展示型视频已保存到: {out_path}")

    return out_path
