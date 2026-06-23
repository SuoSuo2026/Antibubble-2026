from pathlib import Path
import numpy as np
import cv2
import matplotlib.pyplot as plt

from image_utils import crop_roi, draw_roi_on_frame, normalize_to_uint8


# ============================================================
# A. 下层：基础工具
# ============================================================

def ensure_output_dir(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def save_figure(fig, output_path, dpi):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


# ============================================================
# B. 中层：tracking / preview 可视化
# ============================================================

def save_frame0_with_roi(stack, roi, output_dir, dpi):
    fig = plt.figure(figsize=(14, 6))
    full0 = draw_roi_on_frame(stack[0], roi)
    plt.imshow(cv2.cvtColor(full0, cv2.COLOR_BGR2RGB))
    plt.title("Frame 0 with ROI")
    plt.axis("off")
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "frame0_with_roi.png", dpi)


def save_background_roi(background_roi, output_dir, dpi):
    fig = plt.figure(figsize=(12, 3))
    plt.imshow(normalize_to_uint8(background_roi), cmap="gray")
    plt.title("Estimated background in ROI")
    plt.axis("off")
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "background_roi.png", dpi)


def save_tracking_preview(overlays, output_dir, dpi, sample_count):
    n = len(overlays)
    idx_list = np.linspace(0, n - 1, min(sample_count, n), dtype=int)

    fig = plt.figure(figsize=(15, 8))
    rows = int(np.ceil(len(idx_list) / 3))
    cols = min(3, len(idx_list))

    for j, idx in enumerate(idx_list, start=1):
        plt.subplot(rows, cols, j)
        plt.imshow(cv2.cvtColor(overlays[idx], cv2.COLOR_BGR2RGB))
        plt.title(f"Tracked ROI - frame {idx}")
        plt.axis("off")

    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "tracking_preview.png", dpi)


def save_valid_window_tracking_preview(stack, results, roi, fps, frame_range, output_dir, dpi, sample_count):
    f0, f1 = frame_range
    valid_indices = np.arange(max(0, f0), min(len(results), f1 + 1))

    if len(valid_indices) == 0:
        return

    show_indices = np.linspace(valid_indices[0], valid_indices[-1], min(sample_count, len(valid_indices)), dtype=int)

    fig = plt.figure(figsize=(15, 8))
    rows = int(np.ceil(len(show_indices) / 3))
    cols = min(3, len(show_indices))

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

        plt.subplot(rows, cols, j)
        plt.imshow(cv2.cvtColor(disp, cv2.COLOR_BGR2RGB))
        plt.title(f"Valid-window frame {idx}\nt={idx / fps:.4f}s")
        plt.axis("off")

    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "valid_window_tracking_preview.png", dpi)


# ============================================================
# C. 中层：基础曲线图
# ============================================================

def plot_target_area(data, fps, output_dir, dpi):
    t = data["frame"] / fps
    area = data["area"]

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, area, "o-", ms=3, lw=1.5)
    plt.xlabel("Time (s)")
    plt.ylabel("Target area [pixels]")
    plt.title("Main target area")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "target_area.png", dpi)


def plot_volume_equivalent_radius(data, exp_cfg, output_dir, dpi):
    t = data["frame"] / exp_cfg["fps"]
    radius = data["radius_volume_eq_px"].copy()

    pixel_per_mm = exp_cfg.get("pixel_per_mm", None)
    if pixel_per_mm is not None and pixel_per_mm > 0:
        radius = radius / pixel_per_mm
        unit = "mm"
    else:
        unit = "pixel"

    valid = ~np.isnan(radius)
    mean_r = np.nanmean(radius) if np.any(valid) else np.nan
    rel_std = (
        100.0 * np.nanstd(radius) / mean_r
        if np.any(valid) and mean_r > 0
        else np.nan
    )

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, radius, "o-", ms=3, lw=1.5, label="volume-equivalent radius")
    if np.isfinite(mean_r):
        plt.axhline(mean_r, linestyle="--", lw=1.5, label=f"mean = {mean_r:.4f} {unit}")
    plt.xlabel("Time (s)")
    plt.ylabel(f"R [{unit}]")
    plt.title(f"Volume-equivalent droplet radius (relative std = {rel_std:.2f}%)")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "radius_volume_equivalent.png", dpi)


