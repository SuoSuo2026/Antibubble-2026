from pathlib import Path
import numpy as np

from config_loader import load_config, get_roi_tuple
from io_utils import read_tiff_stack
from tracking import track_target_over_stack
from analysis import (
    results_to_dict,
    apply_valid_frame_window,
    compute_kinematics,
    run_enabled_advanced_analysis,
)
from visualization import (
    export_all_visualizations,
    export_tracking_visualizations,
)
from video_export import export_presentation_video


# ============================================================
# A. 摘要输出函数
# ============================================================

def print_tracking_summary(stack, results, valid_frame_range):
    total_frames = stack.shape[0]
    tracked_results = len(results)
    found_count = sum(r.found for r in results)

    valid_start, valid_end = valid_frame_range
    valid_results = results[valid_start:valid_end + 1]
    valid_found_count = sum(r.found for r in valid_results)

    print("=== Tracking summary ===")
    print(f"Total frames: {total_frames}")
    print(f"Tracked results: {tracked_results}")
    print(f"Found frames: {found_count}")
    print(f"Found ratio: {found_count / tracked_results:.3f}")
    print(f"Valid frame range: [{valid_start}, {valid_end}]")
    print(f"Found in valid range: {valid_found_count}/{len(valid_results)}")
    print(f"Valid-range found ratio: {valid_found_count / len(valid_results):.3f}")


def print_kinematics_summary(kin):
    pos_raw = kin["pos_raw"]
    pos_smooth = kin["pos_smooth"]
    vel = kin["vel"]
    acc = kin["acc"]
    t = kin["t"]

    print("\n=== Kinematics summary ===")
    print(f"Time points: {len(t)}")
    print(f"Time range: [{t[0]:.6f}, {t[-1]:.6f}] s")
    print(f"Unit: {kin['unit']}")

    print(f"NaN in pos_raw: {np.isnan(pos_raw).sum()}")
    print(f"NaN in pos_smooth: {np.isnan(pos_smooth).sum()}")
    print(f"NaN in vel: {np.isnan(vel).sum()}")
    print(f"NaN in acc: {np.isnan(acc).sum()}")

    if np.all(np.isnan(pos_smooth)):
        print("Warning: pos_smooth 全为 NaN，说明运动学链路存在问题。")
    else:
        print(
            f"Position range: "
            f"[{np.nanmin(pos_smooth):.6f}, {np.nanmax(pos_smooth):.6f}] {kin['unit']}"
        )
        print(
            f"Velocity range: "
            f"[{np.nanmin(vel):.6f}, {np.nanmax(vel):.6f}] {kin['unit']}/s"
        )
        print(
            f"Acceleration range: "
            f"[{np.nanmin(acc):.6f}, {np.nanmax(acc):.6f}] {kin['unit']}/s^2"
        )


def print_advanced_analysis_summary(outputs):
    print("\n=== Advanced analysis summary ===")

    quad_fit = outputs.get("quadratic_fit")
    if quad_fit is None:
        print("\n[Quadratic fit] failed.")
    else:
        print("\n[Quadratic fit]")
        print(f"a_fit = {quad_fit['a_fit']:.6f}")
        print(f"residual_rms = {quad_fit['residual_rms']:.6f}")
        print(f"r2 = {quad_fit['r2']:.6f}")

    robust_summary = outputs.get("quadratic_fit_robust_summary")
    if robust_summary is None:
        print("\n[Robust quadratic fit] failed.")
    else:
        print("\n[Robust quadratic fit]")
        print(f"a_fit_mean = {robust_summary['a_fit_mean']:.6f}")
        print(f"a_fit_std = {robust_summary['a_fit_std']:.6f}")
        print(f"a_fit_median = {robust_summary['a_fit_median']:.6f}")
        print(f"a_fit_min = {robust_summary['a_fit_min']:.6f}")
        print(f"a_fit_max = {robust_summary['a_fit_max']:.6f}")
        print(f"n_fits = {robust_summary['n_fits']}")

    acc_fft = outputs.get("acceleration_fft")
    if acc_fft is None:
        print("\n[Acceleration FFT] unavailable.")
    else:
        print("\n[Acceleration FFT]")
        print(f"dominant_freq = {acc_fft['freq']:.6f} Hz")
        print(f"dominant_amp = {acc_fft['amp']:.6f}")

    geom_osc = outputs.get("geometry_oscillation")
    if geom_osc is None:
        print("\n[Geometry oscillation] unavailable.")
    else:
        print("\n[Geometry oscillation]")
        for key in ["L", "W", "A"]:
            item = geom_osc.get(key)
            if item is None or item["fft"] is None:
                print(f"{key}: unavailable")
            else:
                print(
                    f"{key}: dominant_freq = {item['fft']['freq']:.6f} Hz, "
                    f"amp = {item['fft']['amp']:.6f}"
                )

    quad_osc_fit = outputs.get("quad_osc_fit")
    if quad_osc_fit is None:
        print("\n[Quadratic + oscillation fit] disabled or unavailable.")
    else:
        print("\n[Quadratic + oscillation fit]")
        print(f"a_fit = {quad_osc_fit['a_fit']:.6f}")
        print(f"freq_hz = {quad_osc_fit['freq_hz']:.6f}")
        print(f"amp = {quad_osc_fit['amp']:.6f}")
        print(f"residual_rms = {quad_osc_fit['residual_rms']:.6f}")
        print(f"r2 = {quad_osc_fit['r2']:.6f}")

    quad_harmonic_fit = outputs.get("quad_harmonic_fit")
    if quad_harmonic_fit is None:
        print("\n[Quadratic + harmonic fit] disabled or unavailable.")
    else:
        print("\n[Quadratic + harmonic fit]")
        print(f"a_fit = {quad_harmonic_fit['a_fit']:.6f}")
        print(f"base_freq_hz = {quad_harmonic_fit['base_freq_hz']:.6f}")
        print(f"amp1 = {quad_harmonic_fit['amp1']:.6f}")
        print(f"amp2 = {quad_harmonic_fit['amp2']:.6f}")
        print(f"residual_rms = {quad_harmonic_fit['residual_rms']:.6f}")
        print(f"r2 = {quad_harmonic_fit['r2']:.6f}")


