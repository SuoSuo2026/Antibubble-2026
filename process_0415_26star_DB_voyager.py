from pathlib import Path
import copy
import json

import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np

from analysis import (
    apply_valid_frame_window,
    compute_kinematics,
    fit_quadratic_plus_oscillation_scan,
    results_to_dict,
    run_enabled_advanced_analysis,
)
from config_loader import load_config
from main import (
    run_tracking_pipeline,
    run_tracking_preview_pipeline,
    run_visualization_pipeline,
    run_video_export_pipeline,
)


BASE_DIR = Path(__file__).resolve().parent
CASE_NAME = "0415-26star_DB voyager"
CASE_SLUG = "0415-26star_DB_voyager"


def build_context(output_dir, valid_frame_range, roi, tracking_overrides):
    config = copy.deepcopy(load_config())
    config["data"]["tiff_path"] = str(
        BASE_DIR / "raw_data" / "0415_exhibition" / f"{CASE_NAME}.tif"
    )
    config["data"]["output_dir"] = str(output_dir)
    config["roi"] = roi
    config["experiment"]["valid_frame_range"] = list(valid_frame_range)
    config["experiment"]["motion_axis"] = "x"
    config["experiment"]["use_axisymmetric_volume_centroid"] = False
    config["tracking"].update(tracking_overrides)
    config["visualization"]["preview_sample_count"] = 6
    config["video_export"]["enabled"] = True
    config["video_export"]["filename"] = f"{CASE_SLUG}_group_meeting_monitor.mp4"
    config["video_export"]["frame_range_mode"] = "valid"
    config["video_export"]["crop_to_roi"] = True
    config["video_export"]["scale_bar_y"] = min(260, roi["h"] - 20)

    return {
        "config": config,
        "data_cfg": config["data"],
        "exp_cfg": config["experiment"],
        "kin_cfg": config["kinematics"],
        "fit_cfg": config["fit"],
        "osc_cfg": config["oscillation"],
        "vis_cfg": config["visualization"],
        "video_cfg": config["video_export"],
        "tiff_path": Path(config["data"]["tiff_path"]),
        "output_dir": Path(config["data"]["output_dir"]),
        "roi": (roi["x"], roi["y"], roi["w"], roi["h"]),
    }


def run_analysis_pipeline_for_context(context, tracking_outputs):
    results_dict = results_to_dict(tracking_outputs["results"])
    valid_data = apply_valid_frame_window(
        results_dict, tuple(context["exp_cfg"]["valid_frame_range"])
    )
    kin = compute_kinematics(
        data=valid_data,
        fps=context["exp_cfg"]["fps"],
        motion_axis=context["exp_cfg"]["motion_axis"],
        smooth_window=context["kin_cfg"]["smooth_window"],
        pixel_per_mm=context["exp_cfg"]["pixel_per_mm"],
    )
    advanced_outputs = run_enabled_advanced_analysis(
        data=valid_data,
        kin=kin,
        exp_cfg=context["exp_cfg"],
        kin_cfg=context["kin_cfg"],
        fit_cfg=context["fit_cfg"],
        osc_cfg=context["osc_cfg"],
    )
    return {
        "results_dict": results_dict,
        "valid_data": valid_data,
        "kin": kin,
        "advanced_outputs": advanced_outputs,
    }


def summarize_radius(valid_data, pixel_per_mm):
    r_mm = valid_data["radius_volume_eq_px"] / pixel_per_mm
    return {
        "radius_mean_mm": float(np.nanmean(r_mm)),
        "radius_std_mm": float(np.nanstd(r_mm)),
        "radius_rel_std_percent": float(100.0 * np.nanstd(r_mm) / np.nanmean(r_mm)),
    }