def plot_kinematics(kin, motion_axis, output_dir, dpi):
    t = kin["t"]
    unit = kin["unit"]

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, kin["pos_raw"], "o-", ms=3, label="raw position")
    plt.plot(t, kin["pos_smooth"], "-", lw=2, label="smoothed position")
    plt.xlabel("Time (s)")
    plt.ylabel(f"{motion_axis}(centroid) [{unit}]")
    plt.title("Position")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "position.png", dpi)

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, kin["vel"], "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Velocity [{unit}/s]")
    plt.title("Velocity")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "velocity.png", dpi)

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, kin["acc"], "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Acceleration")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "acceleration.png", dpi)


def plot_geometry_curves(data, fps, output_dir, dpi):
    t = data["frame"] / fps
    length = data["y_bottom"] - data["y_top"]
    width = data["x_right"] - data["x_left"]

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, length, label="length = y_bottom - y_top")
    plt.plot(t, width, label="width = x_right - x_left")
    plt.xlabel("Time (s)")
    plt.ylabel("Pixels")
    plt.title("Basic geometry")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "geometry.png", dpi)


def plot_core_kinematics_zoom(kin, core_time_range, output_dir, dpi):
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

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t_core, vel_core, "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Velocity [{unit}/s]")
    plt.title("Velocity (core window zoom)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "velocity_core_zoom.png", dpi)

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t_core, acc_core, "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Acceleration (core window zoom)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "acceleration_core_zoom.png", dpi)


def plot_core_acceleration_robust(kin, core_time_range, output_dir, dpi):
    t = kin["t"]
    acc = kin["acc"]
    unit = kin["unit"]

    t0, t1 = core_time_range
    mask = (t >= t0) & (t <= t1)
    if np.sum(mask) < 5:
        return

    t_core = t[mask]
    acc_core = acc[mask]

    q_low, q_high = np.percentile(acc_core, [2, 98])
    pad = 0.1 * max(1e-12, q_high - q_low)

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t_core, acc_core, "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Acceleration (core window, robust y-limit)")
    plt.ylim(q_low - pad, q_high + pad)
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "acceleration_core_robust.png", dpi)


# ============================================================
# D. 中层：拟合相关图
# ============================================================

def plot_quadratic_fit(kin, fit_result, output_dir, dpi):
    if fit_result is None:
        return

    fig = plt.figure(figsize=(10, 4))
    plt.plot(kin["t"], kin["pos_smooth"], "-", lw=1.5, label="smoothed position")
    plt.plot(fit_result["t_fit"], fit_result["x_fit_curve"], "--", lw=2, label="quadratic fit")
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic fit of centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "quadratic_fit_position.png", dpi)


def plot_quadratic_fit_robust_summary(fit_results, summary, output_dir, dpi):
    if summary is None or len(fit_results) == 0:
        return

    a_values = np.array([r["a_fit"] for r in fit_results], dtype=float)
    idx = np.arange(len(a_values))

    fig = plt.figure(figsize=(10, 4))
    plt.plot(idx, a_values, "o-", label="a_fit from each setting")
    plt.axhline(summary["a_fit_mean"], linestyle="--", label="mean")
    plt.axhline(summary["a_fit_median"], linestyle=":", label="median")
    plt.fill_between(
        idx,
        summary["a_fit_mean"] - summary["a_fit_std"],
        summary["a_fit_mean"] + summary["a_fit_std"],
        alpha=0.2,
        label="mean ± std",
    )
    plt.xlabel("Fit case index")
    plt.ylabel("a_fit [mm/s$^2$]")
    plt.title("Robustness of quadratic-fit acceleration")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "quadratic_fit_robust_summary.png", dpi)


