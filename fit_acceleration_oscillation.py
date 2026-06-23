from pathlib import Path
import copy
import json

import matplotlib.pyplot as plt
import numpy as np

from analysis import (
    apply_valid_frame_window,
    compute_kinematics,
    fit_quadratic_plus_oscillation_scan,
    results_to_dict,
)
from config_loader import load_config
from main import run_tracking_pipeline


BASE_DIR = Path(__file__).resolve().parent


CASES = {
    "0415-11star_multi": {
        "tiff_path": BASE_DIR / "raw_data" / "0415_exhibition" / "0415-11star_multi.tif",
        "output_dir": BASE_DIR
        / "processed_data"
        / "0415-11star_multi"
        / "0415-11star_multi_group_meeting"
        / "acceleration_fit_osc",
        "roi": {"x": 0, "y": 190, "w": 1920, "h": 155},
        "valid_frame_range": [65, 195],
        "tracking_overrides": {
            "refine_thin_connections": True,
            "refine_min_distance_px": 5.5,
            "refine_dilate_size": 7,
            "refine_clip_to_original": True,
        },
        "fit_windows": [
            [0.040, 0.090],
            [0.042, 0.090],
            [0.044, 0.090],
            [0.040, 0.088],
            [0.042, 0.088],
            [0.044, 0.088],
            [0.046, 0.088],
            [0.042, 0.086],
            [0.044, 0.086],
        ],
    },
    "0415-42star_freefall": {
        "tiff_path": BASE_DIR
        / "raw_data"
        / "0415_exhibition"
        / "0415-42star_freefall.tif",
        "output_dir": BASE_DIR
        / "processed_data"
        / "0415-42star_freefall"
        / "0415-42star_freefall_group_meeting"
        / "acceleration_fit_osc",
        "roi": {"x": 0, "y": 150, "w": 1870, "h": 240},
        "valid_frame_range": [140, 280],
        "tracking_overrides": {
            "refine_thin_connections": False,
        },
        "fit_windows": [
            [0.078, 0.132],
            [0.080, 0.132],
            [0.082, 0.132],
            [0.078, 0.130],
            [0.080, 0.130],
            [0.082, 0.130],
            [0.084, 0.130],
            [0.080, 0.128],
            [0.082, 0.128],
        ],
    },
}


SMOOTH_WINDOWS = [7, 9, 11]
FREQ_RANGE = (20.0, 80.0)
FREQ_NUM = 601