def run_case(output_dir, valid_frame_range, roi, tracking_overrides, export_video=False):
    context = build_context(output_dir, valid_frame_range, roi, tracking_overrides)
    context["output_dir"].mkdir(parents=True, exist_ok=True)
    tracking_outputs = run_tracking_pipeline(context)
    run_tracking_preview_pipeline(context, tracking_outputs)
    analysis_outputs = run_analysis_pipeline_for_context(context, tracking_outputs)
    run_visualization_pipeline(context, tracking_outputs, analysis_outputs)
    if export_video:
        run_video_export_pipeline(context, tracking_outputs)

    valid_data = analysis_outputs["valid_data"]
    found_ratio = float(np.nanmean(valid_data["found"].astype(float)))
    radius_summary = summarize_radius(valid_data, context["exp_cfg"]["pixel_per_mm"])
    summary = {
        "case": CASE_NAME,
        "output_dir": str(context["output_dir"].resolve()),
        "valid_frame_range": list(valid_frame_range),
        "roi": roi,
        "tracking_overrides": tracking_overrides,
        "valid_found_ratio": found_ratio,
        **radius_summary,
    }
    with open(context["output_dir"] / "case_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return context, tracking_outputs, analysis_outputs, summary


def fit_acceleration_oscillation(context, tracking_outputs):
    outdir = context["output_dir"] / "acceleration_fit_osc"
    outdir.mkdir(parents=True, exist_ok=True)
    data = results_to_dict(tracking_outputs["results"])
    valid_data = apply_valid_frame_window(
        data, tuple(context["exp_cfg"]["valid_frame_range"])
    )

    fit_windows = [
        [0.082, 0.136],
        [0.084, 0.136],
        [0.086, 0.136],
        [0.082, 0.134],
        [0.084, 0.134],
        [0.086, 0.134],
        [0.088, 0.134],
        [0.084, 0.132],
        [0.086, 0.132],
    ]
    smooth_windows = [7, 9, 11]
    fit_results = []
    for smooth_window in smooth_windows:
        kin = compute_kinematics(
            data=valid_data,
            fps=context["exp_cfg"]["fps"],
            motion_axis=context["exp_cfg"]["motion_axis"],
            smooth_window=smooth_window,
            pixel_per_mm=context["exp_cfg"]["pixel_per_mm"],
        )
        for fit_window in fit_windows:
            fit = fit_quadratic_plus_oscillation_scan(
                kin=kin,
                fit_time_range=tuple(fit_window),
                freq_range=(20.0, 90.0),
                n_freq=701,
            )
            if fit is None:
                continue
            fit_results.append(
                {
                    "smooth_window": smooth_window,
                    "fit_window": fit_window,
                    "a_fit_osc_mm_s2": float(fit["a_fit"]),
                    "freq_hz": float(fit["freq_hz"]),
                    "amp_mm": float(fit["amp"]),
                    "residual_rms_mm": float(fit["residual_rms"]),
                    "r2": float(fit["r2"]),
                    "fit": fit,
                    "kin": kin,
                }
            )

    a_values = np.array([item["a_fit_osc_mm_s2"] for item in fit_results], dtype=float)
    freq_values = np.array([item["freq_hz"] for item in fit_results], dtype=float)
    rms_values = np.array([item["residual_rms_mm"] for item in fit_results], dtype=float)
    summary = {
        "case": CASE_NAME,
        "valid_frame_range": context["exp_cfg"]["valid_frame_range"],
        "fit_windows": fit_windows,
        "smooth_windows": smooth_windows,
        "n_fits": int(len(fit_results)),
        "a_fit_osc_mean_mm_s2": float(np.mean(a_values)),
        "a_fit_osc_std_mm_s2": float(np.std(a_values)),
        "a_fit_osc_rel_std_percent": float(
            100.0 * np.std(a_values) / abs(np.mean(a_values))
        ),
        "freq_mean_hz": float(np.mean(freq_values)),
        "freq_std_hz": float(np.std(freq_values)),
        "residual_rms_mean_mm": float(np.mean(rms_values)),
    }
    serializable = [
        {k: v for k, v in item.items() if k not in ("fit", "kin")} for item in fit_results
    ]
    with open(outdir / "a_fit_osc_summary.json", "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "fits": serializable}, f, indent=2)

    idx = np.arange(1, len(a_values) + 1)
    fig, ax = plt.subplots(figsize=(10, 4), dpi=200)
    ax.plot(idx, a_values, "o-", ms=4, lw=1.8)
    ax.axhline(summary["a_fit_osc_mean_mm_s2"], ls="--", lw=1.8)
    ax.fill_between(
        idx,
        summary["a_fit_osc_mean_mm_s2"] - summary["a_fit_osc_std_mm_s2"],
        summary["a_fit_osc_mean_mm_s2"] + summary["a_fit_osc_std_mm_s2"],
        alpha=0.18,
    )
    ax.set_title(f"{CASE_NAME}: quadratic + oscillation acceleration")
    ax.set_xlabel("Fit case index")
    ax.set_ylabel("a_fit_osc [mm/s^2]")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(outdir / "a_fit_osc_summary.png", bbox_inches="tight")
    plt.close(fig)
    return summary, serializable


def make_final_four_panel(context, analysis_outputs, acc_summary, acc_fits):
    outdir = context["output_dir"]
    valid_data = analysis_outputs["valid_data"]
    kin = analysis_outputs["kin"]
    pixel_per_mm = context["exp_cfg"]["pixel_per_mm"]

    r_mm = valid_data["radius_volume_eq_px"] / pixel_per_mm
    r_mean = float(np.nanmean(r_mm))
    r_std = float(np.nanstd(r_mm))
    r_rel = 100.0 * r_std / r_mean
    a_values = np.array([item["a_fit_osc_mm_s2"] for item in acc_fits], dtype=float)
    fit_index = np.arange(1, len(a_values) + 1)

    fig = plt.figure(figsize=(13, 9), dpi=200)
    gs = GridSpec(3, 2, height_ratios=[1.0, 1.0, 0.34], hspace=0.42, wspace=0.28)
    ax_x = fig.add_subplot(gs[0, 0])
    ax_v = fig.add_subplot(gs[0, 1])
    ax_a = fig.add_subplot(gs[1, 0])
    ax_r = fig.add_subplot(gs[1, 1])
    ax_note = fig.add_subplot(gs[2, :])

    ax_x.plot(kin["t"], kin["pos_smooth"], "-", lw=2.2)
    ax_x.set_title("x-t: centroid position")
    ax_x.set_xlabel("Time (s)")
    ax_x.set_ylabel(f"x [{kin['unit']}]")
    ax_x.grid(alpha=0.3)

    ax_v.plot(kin["t"], kin["vel"], "-", lw=2.2)
    ax_v.set_title("v-t: centroid velocity")
    ax_v.set_xlabel("Time (s)")
    ax_v.set_ylabel(f"v [{kin['unit']}/s]")
    ax_v.grid(alpha=0.3)

    ax_a.plot(fit_index, a_values, "o-", ms=4, lw=1.8)
    ax_a.axhline(acc_summary["a_fit_osc_mean_mm_s2"], ls="--", lw=1.8)
    ax_a.fill_between(
        fit_index,
        acc_summary["a_fit_osc_mean_mm_s2"] - acc_summary["a_fit_osc_std_mm_s2"],
        acc_summary["a_fit_osc_mean_mm_s2"] + acc_summary["a_fit_osc_std_mm_s2"],
        alpha=0.18,
    )
    ax_a.set_title("a: quadratic + oscillation fit")
    ax_a.set_xlabel("Fit case index")
    ax_a.set_ylabel("a_fit_osc [mm/s^2]")
    ax_a.grid(alpha=0.3)

    ax_r.plot(valid_data["frame"] / context["exp_cfg"]["fps"], r_mm, "o-", ms=3, lw=1.8)
    ax_r.axhline(r_mean, ls="--", lw=1.8)
    ax_r.set_title(f"R-t: volume-equivalent radius, rel std={r_rel:.2f}%")
    ax_r.set_xlabel("Time (s)")
    ax_r.set_ylabel("R [mm]")
    ax_r.grid(alpha=0.3)

    ax_note.axis("off")
    text = (
        f"Characteristic values for {CASE_NAME}\n"
        f"a_fit_osc = {acc_summary['a_fit_osc_mean_mm_s2']:.1f} +/- "
        f"{acc_summary['a_fit_osc_std_mm_s2']:.1f} mm/s^2 "
        f"({acc_summary['a_fit_osc_mean_mm_s2'] / 1000.0:.4f} +/- "
        f"{acc_summary['a_fit_osc_std_mm_s2'] / 1000.0:.4f} m/s^2; "
        f"relative std = {acc_summary['a_fit_osc_rel_std_percent']:.2f}%)    |    "
        f"R = {r_mean:.4f} +/- {r_std:.4f} mm "
        f"(relative std = {r_rel:.2f}%)    |    "
        f"oscillation frequency f = {acc_summary['freq_mean_hz']:.2f} +/- "
        f"{acc_summary['freq_std_hz']:.2f} Hz    |    "
        f"valid frames = {context['exp_cfg']['valid_frame_range']}"
    )
    ax_note.text(
        0.5,
        0.52,
        text,
        ha="center",
        va="center",
        fontsize=12,
        bbox={"boxstyle": "round,pad=0.55", "facecolor": "#f7f7f7", "edgecolor": "#bdbdbd"},
    )
    fig.suptitle(f"{CASE_NAME}: group meeting summary", fontsize=16)
    fig.savefig(outdir / "group_meeting_final_four_panel.png", bbox_inches="tight")
    plt.close(fig)

    metrics = {
        "case": CASE_NAME,
        "figure": str((outdir / "group_meeting_final_four_panel.png").resolve()),
        "a_fit_osc_mean_mm_s2": acc_summary["a_fit_osc_mean_mm_s2"],
        "a_fit_osc_std_mm_s2": acc_summary["a_fit_osc_std_mm_s2"],
        "radius_mean_mm": r_mean,
        "radius_std_mm": r_std,
        "radius_rel_std_percent": r_rel,
        "freq_mean_hz": acc_summary["freq_mean_hz"],
        "freq_std_hz": acc_summary["freq_std_hz"],
    }
    with open(outdir / "group_meeting_final_metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    return metrics


def main():
    output_dir = BASE_DIR / "processed_data" / CASE_SLUG / f"{CASE_SLUG}_group_meeting"
    roi = {"x": 0, "y": 120, "w": 1920, "h": 320}
    valid_frame_range = [160, 275]
    tracking_overrides = {
        "refine_thin_connections": True,
        "refine_min_distance_px": 5.5,
        "refine_dilate_size": 7,
        "refine_clip_to_original": True,
    }
    context, tracking_outputs, analysis_outputs, summary = run_case(
        output_dir=output_dir,
        valid_frame_range=valid_frame_range,
        roi=roi,
        tracking_overrides=tracking_overrides,
        export_video=True,
    )
    acc_summary, acc_fits = fit_acceleration_oscillation(context, tracking_outputs)
    metrics = make_final_four_panel(context, analysis_outputs, acc_summary, acc_fits)
    print(json.dumps({"summary": summary, "metrics": metrics}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