def plot_quadratic_plus_oscillation_fit(kin, fit_result, output_dir, dpi):
    if fit_result is None:
        return

    fig = plt.figure(figsize=(10, 4))
    plt.plot(kin["t"], kin["pos_smooth"], "-", lw=1.5, label="smoothed position")
    plt.plot(fit_result["t_fit"], fit_result["x_fit_curve"], "--", lw=2, label="quadratic + oscillation fit")
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic + oscillation fit of centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "quadratic_plus_oscillation_fit.png", dpi)


def plot_quadratic_plus_harmonics_fit(kin, fit_result, output_dir, dpi):
    if fit_result is None:
        return

    fig = plt.figure(figsize=(10, 4))
    plt.plot(kin["t"], kin["pos_smooth"], "-", lw=1.5, label="smoothed position")
    plt.plot(
        fit_result["t_fit"],
        fit_result["x_fit_curve"],
        "--",
        lw=2,
        label="quadratic + fundamental + 2nd harmonic",
    )
    plt.xlabel("Time (s)")
    plt.ylabel("Position [mm]")
    plt.title("Quadratic + harmonic-constrained fit of centroid motion")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "quadratic_plus_harmonics_fit.png", dpi)


def plot_oscillation_component(fit_result, output_dir, dpi):
    if fit_result is None:
        return

    coeffs = fit_result["coeffs"]
    tau = fit_result["tau"]
    x_data = fit_result["x_fit_data"]
    x_pred = fit_result["x_fit_curve"]

    c0, c1, c2, B, C = coeffs
    osc_part = B * np.cos(2 * np.pi * fit_result["freq_hz"] * tau) + C * np.sin(
        2 * np.pi * fit_result["freq_hz"] * tau
    )
    residual = x_data - x_pred

    fig = plt.figure(figsize=(10, 6))

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
    save_figure(fig, Path(output_dir) / "oscillation_component_and_residual.png", dpi)


def plot_harmonic_components_and_residual(fit_result, output_dir, dpi):
    if fit_result is None:
        return

    coeffs = fit_result["coeffs"]
    tau = fit_result["tau"]
    t_fit = fit_result["t_fit"]
    residual = fit_result["residual"]

    c0, c1, c2, B1, C1, B2, C2 = coeffs
    f0 = fit_result["base_freq_hz"]
    w = 2.0 * np.pi * f0

    osc1 = B1 * np.cos(w * tau) + C1 * np.sin(w * tau)
    osc2 = B2 * np.cos(2.0 * w * tau) + C2 * np.sin(2.0 * w * tau)

    fig = plt.figure(figsize=(10, 8))

    plt.subplot(3, 1, 1)
    plt.plot(t_fit, osc1, lw=2, label="fundamental component")
    plt.xlabel("Time (s)")
    plt.ylabel("Fundamental [mm]")
    plt.title(f"Fundamental component ({f0:.3f} Hz)")
    plt.grid(alpha=0.3)
    plt.legend()

    plt.subplot(3, 1, 2)
    plt.plot(t_fit, osc2, lw=2, label="2nd harmonic component")
    plt.xlabel("Time (s)")
    plt.ylabel("2nd harmonic [mm]")
    plt.title(f"Second harmonic component ({2.0 * f0:.3f} Hz)")
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
    save_figure(fig, Path(output_dir) / "harmonic_components_and_residual.png", dpi)


# ============================================================
# E. 中层：FFT / oscillation 图
# ============================================================

