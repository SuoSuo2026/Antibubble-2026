from pathlib import Path
import copy
import json

import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
import numpy as np

from analysis import (
    apply_valid_frame_window,
    compute_kinematics,
    results_to_dict,
)
from config_loader import load_config
from main import run_tracking_pipeline


BASE_DIR = Path(__file__).resolve().parent


CASES = {
    "0415-11star_multi": {
        "title": "0415-11star_multi",
        "tiff_path": BASE_DIR / "raw_data" / "0415_exhibition" / "0415-11star_multi.tif",
        "output_dir": BASE_DIR
        / "processed_data"
        / "0415-11star_multi"
        / "0415-11star_multi_group_meeting",
        "roi": {"x": 0, "y": 190, "w": 1920, "h": 155},
        "valid_frame_range": [65, 195],
        "tracking_overrides": {
            "refine_thin_connections": True,
            "refine_min_distance_px": 5.5,
            "refine_dilate_size": 7,
            "refine_clip_to_original": True,
        },
    },
    "0415-42star_freefall": {
        "title": "0415-42star_freefall",
        "tiff_path": BASE_DIR
        / "raw_data"
        / "0415_exhibition"
        / "0415-42star_freefall.tif",
        "output_dir": BASE_DIR
        / "processed_data"
        / "0415-42star_freefall"
        / "0415-42star_freefall_group_meeting",
        "roi": {"x": 0, "y": 150, "w": 1870, "h": 240},
        "valid_frame_range": [140, 280],
        "tracking_overrides": {"refine_thin_connections": False},
    },
}


def build_context(spec):
    config = copy.deepcopy(load_config())
    config["data"]["tiff_path"] = str(spec["tiff_path"])
    config["data"]["output_dir"] = str(spec["output_dir"])
    config["roi"] = spec["roi"]
    config["experiment"]["valid_frame_range"] = spec["valid_frame_range"]
    config["experiment"]["motion_axis"] = "x"
    config["tracking"].update(spec["tracking_overrides"])

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
        "roi": (
            config["roi"]["x"],
            config["roi"]["y"],
            config["roi"]["w"],
            config["roi"]["h"],
        ),
    }


def load_acceleration_fit(outdir):
    path = outdir / "acceleration_fit_osc" / "a_fit_osc_summary.json"
    with open(path, "r", encoding="utf-8") as f:
        payload = json.load(f)
    return payload["summary"], payload["fits"]


def make_final_figure(case_name, spec):
    context = build_context(spec)
    outdir = context["output_dir"]
    outdir.mkdir(parents=True, exist_ok=True)

    tracking_outputs = run_tracking_pipeline(context)
    data = results_to_dict(tracking_outputs["results"])
    valid_data = apply_valid_frame_window(
        data, tuple(context["exp_cfg"]["valid_frame_range"])
    )
    kin = compute_kinematics(
        data=valid_data,
        fps=context["exp_cfg"]["fps"],
        motion_axis=context["exp_cfg"]["motion_axis"],
        smooth_window=context["kin_cfg"]["smooth_window"],
        pixel_per_mm=context["exp_cfg"]["pixel_per_mm"],
    )

    r_mm = valid_data["radius_volume_eq_px"] / context["exp_cfg"]["pixel_per_mm"]
    r_mean = float(np.nanmean(r_mm))
    r_std = float(np.nanstd(r_mm))
    r_rel = 100.0 * r_std / r_mean

    acc_summary, acc_fits = load_acceleration_fit(outdir)
    a_values = np.array([item["a_fit_osc_mm_s2"] for item in acc_fits], dtype=float)
    a_mean = acc_summary["a_fit_osc_mean_mm_s2"]
    a_std = acc_summary["a_fit_osc_std_mm_s2"]
    f_mean = acc_summary["freq_mean_hz"]
    f_std = acc_summary["freq_std_hz"]

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

    fit_index = np.arange(1, len(a_values) + 1)
    ax_a.plot(fit_index, a_values, "o-", ms=4, lw=1.8)
    ax_a.axhline(a_mean, linestyle="--", lw=1.8, label=f"mean = {a_mean:.1f} mm/s^2")
    ax_a.fill_between(
        fit_index,
        a_mean - a_std,
        a_mean + a_std,
        alpha=0.18,
        label=f"1 std = {a_std:.1f} mm/s^2",
    )
    ax_a.set_title("a-t proxy: quadratic + oscillation fit")
    ax_a.set_xlabel("Fit case index")
    ax_a.set_ylabel("a_fit_osc [mm/s^2]")
    ax_a.grid(alpha=0.3)
    ax_a.legend(fontsize=8)

    ax_r.plot(valid_data["frame"] / context["exp_cfg"]["fps"], r_mm, "o-", ms=3, lw=1.8)
    ax_r.axhline(r_mean, linestyle="--", lw=1.8, label=f"mean = {r_mean:.4f} mm")
    ax_r.set_title(f"R-t: volume-equivalent radius, rel std={r_rel:.2f}%")
    ax_r.set_xlabel("Time (s)")
    ax_r.set_ylabel("R [mm]")
    ax_r.grid(alpha=0.3)
    ax_r.legend(fontsize=8)

    ax_note.axis("off")
    text = (
        f"Characteristic values for {case_name}\n"
        f"a_fit_osc = {a_mean:.1f} +/- {a_std:.1f} mm/s^2 "
        f"({a_mean / 1000.0:.4f} +/- {a_std / 1000.0:.4f} m/s^2; "
        f"relative std = {acc_summary['a_fit_osc_rel_std_percent']:.2f}%)    |    "
        f"R = {r_mean:.4f} +/- {r_std:.4f} mm "
        f"(relative std = {r_rel:.2f}%)    |    "
        f"oscillation frequency f = {f_mean:.2f} +/- {f_std:.2f} Hz    |    "
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

    fig.suptitle(f"{case_name}: group meeting summary", fontsize=16)
    fig.savefig(outdir / "group_meeting_final_four_panel.png", bbox_inches="tight")
    plt.close(fig)

    result = {
        "case": case_name,
        "figure": str((outdir / "group_meeting_final_four_panel.png").resolve()),
        "a_fit_osc_mean_mm_s2": a_mean,
        "a_fit_osc_std_mm_s2": a_std,
        "radius_mean_mm": r_mean,
        "radius_std_mm": r_std,
        "freq_mean_hz": f_mean,
        "freq_std_hz": f_std,
    }

    with open(outdir / "group_meeting_final_metrics.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    return result


def main():
    results = {}
    for case_name, spec in CASES.items():
        results[case_name] = make_final_figure(case_name, spec)

    outdir = BASE_DIR / "processed_data" / "group_meeting_final_figures"
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outdir / "group_meeting_final_metrics.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
