"""Export descriptive E2 comparison figures without adjusting any scores."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from e2_metrics import pr_metrics
from score_e2 import digest, save_json

DISPLAY = {"B2_confidence": "Confidence", "B2_opacity": "Opacity", "B5_self_residual": "Self residual",
           "B6_depth_front": "Cross depth", "B7_rgb_l1_region": "Warped RGB L1", "B7_rgb_ncc_region": "Warped RGB NCC",
           "B8_dog_redundancy": "DoG redundancy", "P1_plane_front_1view": "Plane (1+ view)", "P1_plane_front_2view": "Plane (2+ views)"}


def main():
    spec = json.loads((ROOT / "configs/e2_discriminability.json").read_text())
    out = ROOT / spec["output"]
    results = json.loads((out / "metrics.json").read_text())
    figures = out / "figures"; figures.mkdir(exist_ok=True)
    methods = spec["methods"]
    f = np.load(out / "features.npz")
    b8 = np.load(out / "b8_features.npz")["B8_dog_redundancy"]
    labels = np.load(out / "evaluation_labels.npz")["raw__creation_pose_gt_proxy"]
    temporal = np.isin(f["anchor_kf"], spec["temporal_evaluation_kfs"])
    def save(fig, name):
        fig.savefig(figures / f"{name}.png", dpi=170, bbox_inches="tight")
        fig.savefig(figures / f"{name}.pdf", bbox_inches="tight")
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(12, 4))
    x = np.arange(len(methods))
    for j, mode in enumerate(spec["score_availability_modes"]):
        table = results["results"]["raw"]["creation_pose_gt_proxy"][mode]["all_descriptive"]
        ax.bar(x + (j - 1) * 0.24, [100 * table[m]["score_coverage"] for m in methods], width=0.24,
               label=mode.replace("_", " "))
    ax.set_xticks(x, [DISPLAY[m] for m in methods], rotation=25, ha="right")
    ax.set_ylabel("Raw-candidate score coverage (%)")
    ax.set_title("E2: evidence availability (no missing-evidence rejection)")
    ax.legend(fontsize=8)
    fig.tight_layout(); save(fig, "availability")

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for ax, group in zip(axes, spec["common_cohorts"]):
        scores = {m: b8 if m == "B8_dog_redundancy" else f["at_creation__" + m] for m in group}
        common = temporal & np.isin(labels, [1, 3])
        for score in scores.values():common &= np.isfinite(score)
        for m, score in scores.items():
            metric, (recall, precision) = pr_metrics(labels[common] == 3, score[common])
            if len(recall):ax.step(recall, precision, where="pre", label=f"{DISPLAY[m]} AP={metric['average_precision']:.3f}")
        if common.any():ax.axhline(np.mean(labels[common] == 3), color="gray", ls=":", label="cohort prevalence")
        ax.set_xlim(0, 1);ax.set_ylim(0, 1.02)
        ax.set_xlabel("Bad-proxy recall (within common cohort)")
        ax.set_ylabel("Bad-proxy precision")
        ax.set_title(f"Same temporal cohort, n={common.sum():,}")
        ax.legend(fontsize=7)
    fig.suptitle("E2: creation-time ranking; GT proxy, one previously inspected scene")
    fig.tight_layout(); save(fig, "common_cohort_pr")

    thresholds = json.loads((out / "thresholds_development_only.json").read_text())
    development = np.isin(f["anchor_kf"], spec["development_kfs"])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, method in zip(axes, ("P1_plane_front_1view", "B6_depth_front")):
        score = f["at_creation__" + method]
        finite = np.isfinite(score)
        bins = np.linspace(0, np.log1p(np.nanmax(score)) + 1e-6, 50)
        for title, mask in (("development normal", development & (labels == 1)),
                            ("temporal normal", temporal & (labels == 1)),
                            ("temporal bad proxy", temporal & (labels == 3))):
            ax.hist(np.log1p(score[finite & mask]), bins=bins, density=True, histtype="step", label=title)
        threshold = thresholds["raw"]["at_creation"][method]["0.99"]
        if threshold is not None:ax.axvline(np.log1p(threshold), color="black", ls="--", label="sealed 99% retention cutoff")
        ax.set_title(DISPLAY[method]);ax.set_xlabel("log(1 + positive conflict score)");ax.set_ylabel("Density")
        ax.legend(fontsize=7)
    fig.suptitle("E2: development cutoff transfer; no temporal-label threshold tuning")
    fig.tight_layout();save(fig, "calibration_transfer")

    fig, axes = plt.subplots(3, 5, figsize=(16, 6))
    for i in range(5):
        p = np.load(out / "premaps" / f"kf{i:04d}.npz")
        axes[0, i].imshow(p["source"]);axes[1, i].imshow(np.clip(p["render_predicted_rays"], 0, 1))
        axes[2, i].imshow(np.ma.masked_where(~p["eligible"], p["score"]), cmap="coolwarm", vmin=-0.1, vmax=0.1)
        axes[0, i].set_title(f"KF{i}: previous KFs 0..{i-1}" if i else "KF0: empty pre-map")
        for row in range(3):
            axes[row, i].set_xticks([]);axes[row, i].set_yticks([])
    for i, title in enumerate(["Input RGB", "Causal pre-map RGB", "DoG render - input"]):axes[i, 0].set_ylabel(title)
    fig.suptitle("B8 inspired proxy: current and future candidates excluded from each pre-map")
    fig.tight_layout(); save(fig, "b8_premaps")
    save_json(out / "figure_manifest.json", dict(code=digest(Path(__file__)), metrics=digest(out / "metrics.json")))
    print(f"Figures: {figures}")


if __name__ == "__main__":
    main()