def build_context(case_name, spec):
    config = load_config()
    config = copy.deepcopy(config)

    config["data"]["tiff_path"] = str(spec["tiff_path"])
    config["data"]["output_dir"] = str(spec["output_dir"])
    config["roi"] = spec["roi"]
    config["experiment"]["valid_frame_range"] = spec["valid_frame_range"]
    config["experiment"]["motion_axis"] = "x"
    config["tracking"].update(spec["tracking_overrides"])

    return {
        "case_name": case_name,
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


def fit_case(case_name, spec):
    context = build_context(case_name, spec)
    outdir = context["output_dir"]
    outdir.mkdir(parents=True, exist_ok=True)

    tracking_outputs = run_tracking_pipeline(context)
    data = results_to_dict(tracking_outputs["results"])
    valid_data = apply_valid_frame_window(
        data, tuple(context["exp_cfg"]["valid_frame_range"])
    )

    fit_results = []
    for smooth_window in SMOOTH_WINDOWS:
        kin = compute_kinematics(
            data=valid_data,
            fps=context["exp_cfg"]["fps"],
            motion_axis=context["exp_cfg"]["motion_axis"],
            smooth_window=smooth_window,
            pixel_per_mm=context["exp_cfg"]["pixel_per_mm"],
        )
        for fit_window in spec["fit_windows"]:
            fit = fit_quadratic_plus_oscillation_scan(
                kin=kin,
                fit_time_range=tuple(fit_window),
                freq_range=FREQ_RANGE,
                n_freq=FREQ_NUM,
            )
            if fit is None:
                continue
            fit_results.append(
                {
                    "smooth_window": smooth_window,
                    "fit_window": fit_window,
                    "a_fit_osc_mm_s2": fit["a_fit"],
                    "freq_hz": fit["freq_hz"],
                    "amp_mm": fit["amp"],
                    "residual_rms_mm": fit["residual_rms"],
                    "r2": fit["r2"],
                    "fit": fit,
                    "kin": kin,
                }
            )

    a_values = np.array([item["a_fit_osc_mm_s2"] for item in fit_results], dtype=float)
    freq_values = np.array([item["freq_hz"] for item in fit_results], dtype=float)
    rms_values = np.array([item["residual_rms_mm"] for item in fit_results], dtype=float)

    summary = {
        "case": case_name,
        "valid_frame_range": context["exp_cfg"]["valid_frame_range"],
        "fit_windows": spec["fit_windows"],
        "smooth_windows": SMOOTH_WINDOWS,
        "freq_scan_range_hz": list(FREQ_RANGE),
        "n_fits": int(len(fit_results)),
        "a_fit_osc_mean_mm_s2": float(np.mean(a_values)),
        "a_fit_osc_std_mm_s2": float(np.std(a_values)),
        "a_fit_osc_rel_std_percent": float(
            100.0 * np.std(a_values) / abs(np.mean(a_values))
        ),
        "a_fit_osc_min_mm_s2": float(np.min(a_values)),
        "a_fit_osc_max_mm_s2": float(np.max(a_values)),
        "freq_mean_hz": float(np.mean(freq_values)),
        "freq_std_hz": float(np.std(freq_values)),
        "residual_rms_mean_mm": float(np.mean(rms_values)),
    }

    serializable_results = []
    for item in fit_results:
        serializable_results.append(
            {
                "smooth_window": item["smooth_window"],
                "fit_window": item["fit_window"],
                "a_fit_osc_mm_s2": item["a_fit_osc_mm_s2"],
                "freq_hz": item["freq_hz"],
                "amp_mm": item["amp_mm"],
                "residual_rms_mm": item["residual_rms_mm"],
                "r2": item["r2"],
            }
        )

    with open(outdir / "a_fit_osc_summary.json", "w", encoding="utf-8") as f:
        json.dump(
            {"summary": summary, "fits": serializable_results},
            f,
            indent=2,
            ensure_ascii=False,
        )

    best_idx = int(np.argmin(rms_values))
    best = fit_results[best_idx]
    plot_acceleration_fit(case_name, outdir, fit_results, summary, best)

    return summary


def plot_acceleration_fit(case_name, outdir, fit_results, summary, best):
    a_values = np.array([item["a_fit_osc_mm_s2"] for item in fit_results], dtype=float)
    indices = np.arange(1, len(a_values) + 1)
    mean_a = summary["a_fit_osc_mean_mm_s2"]
    std_a = summary["a_fit_osc_std_mm_s2"]

    fig, ax = plt.subplots(figsize=(10, 4), dpi=200)
    ax.plot(indices, a_values, "o-", ms=4, lw=1.8, label="window/smoothing fits")
    ax.axhline(mean_a, linestyle="--", lw=1.8, label=f"mean = {mean_a:.2f} mm/s^2")
    ax.fill_between(
        indices,
        mean_a - std_a,
        mean_a + std_a,
        alpha=0.18,
        label=f"1 std = {std_a:.2f} mm/s^2",
    )
    ax.set_xlabel("Fit case index")
    ax.set_ylabel("a_fit_osc [mm/s^2]")
    ax.set_title(
        f"{case_name}: quadratic + oscillation acceleration "
        f"(relative std = {summary['a_fit_osc_rel_std_percent']:.2f}%)"
    )
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outdir / "a_fit_osc_summary.png", bbox_inches="tight")
    plt.close(fig)

    fit = best["fit"]
    kin = best["kin"]
    fig, ax = plt.subplots(figsize=(10, 4), dpi=200)
    ax.plot(kin["t"], kin["pos_smooth"], "-", lw=1.5, label="smoothed x(t)")
    ax.plot(
        fit["t_fit"],
        fit["x_fit_curve"],
        "--",
        lw=2.0,
        label="best quadratic + oscillation fit",
    )
    ax.set_xlabel("Time (s)")
    ax.set_ylabel(f"x [{kin['unit']}]")
    ax.set_title(
        f"{case_name}: best fit, a_fit_osc={best['a_fit_osc_mm_s2']:.2f} mm/s^2, "
        f"f={best['freq_hz']:.2f} Hz"
    )
    ax.grid(alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(outdir / "a_fit_osc_best_position_fit.png", bbox_inches="tight")
    plt.close(fig)


def main():
    summaries = {}
    for case_name, spec in CASES.items():
        summaries[case_name] = fit_case(case_name, spec)

    combined_dir = BASE_DIR / "processed_data" / "acceleration_fit_osc_comparison"
    combined_dir.mkdir(parents=True, exist_ok=True)
    with open(combined_dir / "a_fit_osc_all_cases_summary.json", "w", encoding="utf-8") as f:
        json.dump(summaries, f, indent=2, ensure_ascii=False)

    print(json.dumps(summaries, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