def plot_geometry_detrended(geom_result, output_dir, dpi):
    if geom_result is None:
        return

    fig = plt.figure(figsize=(12, 8))
    plot_id = 1

    for name in ["L", "W", "A"]:
        if geom_result.get(name) is None:
            continue

        res = geom_result[name]

        plt.subplot(3, 2, plot_id)
        plt.plot(res["t"], res["raw"], label=f"{name} raw")
        plt.plot(res["t"], res["trend"], label=f"{name} trend")
        plt.xlabel("Time (s)")
        plt.ylabel(name)
        plt.title(f"{name}: raw + trend")
        plt.grid(alpha=0.3)
        plt.legend()
        plot_id += 1

        plt.subplot(3, 2, plot_id)
        plt.plot(res["t"], res["detrended"], label=f"{name} detrended")
        plt.xlabel("Time (s)")
        plt.ylabel(name)
        plt.title(f"{name}: detrended")
        plt.grid(alpha=0.3)
        plt.legend()
        plot_id += 1

    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "geometry_detrended.png", dpi)


def plot_geometry_fft(geom_result, output_dir, dpi):
    if geom_result is None:
        return

    fig = plt.figure(figsize=(12, 8))
    plot_id = 1

    for name in ["L", "W", "A"]:
        if geom_result.get(name) is None or geom_result[name]["fft"] is None:
            continue

        fft_res = geom_result[name]["fft"]
        plt.subplot(3, 1, plot_id)
        plt.plot(fft_res["freq_axis"], fft_res["amp_spectrum"])
        plt.xlabel("Frequency (Hz)")
        plt.ylabel("Amplitude")
        plt.title(f"{name} FFT (dominant = {fft_res['freq']:.2f} Hz)")
        plt.grid(alpha=0.3)
        plot_id += 1

    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "geometry_fft.png", dpi)


def plot_acceleration_fft(acc_fft_result, output_dir, dpi):
    if acc_fft_result is None:
        return

    fig = plt.figure(figsize=(10, 4))
    plt.plot(acc_fft_result["freq_axis"], acc_fft_result["amp_spectrum"])
    plt.xlabel("Frequency (Hz)")
    plt.ylabel("Acceleration amplitude")
    plt.title(f"Acceleration FFT (dominant frequency = {acc_fft_result['freq']:.2f} Hz)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "acceleration_fft.png", dpi)


def plot_lowpass_kinematics(kin_lowpass, output_dir, dpi):
    if kin_lowpass is None:
        return

    t = kin_lowpass["t"]
    unit = kin_lowpass["unit"]

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, kin_lowpass["pos_raw"], "o-", ms=3, label="raw position")
    plt.plot(t, kin_lowpass["pos_lowpass"], "-", lw=2, label="lowpass position")
    plt.xlabel("Time (s)")
    plt.ylabel(f"Position [{unit}]")
    plt.title(f"Lowpass position (cutoff = {kin_lowpass['cutoff_hz']:.2f} Hz)")
    plt.grid(alpha=0.3)
    plt.legend()
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "position_lowpass.png", dpi)

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, kin_lowpass["vel_lowpass"], "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Velocity [{unit}/s]")
    plt.title("Lowpass velocity")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "velocity_lowpass.png", dpi)

    fig = plt.figure(figsize=(10, 4))
    plt.plot(t, kin_lowpass["acc_lowpass"], "-", lw=2)
    plt.xlabel("Time (s)")
    plt.ylabel(f"Acceleration [{unit}/s$^2$]")
    plt.title("Lowpass acceleration")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_figure(fig, Path(output_dir) / "acceleration_lowpass.png", dpi)


# ============================================================
# F. 上层：配置驱动导出
# ============================================================

def export_tracking_visualizations(
    stack,
    roi,
    results,
    background_roi,
    overlays,
    exp_cfg,
    vis_cfg,
    output_dir,
):
    output_dir = ensure_output_dir(output_dir)
    dpi = vis_cfg["dpi"]
    sample_count = vis_cfg["preview_sample_count"]

    save_frame0_with_roi(stack, roi, output_dir, dpi)
    save_background_roi(background_roi, output_dir, dpi)
    save_tracking_preview(overlays, output_dir, dpi, sample_count)
    save_valid_window_tracking_preview(
        stack=stack,
        results=results,
        roi=roi,
        fps=exp_cfg["fps"],
        frame_range=tuple(exp_cfg["valid_frame_range"]),
        output_dir=output_dir,
        dpi=dpi,
        sample_count=sample_count,
    )


