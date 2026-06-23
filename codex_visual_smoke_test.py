from pathlib import Path

import matplotlib.pyplot as plt
import tifffile

from config_loader import get_roi_tuple, load_config
from image_utils import normalize_to_uint8


def main():
    config = load_config()
    roi = get_roi_tuple(config)
    tiff_path = Path(config["data"]["tiff_path"])

    output_dir = Path("codex_internal_test_output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / "visual_smoke_test.png"

    first_frame = tifffile.imread(str(tiff_path), key=0)
    x, y, w, h = roi
    preview = normalize_to_uint8(first_frame)

    fig, ax = plt.subplots(figsize=(12, 5), dpi=160)
    ax.imshow(preview, cmap="gray")
    rect = plt.Rectangle((x, y), w, h, fill=False, edgecolor="red", linewidth=1.5)
    ax.add_patch(rect)
    ax.set_title("TIFF first frame with configured ROI")
    ax.set_xlabel(f"{tiff_path.name} | frame shape: {first_frame.shape}")
    ax.set_axis_off()

    fig.tight_layout()
    fig.savefig(output_path, bbox_inches="tight")
    plt.close(fig)

    print(f"Saved visual smoke test to: {output_path.resolve()}")


if __name__ == "__main__":
    main()
