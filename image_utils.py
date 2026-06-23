import cv2
import numpy as np


def crop_roi(frame, roi):
    x, y, w, h = roi
    return frame[y:y + h, x:x + w]


def draw_roi_on_frame(frame, roi):
    x, y, w, h = roi
    if frame.ndim == 2:
        disp = cv2.cvtColor(normalize_to_uint8(frame), cv2.COLOR_GRAY2BGR)
    else:
        disp = frame.copy()
    cv2.rectangle(disp, (x, y), (x + w, y + h), (0, 0, 255), 3)
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


def estimate_background(stack_roi, sample_count):
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


def build_foreground_mask(frame_roi, background_roi, preprocess_cfg):
    """
    背景差分 + 阈值 + 形态学，得到前景 mask。
    """
    threshold_mode = preprocess_cfg["threshold_mode"]
    manual_threshold = preprocess_cfg["manual_threshold"]
    morph_kernel_size = preprocess_cfg["morph_kernel_size"]

    frame_u8 = normalize_to_uint8(frame_roi)
    bg_u8 = normalize_to_uint8(background_roi)

    diff = cv2.absdiff(frame_u8, bg_u8)

    if threshold_mode == "otsu":
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif threshold_mode == "manual":
        _, mask = cv2.threshold(diff, manual_threshold, 255, cv2.THRESH_BINARY)
    else:
        raise ValueError("threshold_mode 只能是 'otsu' 或 'manual'")

    kernel = cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (morph_kernel_size, morph_kernel_size)
    )
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    return mask
