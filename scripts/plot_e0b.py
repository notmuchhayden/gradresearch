"""Create standalone E0b feasibility figures from audited measurements."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "results/E0b_ancestry_causality"


def main():
    summary = json.loads((RUN / "extended/audit_summary.json").read_text())
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
    for mode, color in (("raw", "#2878b5"), ("fused", "#e07a34")):
        rows = [r for r in summary["candidate_pools"] if r["mode"] == mode]
        x = np.arange(len(rows))
        width = .36
        axes[0].bar(x + (-width / 2 if mode == "raw" else width / 2),
                    [100 * r["creation"]["sample_supported_1plus"] / r["creation"]["sample_count"] for r in rows],
                    width, label=mode, color=color)
        measures = summary["availability"][mode]
        labels = ["Source disjoint\nat creation", "Ray + parallax\nat creation", "Causal\nwith deferral", "Final-pose\nhindsight"]
        values = [measures[k] * 100 for k in (
            "source_disjoint_at_creation_pool_fraction", "geometry_at_creation_fraction",
            "geometry_eventual_causal_fraction", "geometry_final_revision_hindsight_fraction")]
        axes[1].plot(np.arange(4), values, marker="o", label=mode, color=color)
    axes[0].set_xticks(x, [str(r["original_frame"]) for r in rows])
    axes[0].set_xlabel("Candidate keyframe (original frame ID)")
    axes[0].set_title("Support available when candidates are created")
    axes[1].set_xticks(np.arange(4), labels, fontsize=8)
    axes[1].set_title("Source eligibility and geometric support")
    for ax in axes:
        ax.set_ylim(0, 105)
        ax.set_ylabel("Candidate fraction (%)")
        ax.grid(axis="y", alpha=.25)
        ax.set_axisbelow(True)
        ax.legend()
    fig.suptitle("E0b office0: image-source separation, not statistical independence", fontsize=11)
    folder = RUN / "figures"
    folder.mkdir(exist_ok=True)
    for suffix in ("png", "pdf"):
        fig.savefig(folder / f"availability.{suffix}", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    main()
