"""Standalone E1 figures; no score tuning or candidate/map changes."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from e1_taxonomy import LABELS


def main():
    spec = json.loads((ROOT / "configs/e1_taxonomy.json").read_text())
    out = ROOT / spec["output"]
    figures = out / "figures"
    figures.mkdir(exist_ok=True)
    report = json.loads((out / "taxonomy_summary.json").read_text())
    arrays = np.load(out / "candidate_labels.npz")
    palette = ["#9da5af", "#299d8f", "#e8ad39", "#ce4b52"]
    short = ["Ambiguous", "Well placed (proxy)", "Redundant valid (proxy)", "Repeated front (proxy)"]
    arms = ["estimated_pose", "gt_anchor_pose_diagnostic"]
    def save(fig, name):
        fig.savefig(figures / f"{name}.png", dpi=170, bbox_inches="tight")
        fig.savefig(figures / f"{name}.pdf", bbox_inches="tight")
        plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.2), sharey=True)
    for ax, arm in zip(axes, arms):
        for x, scope in enumerate(("raw", "active")):
            bottom = 0
            for code, name in LABELS.items():
                value = report["arms"][arm][scope][name]["fraction"] * 100
                ax.bar(x, value, bottom=bottom, color=palette[code], label=short[code] if x == 0 else None)
                if value > 5:
                    ax.text(x, bottom + value / 2, f"{value:.1f}%", ha="center", va="center", fontsize=9)
                bottom += value
        ax.set_xticks([0, 1], ["Raw candidates\n737,280", "Original active map\n705,772"])
        ax.set_title(arm.replace("_", " "))
        ax.set_ylim(0, 100)
    axes[0].set_ylabel("Candidate fraction (%)")
    axes[1].legend(loc="upper left", bbox_to_anchor=(1, 1), fontsize=9)
    fig.suptitle("E1: fixed-baseline geometry taxonomy (one scene, descriptive pilot)")
    fig.tight_layout()
    save(fig, "taxonomy")

    fig, axes = plt.subplots(2, 5, figsize=(16, 4.7))
    cmap = ListedColormap(palette)
    for row, arm in enumerate(arms):
        for col, lineage in enumerate(report["lineage"]):
            mask = arrays["anchor_kf"] == col
            image = arrays[arm + "_labels_raw"][mask].reshape(288, 512).copy()
            axes[row, col].imshow(image, cmap=cmap, vmin=0, vmax=3, interpolation="nearest")
            axes[row, col].set_title(f"KF{col}, frame {lineage['original_frame_id']}", fontsize=10)
            axes[row, col].set_xticks([])
            axes[row, col].set_yticks([])
            if col == 0:
                axes[row, col].set_ylabel("Estimated pose" if row == 0 else "GT-anchor diagnostic")
    fig.suptitle("Labels on source pixel grid; all raw candidates shown; no admission decisions")
    fig.tight_layout()
    save(fig, "label_maps")

    if (out / "render_metrics.json").exists():
        frames = (41, 149, 299)
        fig, axes = plt.subplots(5, 3, figsize=(12, 11))
        for col, frame in enumerate(frames):
            est = np.load(out / "render" / f"estimated_pose_frame{frame:06d}.npz")
            diag = np.load(out / "render" / f"gt_anchor_pose_diagnostic_frame{frame:06d}.npz")
            valid = est["valid"]
            covered = (est["weight"] > spec["render_coverage_weight_min"]) & (est["rendered_depth"] > 0)
            diag_covered = (diag["weight"] > spec["render_coverage_weight_min"]) & (diag["rendered_depth"] > 0)
            layers = [(np.ma.masked_where(~valid, est["gt_depth"]), "viridis", 0, 5),
                      (np.ma.masked_where(~covered, est["rendered_depth"]), "viridis", 0, 5),
                      (np.ma.masked_where(~diag_covered, diag["rendered_depth"]), "viridis", 0, 5),
                      (np.ma.masked_where(~(valid & covered), np.clip(est["rendered_depth"] - est["gt_depth"], -0.5, 0.5)), "coolwarm", -0.5, 0.5),
                      (est["front_class_weight"], "magma", 0, 0.5)]
            for row, (layer, color, vmin, vmax) in enumerate(layers):
                im = axes[row, col].imshow(layer, cmap=color, vmin=vmin, vmax=vmax)
                axes[row, col].set_xticks([])
                axes[row, col].set_yticks([])
                if row == 0:
                    axes[row, col].set_title(f"Held-out frame {frame}")
                if col == 0:
                    axes[row, col].set_ylabel(["GT z (m)", "Estimated-map z (m)", "GT-anchor z (m)",
                                               "Estimated minus GT (m)", "Front-class alpha weight"][row])
                if col == 2:
                    fig.colorbar(im, ax=axes[row, col], fraction=0.03)
        fig.suptitle("E1: full frozen map rendering; class weights include transmittance")
        fig.tight_layout()
        save(fig, "rendered_geometry")
    print(f"Figures: {figures}")


if __name__ == "__main__":
    main()