def export_basic_analysis_visualizations(
    valid_data,
    kin,
    exp_cfg,
    kin_cfg,
    output_dir,
    vis_cfg,
):
    output_dir = ensure_output_dir(output_dir)
    dpi = vis_cfg["dpi"]

    plot_target_area(valid_data, exp_cfg["fps"], output_dir, dpi)
    plot_volume_equivalent_radius(valid_data, exp_cfg, output_dir, dpi)
    plot_kinematics(kin, exp_cfg["motion_axis"], output_dir, dpi)
    plot_geometry_curves(valid_data, exp_cfg["fps"], output_dir, dpi)
    plot_core_kinematics_zoom(
        kin=kin,
        core_time_range=tuple(kin_cfg["core_time_range"]),
        output_dir=output_dir,
        dpi=dpi,
    )
    plot_core_acceleration_robust(
        kin=kin,
        core_time_range=tuple(kin_cfg["core_time_range"]),
        output_dir=output_dir,
        dpi=dpi,
    )


def export_advanced_analysis_visualizations(
    kin,
    advanced_outputs,
    output_dir,
    vis_cfg,
):
    output_dir = ensure_output_dir(output_dir)
    dpi = vis_cfg["dpi"]

    plot_quadratic_fit(
        kin=kin,
        fit_result=advanced_outputs.get("quadratic_fit"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_quadratic_fit_robust_summary(
        fit_results=advanced_outputs.get("quadratic_fit_robust_results", []),
        summary=advanced_outputs.get("quadratic_fit_robust_summary"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_quadratic_plus_oscillation_fit(
        kin=kin,
        fit_result=advanced_outputs.get("quad_osc_fit"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_quadratic_plus_harmonics_fit(
        kin=kin,
        fit_result=advanced_outputs.get("quad_harmonic_fit"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_oscillation_component(
        fit_result=advanced_outputs.get("quad_osc_fit"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_harmonic_components_and_residual(
        fit_result=advanced_outputs.get("quad_harmonic_fit"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_geometry_detrended(
        geom_result=advanced_outputs.get("geometry_oscillation"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_geometry_fft(
        geom_result=advanced_outputs.get("geometry_oscillation"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_acceleration_fft(
        acc_fft_result=advanced_outputs.get("acceleration_fft"),
        output_dir=output_dir,
        dpi=dpi,
    )

    plot_lowpass_kinematics(
        kin_lowpass=advanced_outputs.get("kinematics_lowpass"),
        output_dir=output_dir,
        dpi=dpi,
    )


def export_all_visualizations(
    stack,
    roi,
    results,
    background_roi,
    overlays,
    valid_data,
    kin,
    advanced_outputs,
    config,
):
    data_cfg = config["data"]
    exp_cfg = config["experiment"]
    kin_cfg = config["kinematics"]
    vis_cfg = config["visualization"]

    output_dir = Path(data_cfg["output_dir"])

    export_tracking_visualizations(
        stack=stack,
        roi=roi,
        results=results,
        background_roi=background_roi,
        overlays=overlays,
        exp_cfg=exp_cfg,
        vis_cfg=vis_cfg,
        output_dir=output_dir,
    )

    export_basic_analysis_visualizations(
        valid_data=valid_data,
        kin=kin,
        exp_cfg=exp_cfg,
        kin_cfg=kin_cfg,
        output_dir=output_dir,
        vis_cfg=vis_cfg,
    )

    export_advanced_analysis_visualizations(
        kin=kin,
        advanced_outputs=advanced_outputs,
        output_dir=output_dir,
        vis_cfg=vis_cfg,
    )
