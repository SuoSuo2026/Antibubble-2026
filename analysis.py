import numpy as np


# ============================================================
# A. 数据整理层（相对上层，但无实验默认值）
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
        "volume_px3": np.array([r.volume_px3 for r in results], dtype=float),
        "radius_volume_eq_px": np.array(
            [r.radius_volume_eq_px for r in results], dtype=float
        ),
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
# B. 下层工具函数（纯数值工具，不偷用配置）
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


def select_time_window(t, y, t_range):
    """
    截取指定时间窗内的数据，并自动去除 NaN。
    """
    t0, t1 = t_range
    mask = (t >= t0) & (t <= t1) & (~np.isnan(y))
    return t[mask], y[mask]


def detrend_signal(t, y, order):
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

    if len(f) <= 1:
        return None

    amp = np.abs(Y)
    amp[0] = 0.0

    idx = np.argmax(amp)
    return {
        "freq": float(f[idx]),
        "amp": float(amp[idx]),
        "freq_axis": f,
        "amp_spectrum": amp,
    }


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


# ============================================================
# C. 中层：基础运动学与统计
# ============================================================

def compute_kinematics(data, fps, motion_axis, smooth_window, pixel_per_mm=None):
    """
    计算位置、速度、加速度。
    """
    if motion_axis == "x":
        pos_raw = data["cx"].copy()
    elif motion_axis == "y":
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
        "unit": unit,
    }


def compute_kinematics_lowpass_core(data, fps, motion_axis, pixel_per_mm, cutoff_hz):
    """
    中层核心函数：基于位置低通滤波的运动学重建。
    """
    if motion_axis == "x":
        pos_raw = data["cx"].copy()
    elif motion_axis == "y":
        pos_raw = data["cy"].copy()
    else:
        raise ValueError("motion_axis 只能是 'x' 或 'y'")

    t = data["frame"] / fps

    valid = ~np.isnan(pos_raw)
    pos_interp = pos_raw.copy()

    if np.sum(valid) >= 2:
        pos_interp[~valid] = np.interp(t[~valid], t[valid], pos_raw[valid])

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
        "cutoff_hz": cutoff_hz,
    }


def estimate_kinematic_uncertainty(
    kin,
    pixel_per_mm,
    fps,
    centroid_sigma_px,
    fps_rel_error,
):
    """
    根据像素误差 + 平滑残差 + 帧率误差，估计速度和加速度的不确定度。
    """
    dt = 1.0 / fps

    pos_raw = kin["pos_raw"]
    pos_smooth = kin["pos_smooth"]
    vel = kin["vel"]
    acc = kin["acc"]

    sigma_x_pix = centroid_sigma_px / pixel_per_mm

    residual = pos_raw - pos_smooth
    residual = residual[~np.isnan(residual)]
    if len(residual) > 0:
        sigma_x_fit = np.sqrt(np.mean(residual ** 2))
    else:
        sigma_x_fit = 0.0

    sigma_x_tot = np.sqrt(sigma_x_pix ** 2 + sigma_x_fit ** 2)

    sigma_v_meas = sigma_x_tot / (np.sqrt(2.0) * dt)
    sigma_a_meas = np.sqrt(6.0) * sigma_x_tot / (dt ** 2)

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


# ============================================================
# D. 中层：拟合模型
# ============================================================