# ============================================================
# B. 主流程子阶段
# ============================================================

def load_project_context():
    config = load_config()

    data_cfg = config["data"]
    exp_cfg = config["experiment"]
    kin_cfg = config["kinematics"]
    fit_cfg = config["fit"]
    osc_cfg = config["oscillation"]
    vis_cfg = config["visualization"]
    video_cfg = config.get("video_export", {"enabled": False})

    tiff_path = Path(data_cfg["tiff_path"])
    output_dir = Path(data_cfg["output_dir"])
    roi = get_roi_tuple(config)

    output_dir.mkdir(parents=True, exist_ok=True)

    return {
        "config": config,
        "data_cfg": data_cfg,
        "exp_cfg": exp_cfg,
        "kin_cfg": kin_cfg,
        "fit_cfg": fit_cfg,
        "osc_cfg": osc_cfg,
        "vis_cfg": vis_cfg,
        "video_cfg": video_cfg,
        "tiff_path": tiff_path,
        "output_dir": output_dir,
        "roi": roi,
    }


def run_tracking_pipeline(context):
    stack = read_tiff_stack(context["tiff_path"])

    results, background_roi, overlays = track_target_over_stack(
        stack=stack,
        roi=context["roi"],
        config=context["config"],
    )

    return {
        "stack": stack,
        "results": results,
        "background_roi": background_roi,
        "overlays": overlays,
    }


def run_tracking_preview_pipeline(context, tracking_outputs):
    export_tracking_visualizations(
        stack=tracking_outputs["stack"],
        roi=context["roi"],
        results=tracking_outputs["results"],
        background_roi=tracking_outputs["background_roi"],
        overlays=tracking_outputs["overlays"],
        exp_cfg=context["exp_cfg"],
        vis_cfg=context["vis_cfg"],
        output_dir=context["output_dir"],
    )


def run_analysis_pipeline(context, tracking_outputs):
    exp_cfg = context["exp_cfg"]
    kin_cfg = context["kin_cfg"]
    fit_cfg = context["fit_cfg"]
    osc_cfg = context["osc_cfg"]

    results_dict = results_to_dict(tracking_outputs["results"])
    valid_data = apply_valid_frame_window(
        results_dict,
        tuple(exp_cfg["valid_frame_range"]),
    )

    kin = compute_kinematics(
        data=valid_data,
        fps=exp_cfg["fps"],
        motion_axis=exp_cfg["motion_axis"],
        smooth_window=kin_cfg["smooth_window"],
        pixel_per_mm=exp_cfg["pixel_per_mm"],
    )

    advanced_outputs = run_enabled_advanced_analysis(
        data=valid_data,
        kin=kin,
        exp_cfg=exp_cfg,
        kin_cfg=kin_cfg,
        fit_cfg=fit_cfg,
        osc_cfg=osc_cfg,
    )

    return {
        "results_dict": results_dict,
        "valid_data": valid_data,
        "kin": kin,
        "advanced_outputs": advanced_outputs,
    }


def run_visualization_pipeline(context, tracking_outputs, analysis_outputs):
    export_all_visualizations(
        stack=tracking_outputs["stack"],
        roi=context["roi"],
        results=tracking_outputs["results"],
        background_roi=tracking_outputs["background_roi"],
        overlays=tracking_outputs["overlays"],
        valid_data=analysis_outputs["valid_data"],
        kin=analysis_outputs["kin"],
        advanced_outputs=analysis_outputs["advanced_outputs"],
        config=context["config"],
    )


def run_video_export_pipeline(context, tracking_outputs):
    export_presentation_video(
        stack=tracking_outputs["stack"],
        roi=context["roi"],
        results=tracking_outputs["results"],
        exp_cfg=context["exp_cfg"],
        video_cfg=context["video_cfg"],
        output_dir=context["output_dir"],
    )


def print_pipeline_summary(context, tracking_outputs, analysis_outputs):
    print_tracking_summary(
        stack=tracking_outputs["stack"],
        results=tracking_outputs["results"],
        valid_frame_range=tuple(context["exp_cfg"]["valid_frame_range"]),
    )

    print_kinematics_summary(analysis_outputs["kin"])

    print("\nMain pipeline test passed.")

    print_advanced_analysis_summary(analysis_outputs["advanced_outputs"])


# ============================================================
# C. 总入口
# ============================================================

def main():
    # 1. 读取配置与项目上下文
    context = load_project_context()

    # 2. tracking和预检查
    tracking_outputs = run_tracking_pipeline(context)
    # run_tracking_preview_pipeline(context, tracking_outputs)

    # 3. analysis
    # analysis_outputs = run_analysis_pipeline(context, tracking_outputs)

    # 4. summary
    # print_pipeline_summary(context, tracking_outputs, analysis_outputs)

    # 5. visualization
    # run_visualization_pipeline(context, tracking_outputs, analysis_outputs)

    # 6. video export
    run_video_export_pipeline(context, tracking_outputs)

    # 7. 返回完整上下文，便于后续 notebook / 调试复用
    return {
        **context,
        **tracking_outputs,
        # **analysis_outputs,
    }


if __name__ == "__main__":
    main()
