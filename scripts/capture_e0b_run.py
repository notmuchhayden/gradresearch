"""Freeze the code and RGB inputs actually used by an E0b run."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    case, dataset, run = sys.argv[1:]
    dataset, run = Path(dataset), Path(run)
    specification = json.loads((ROOT / "configs/e0b_audit.json").read_text())
    all_images = sorted((dataset / "results").glob("frame*.jpg"))
    expected = specification["cases"][case]["original_frame_stop_exclusive"]
    assert len(all_images) == expected, (len(all_images), expected)
    inputs = all_images[::2]
    code = [ROOT / "src/e0_export.py", ROOT / "src/e0b_export.py",
            ROOT / "scripts/run_e0b_audit.sh", ROOT / "scripts/capture_e0b_run.py",
            ROOT / "configs/e0b_audit.json", ROOT / "configs/e0b_replica_office0.yaml"]
    upstream = ROOT / "thirdparty/Splatt3R-SLAM"
    code += [upstream / p for p in ("main.py", "splatt3r_slam/frame.py", "splatt3r_slam/tracker.py",
                                  "splatt3r_slam/splatt3r_utils.py", "splatt3r_slam/dataloader.py", "config/base.yaml")]
    def entry(p):
        return dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size,
                    sha256=hashlib.sha256(p.read_bytes()).hexdigest())
    manifest = dict(case=case, specification=specification, dataset=str(dataset),
                    code=[entry(p) for p in code], inputs=[entry(p) for p in inputs],
                    upstream_commit=subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip(),
                    command=sys.argv, gt_read_by_mapper=False)
    for p in code:
        archived = run / "code" / p.relative_to(ROOT)
        archived.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, archived)
    (run / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