def fit_quadratic_motion(kin, fit_time_range):
    """
    对位置曲线 x(t) 在核心时间段内做二次拟合：
        x(t) = c0 + c1 t + c2 t^2
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


def fit_quadratic_plus_oscillation(kin, fit_time_range, freq_hz):
    """
    固定频率下拟合：
        x(t) = c0 + c1*tau + c2*tau^2 + B*cos(2*pi*f*tau) + C*sin(2*pi*f*tau)
    """
    t = kin["t"]
    x = kin["pos_smooth"]

    t_fit, x_fit = select_time_window(t, x, fit_time_range)
    if len(t_fit) < 8:
        return None

    t_ref = np.mean(t_fit)
    tau = t_fit - t_ref
    w = 2.0 * np.pi * freq_hz

    M = np.column_stack([
        np.ones_like(tau),
        tau,
        tau ** 2,
        np.cos(w * tau),
        np.sin(w * tau),
    ])

    coeffs, _, _, _ = np.linalg.lstsq(M, x_fit, rcond=None)
    c0, c1, c2, B, C = coeffs

    x_pred = M @ coeffs
    residual = x_fit - x_pred

    residual_rms = np.sqrt(np.mean(residual ** 2))
    ss_res = np.sum((x_fit - x_pred) ** 2)
    ss_tot = np.sum((x_fit - np.mean(x_fit)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    a_fit = 2.0 * c2
    amp = np.sqrt(B ** 2 + C ** 2)
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
        "t_ref": float(t_ref),
    }


def fit_quadratic_plus_harmonics(kin, fit_time_range, base_freq_hz):
    """
    固定主频 + 二次谐波联合拟合：
        x(t) = c0 + c1*tau + c2*tau^2
             + B1*cos(w*tau) + C1*sin(w*tau)
             + B2*cos(2*w*tau) + C2*sin(2*w*tau)
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
        tau ** 2,
        np.cos(w * tau),
        np.sin(w * tau),
        np.cos(2.0 * w * tau),
        np.sin(2.0 * w * tau),
    ])

    coeffs, _, _, _ = np.linalg.lstsq(M, x_fit, rcond=None)
    c0, c1, c2, B1, C1, B2, C2 = coeffs

    x_pred = M @ coeffs
    residual = x_fit - x_pred

    residual_rms = np.sqrt(np.mean(residual ** 2))
    ss_res = np.sum((x_fit - x_pred) ** 2)
    ss_tot = np.sum((x_fit - np.mean(x_fit)) ** 2)
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

    a_fit = 2.0 * c2
    amp1 = np.sqrt(B1 ** 2 + C1 ** 2)
    phase1 = np.arctan2(C1, B1)
    amp2 = np.sqrt(B2 ** 2 + C2 ** 2)
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
        "t_ref": float(t_ref),
    }


def fit_quadratic_plus_oscillation_scan(kin, fit_time_range, freq_range, n_freq):
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
            tau ** 2,
            np.cos(w * tau),
            np.sin(w * tau),
        ])

        coeffs, _, _, _ = np.linalg.lstsq(M, x_fit, rcond=None)
        x_pred = M @ coeffs
        residual = x_fit - x_pred
        rms = np.sqrt(np.mean(residual ** 2))

        if rms < best_rms:
            c0, c1, c2, B, C = coeffs
            ss_res = np.sum((x_fit - x_pred) ** 2)
            ss_tot = np.sum((x_fit - np.mean(x_fit)) ** 2)
            r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else np.nan

            best_rms = rms
            best = {
                "a_fit": float(2.0 * c2),
                "freq_hz": float(freq_hz),
                "amp": float(np.sqrt(B ** 2 + C ** 2)),
                "phase_rad": float(np.arctan2(C, B)),
                "coeffs": coeffs,
                "t_fit": t_fit,
                "tau": tau,
                "x_fit_data": x_fit,
                "x_fit_curve": x_pred,
                "residual_rms": float(rms),
                "r2": float(r2),
                "t_ref": float(t_ref),
                "scan_freqs": freqs,
            }

    return best


# ============================================================
# E. 中层：FFT / 信号分析
# ============================================================

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
        "amp_spectrum": amp,
    }


# ============================================================
# F. 上层：配置驱动的分析编排层
# ============================================================

def fit_quadratic_motion_robust(data, exp_cfg, kin_cfg, fit_cfg):
    """
    用多组平滑窗口 + 多组拟合时间窗，重复计算 a_fit，
    作为更稳健的敏感性分析。
    """
    fps = exp_cfg["fps"]
    pixel_per_mm = exp_cfg["pixel_per_mm"]
    motion_axis = exp_cfg["motion_axis"]

    smooth_windows = fit_cfg["fit_smooth_windows"]
    fit_time_windows = fit_cfg["fit_time_windows"]

    fit_results = []

    for sw in smooth_windows:
        kin_local = compute_kinematics(
            data=data,
            fps=fps,
            motion_axis=motion_axis,
            smooth_window=sw,
            pixel_per_mm=pixel_per_mm,
        )

        for t_range in fit_time_windows:
            t_range = tuple(t_range)
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


