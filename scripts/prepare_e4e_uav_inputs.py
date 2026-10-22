"""Register timestamp-only E4e splits and prepare the HKairport01 dev inputs."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
import re
import shutil
from pathlib import Path
from zipfile import ZipFile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARCHIVES = ROOT / "data/E4e/archives"
SPLIT_PATH = ROOT / "configs/e4e_input_split.json"
SEQUENCES = ["HKairport01", "AMtown01", "AMvalley01"]


def parse_archive(sequence):
    archive = ARCHIVES / f"interval1_{sequence}.zip"
    prefix = f"interval1_{sequence}/"
    with ZipFile(archive) as zf:
        infos = zf.infolist()
        image_map = {}
        lidar_map = {}
        for info in infos:
            name = info.filename
            if name.startswith(prefix + "interval1_CAM/") and name.endswith(".jpg"):
                ts = float(Path(name).stem)
                image_map[ts] = name
            elif name.startswith(prefix + "interval1_LIDAR/") and name.endswith(".txt"):
                match = re.search(r"image(\d+\.\d+)_lidar(\d+\.\d+)", Path(name).stem)
                if match:
                    image_ts, lidar_ts = map(float, match.groups())
                    lidar_map[image_ts] = {"lidar_timestamp": lidar_ts, "member": name,
                                           "size_bytes": info.file_size}
        times = sorted(image_map)
        if not times:
            raise RuntimeError(f"No timestamped camera frames in {archive}")
        t0 = times[0]
        frames = []
        used = set()
        for k in range(300):
            target = t0 + 30.0 + 0.2 * k
            nearest = min(times, key=lambda t: (abs(t-target), t))
            delta = abs(nearest-target)
            if delta > 0.05 + 1e-6:
                raise RuntimeError(f"{sequence}: grid k={k} nearest delta={delta:.6f}s exceeds 0.05s")
            if nearest in used:
                raise RuntimeError(f"{sequence}: duplicate RGB selection at grid k={k}")
            used.add(nearest)
            if nearest not in lidar_map:
                raise RuntimeError(f"{sequence}: no LiDAR point file paired to RGB {nearest}")
            lidar = lidar_map[nearest]
            heldout = (k % 5 == 4)
            frames.append({"grid_index": k, "grid_timestamp": target,
                           "rgb_timestamp": nearest, "rgb_delta_seconds": nearest-target,
                           "rgb_member": image_map[nearest],
                           "lidar_timestamp": lidar["lidar_timestamp"],
                           "camera_lidar_delta_seconds": lidar["lidar_timestamp"]-nearest,
                           "lidar_member": lidar["member"], "lidar_size_bytes": lidar["size_bytes"],
                           "role": "heldout" if heldout else "mapping"})
        return zf, infos, times, frames


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def register_all():
    amendment_window = json.loads((ROOT / "configs/e4e_window_selection_A1.json").read_text())
    window_start = amendment_window["selection"]["start_offset_seconds"]
    scenes = {}
    for sequence in SEQUENCES:
        archive = ARCHIVES / f"interval1_{sequence}.zip"
        with ZipFile(archive) as zf:
            names = zf.namelist()
            camera_times = sorted(float(Path(n).stem) for n in names
                                  if n.startswith(f"interval1_{sequence}/interval1_CAM/") and n.endswith(".jpg"))
            prefix = f"interval1_{sequence}/"
            lidar = {}
            for n in names:
                if n.startswith(prefix + "interval1_LIDAR/") and n.endswith(".txt"):
                    m = re.search(r"image(\d+\.\d+)_lidar(\d+\.\d+)", Path(n).stem)
                    if m:
                        lidar[float(m.group(1))] = (float(m.group(2)), n)
            t0 = camera_times[0]
            frames = []
            selected = set()
            for k in range(300):
                target = t0 + window_start + 0.2*k
                ts = min(camera_times, key=lambda t: (abs(t-target),t))
                if abs(ts-target) > 0.05 + 1e-6 or ts in selected or ts not in lidar:
                    raise RuntimeError(f"Timestamp split failed for {sequence} at grid {k}")
                selected.add(ts)
                lts, lmember = lidar[ts]
                frames.append({"grid_index": k, "grid_timestamp": round(target, 9),
                    "rgb_timestamp": ts, "rgb_delta_seconds": round(ts-target, 9),
                    "rgb_member": f"interval1_{sequence}/interval1_CAM/{ts:.9f}.jpg",
                    "lidar_timestamp": lts, "camera_lidar_delta_seconds": round(lts-ts, 9),
                    "lidar_member": lmember, "role": "heldout" if k%5==4 else "mapping"})
            scenes[sequence] = {"role": "development" if sequence == "HKairport01" else "primary_evaluation",
                "first_rgb_timestamp": t0, "rgb_count_in_archive": len(camera_times),
                "rgb_first": camera_times[0], "rgb_last": camera_times[-1],
                "selected_count": len(frames), "mapping_count": sum(f['role']=='mapping' for f in frames),
                "heldout_count": sum(f['role']=='heldout' for f in frames), "frames": frames}
    output = {"registered_at": datetime.now(timezone.utc).isoformat(),
        "amendment":"A1", "window_start_offset_seconds":window_start,
        "selection": f"timestamp names only; first RGB timestamp is zero; 5Hz [{window_start}s,{window_start+60}s); nearest RGB <=0.05s; no duplicate; earlier timestamp wins ties; grid k mod 5=4 held out",
        "heldout_predictions_or_images_inspected": False,
        "scene_splits": scenes}
    SPLIT_PATH.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n")
    print("registered timestamp splits:", {k:{q:v[q] for q in ('rgb_count_in_archive','selected_count','mapping_count','heldout_count','rgb_first','rgb_last')} for k,v in scenes.items()})


def prepare_dev():
    split = json.loads(SPLIT_PATH.read_text())
    sequence = "HKairport01"
    scene = split["scene_splits"][sequence]
    archive = ARCHIVES / f"interval1_{sequence}.zip"
    map_dir = ROOT / "data/E4e/eth3d/HKairport01"
    rgb_dir = map_dir / "images"
    lidar_dir = ROOT / "data/E4e/evaluation_only/HKairport01/lidar"
    gt_dir = ROOT / "data/E4e/evaluation_only/HKairport01"
    for directory in (rgb_dir, lidar_dir):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    hashes = []
    with ZipFile(archive) as zf:
        for frame in scene["frames"]:
            if frame["role"] == "mapping":
                target = rgb_dir / Path(frame["rgb_member"]).name
                if not target.exists():
                    target.write_bytes(zf.read(frame["rgb_member"]))
                hashes.append({"role":"mapping_rgb", "member":frame["rgb_member"], "sha256":sha256_file(target)})
            lidar_target = lidar_dir / Path(frame["lidar_member"]).name
            if not lidar_target.exists():
                lidar_target.write_bytes(zf.read(frame["lidar_member"]))
            hashes.append({"role":"evaluation_lidar", "member":frame["lidar_member"], "sha256":sha256_file(lidar_target)})
        sampleinfo = f"interval1_{sequence}/sampleinfos_interpolated.json"
        gt_path = gt_dir / "sampleinfos_interpolated.json"
        if not gt_path.exists():
            gt_path.write_bytes(zf.read(sampleinfo))
        hashes.append({"role":"evaluation_pose_calibration", "member":sampleinfo, "sha256":sha256_file(gt_path)})
    rgb_rows = []
    for frame in scene["frames"]:
        if frame["role"] == "mapping":
            rgb_rows.append(f"{frame['rgb_timestamp']:.9f} images/{Path(frame['rgb_member']).name}")
    (map_dir / "rgb.txt").write_text("\n".join(rgb_rows) + "\n")
    # ETH3D loader consumes four pinhole values. Use the official MARS-LVIG
    # camera-LiDAR calibration K; use_calib=false keeps remapping disabled.
    source = (ROOT / "data/E4e/calibration_results.py").read_text()
    assignments = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            try:
                assignments[node.targets[0].id] = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                pass
    calibration_name = {"HKairport01":"HK_GNSS_calibration", "AMtown01":"AMtown_calibration",
                        "AMvalley01":"AMvalley_calibration"}[sequence]
    camera_calibration = assignments[calibration_name]
    K = camera_calibration["camera_intrinsic"]
    calibration = [K[0], K[4], K[2], K[5]]
    (map_dir / "calibration.txt").write_text(" ".join(map(str, calibration)) + "\n")
    result = {"sequence":sequence,"mapping_rgb_count":len(rgb_rows),"heldout_rgb_extracted":False,
        "evaluation_lidar_count":len(scene["frames"]),"calibration_pinhole_from_sampleinfo":calibration,
        "camera_lidar_calibration":camera_calibration,
        "calibration_source_sha256":sha256_file(ROOT/"data/E4e/calibration_results.py"),
        "calibration_role":"official camera K to loader; distortion remap disabled; extrinsic direction tested in development; reference pose and LiDAR isolated from model input",
        "files":hashes}
    out=ROOT/"results/E4e_uav_dataset_pilot/development/HKairport01/input_manifest.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
    print("prepared HKairport01 mapping input",len(rgb_rows),"RGB;",len(scene['frames']),"LiDAR references; heldout RGB not extracted")


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=["register","prepare-dev"])
    args=parser.parse_args()
    if args.stage=="register": register_all()
    else: prepare_dev()