def analyze_geometry_oscillation(data, exp_cfg, osc_cfg):
    """
    对 L(t), W(t), A(t) 做去趋势与主频分析。
    """
    fps = exp_cfg["fps"]
    time_range = tuple(osc_cfg["geom_analysis_time_range"])

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
            "fft": fft_res,
        }

    return result


def analyze_acceleration_fft(kin, osc_cfg):
    """
    分析加速度信号在核心时间窗内的频谱。
    """
    time_range = tuple(osc_cfg["acc_fft_time_range"])
    return analyze_signal_fft(
        t=kin["t"],
        y=kin["acc"],
        time_range=time_range,
    )


def compute_kinematics_lowpass(data, exp_cfg, osc_cfg):
    """
    配置驱动的低通运动学分析。
    """
    return compute_kinematics_lowpass_core(
        data=data,
        fps=exp_cfg["fps"],
        motion_axis=exp_cfg["motion_axis"],
        pixel_per_mm=exp_cfg["pixel_per_mm"],
        cutoff_hz=osc_cfg["lowpass_cutoff_hz"],
    )


def run_enabled_advanced_analysis(data, kin, exp_cfg, kin_cfg, fit_cfg, osc_cfg):
    """
    一个可选的上层总入口。
    用于后续 main.py 中统一启用 / 禁用若干 analysis 功能。
    当前只做计算，不做绘图。
    """
    outputs = {}

    # 1. 基础二次拟合
    outputs["quadratic_fit"] = fit_quadratic_motion(
        kin=kin,
        fit_time_range=tuple(fit_cfg["quad_fit_time_range"]),
    )

    # 2. 稳健二次拟合
    robust_summary, robust_results = fit_quadratic_motion_robust(
        data=data,
        exp_cfg=exp_cfg,
        kin_cfg=kin_cfg,
        fit_cfg=fit_cfg,
    )
    outputs["quadratic_fit_robust_summary"] = robust_summary
    outputs["quadratic_fit_robust_results"] = robust_results

    # 3. 几何振荡分析
    outputs["geometry_oscillation"] = analyze_geometry_oscillation(
        data=data,
        exp_cfg=exp_cfg,
        osc_cfg=osc_cfg,
    )

    # 4. 加速度 FFT
    outputs["acceleration_fft"] = analyze_acceleration_fft(
        kin=kin,
        osc_cfg=osc_cfg,
    )

    # 5. 低通运动学
    outputs["kinematics_lowpass"] = compute_kinematics_lowpass(
        data=data,
        exp_cfg=exp_cfg,
        osc_cfg=osc_cfg,
    )

    # 6. 二次 + 振荡拟合
    if osc_cfg["use_quad_osc_fit"]:
        if osc_cfg["use_freq_scan"]:
            outputs["quad_osc_fit"] = fit_quadratic_plus_oscillation_scan(
                kin=kin,
                fit_time_range=tuple(fit_cfg["quad_fit_time_range"]),
                freq_range=tuple(osc_cfg["freq_scan_range"]),
                n_freq=osc_cfg["freq_scan_num"],
            )
        else:
            outputs["quad_osc_fit"] = fit_quadratic_plus_oscillation(
                kin=kin,
                fit_time_range=tuple(fit_cfg["quad_fit_time_range"]),
                freq_hz=osc_cfg["shape_freq_hz"],
            )
    else:
        outputs["quad_osc_fit"] = None

    # 7. 主频 + 二次谐波拟合
    if osc_cfg["use_quad_osc_harmonic_fit"]:
        outputs["quad_harmonic_fit"] = fit_quadratic_plus_harmonics(
            kin=kin,
            fit_time_range=tuple(fit_cfg["quad_fit_time_range"]),
            base_freq_hz=osc_cfg["shape_freq_hz"],
        )
    else:
        outputs["quad_harmonic_fit"] = None

    return outputs
