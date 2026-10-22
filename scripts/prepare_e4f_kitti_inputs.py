#!/usr/bin/env python3
"""Prepare and seal the pre-registered KITTI Raw E4f diagnostic input."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DRIVE = "2011_09_26_drive_0015_sync"
DATE_ROOT = "2011_09_26"
N = 240
ARCHIVES = ROOT / "data/E4f/archives"
INPUT = ROOT / f"data/E4f/eth3d/{DRIVE}"
EVAL = ROOT / f"data/E4f/evaluation_only/{DRIVE}"
OUT = ROOT / "results/E4f_kitti_geometry_diagnostic" / DRIVE


def digest(path: Path) -> dict:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return {"path": str(path.relative_to(ROOT)), "bytes": path.stat().st_size,
            "sha256": h.hexdigest()}


def parse_calibration(text: str) -> dict[str, np.ndarray]:
    result = {}
    for line in text.splitlines():
        parts = line.split(":", 1)
        if len(parts) != 2:
            continue
        key, values = parts
        try:
            result[key.strip()] = np.asarray([float(x) for x in values.split()])
        except ValueError:
            continue
    return result


def transform(r: np.ndarray, t: np.ndarray) -> np.ndarray:
    T = np.eye(4, dtype=np.float64)
    T[:3, :3] = r.reshape(3, 3)
    T[:3, 3] = t.reshape(3)
    return T


def sha_file_list(paths: list[Path]) -> list[dict]:
    return [digest(p) for p in paths]


def main() -> None:
    drive_zip = ARCHIVES / f"{DRIVE}.zip"
    track_zip = ARCHIVES / "2011_09_26_drive_0015_tracklets.zip"
    calib_zip = ARCHIVES / "2011_09_26_calib.zip"
    for p in (drive_zip, track_zip, calib_zip):
        if not p.is_file():
            raise FileNotFoundError(p)

    source = f"{DATE_ROOT}/{DRIVE}/"
    with ZipFile(drive_zip) as z:
        names = set(z.namelist())
        modalities = {
            "rgb": sorted(n for n in names if n.startswith(source + "image_02/data/") and n.endswith(".png")),
            "lidar": sorted(n for n in names if n.startswith(source + "velodyne_points/data/") and n.endswith(".bin")),
            "oxts": sorted(n for n in names if n.startswith(source + "oxts/data/") and n.endswith(".txt")),
        }
        time_rows = {}
        for modality, subpath in (("rgb", "image_02/timestamps.txt"),
                                  ("lidar", "velodyne_points/timestamps.txt"),
                                  ("oxts", "oxts/timestamps.txt")):
            time_rows[modality] = z.read(source + subpath).decode().splitlines()
        for key in modalities:
            if len(modalities[key]) != len(time_rows[key]) or len(modalities[key]) < N:
                raise RuntimeError(f"{key} has {len(modalities[key])} files / {len(time_rows[key])} timestamps")
        counts = {k: len(v) for k, v in modalities.items()}
        if len(set(counts.values())) != 1:
            raise RuntimeError(f"modality frame counts differ: {counts}")

        ts_ns = {k: np.asarray(time_rows[k], dtype="datetime64[ns]").astype(np.int64) for k in time_rows}
        rgb_ns = ts_ns["rgb"][:N]
        dt_rgb_lidar_ms = np.abs(rgb_ns - ts_ns["lidar"][:N]) / 1e6
        dt_rgb_oxts_ms = np.abs(rgb_ns - ts_ns["oxts"][:N]) / 1e6
        if np.max(dt_rgb_lidar_ms) > 50 or np.max(dt_rgb_oxts_ms) > 50:
            raise RuntimeError("timestamp offset exceeds registered 50 ms limit")

        oxts = np.asarray([[float(x) for x in z.read(n).decode().split()]
                           for n in modalities["oxts"][:N]], dtype=np.float64)
        lat0 = math.radians(oxts[0, 0])
        earth_r = 6378137.0
        xy = np.column_stack((earth_r * math.cos(lat0) * np.radians(oxts[:, 1] - oxts[0, 1]),
                              earth_r * np.radians(oxts[:, 0] - oxts[0, 0])))
        displacement = float(np.linalg.norm(xy[-1] - xy[0]))
        path_length = float(np.linalg.norm(np.diff(xy, axis=0), axis=1).sum())
        if displacement < 30:
            raise RuntimeError(f"horizontal displacement gate failed: {displacement:.3f} m")

        INPUT.mkdir(parents=True, exist_ok=True)
        (INPUT / "images").mkdir(exist_ok=True)
        (EVAL / "lidar").mkdir(parents=True, exist_ok=True)
        (EVAL / "oxts").mkdir(parents=True, exist_ok=True)
        rgb_manifest = []
        for i in range(N):
            rid = f"{i:010d}"
            rgb_rel = Path("images") / f"{rid}.png"
            for modality, dst in (("rgb", INPUT / rgb_rel),
                                  ("lidar", EVAL / "lidar" / f"{rid}.bin"),
                                  ("oxts", EVAL / "oxts" / f"{rid}.txt")):
                if dst.exists():
                    raise FileExistsError(f"preserving existing output: {dst}")
                member = modalities[modality][i]
                dst.write_bytes(z.read(member))
            stamp_sec = (int(rgb_ns[i]) - int(rgb_ns[0])) / 1e9
            rgb_manifest.append({
                "index": i, "rgb_member": modalities["rgb"][i],
                "rgb_relative_path": str(rgb_rel),
                "rgb_timestamp": time_rows["rgb"][i],
                "rgb_seconds_from_start": stamp_sec,
                "lidar_member": modalities["lidar"][i],
                "lidar_timestamp": time_rows["lidar"][i],
                "oxts_member": modalities["oxts"][i],
                "oxts_timestamp": time_rows["oxts"][i],
                "rgb_lidar_offset_ms": float((ts_ns["rgb"][i] - ts_ns["lidar"][i]) / 1e6),
                "rgb_oxts_offset_ms": float((ts_ns["rgb"][i] - ts_ns["oxts"][i]) / 1e6),
                "model_input_rgb": True, "model_input_lidar": False, "model_input_oxts": False,
            })

    calib_dir = EVAL / "calibration"
    calib_dir.mkdir(exist_ok=True)
    with ZipFile(calib_zip) as z:
        for name in ("calib_cam_to_cam.txt", "calib_velo_to_cam.txt", "calib_imu_to_velo.txt"):
            member = f"{DATE_ROOT}/{name}"
            (calib_dir / name).write_bytes(z.read(member))

    with ZipFile(track_zip) as z:
        xml_member = next(n for n in z.namelist() if n.endswith("/tracklet_labels.xml"))
        tracklet_dest = EVAL / "tracklet_labels.xml"
        tracklet_dest.write_bytes(z.read(xml_member))

    cam = parse_calibration((calib_dir / "calib_cam_to_cam.txt").read_text())
    velo = parse_calibration((calib_dir / "calib_velo_to_cam.txt").read_text())
    K = cam["P_rect_02"].reshape(3, 4)[:3, :3]
    Rrect = cam["R_rect_02"].reshape(3, 3)
    T_cam2_cam0 = transform(cam["R_02"], cam["T_02"])
    T_cam0_velo = transform(velo["R"], velo["T"])
    T_cam2rect_velo = np.eye(4)
    T_cam2rect_velo[:3, :3] = Rrect
    T_cam2rect_velo = T_cam2rect_velo @ T_cam2_cam0 @ T_cam0_velo
    first_img = cv2.imread(str(INPUT / "images/0000000000.png"), cv2.IMREAD_COLOR)
    if first_img is None:
        raise RuntimeError("first RGB decode failed")
    h, w = first_img.shape[:2]
    scan = np.fromfile(EVAL / "lidar/0000000000.bin", dtype=np.float32).reshape(-1, 4)
    xyz = scan[:, :3].astype(np.float64)
    xyz_cam = xyz @ T_cam2rect_velo[:3, :3].T + T_cam2rect_velo[:3, 3]
    positive = xyz_cam[:, 2] > 0
    uvw = xyz_cam[positive] @ K.T
    uv = uvw[:, :2] / uvw[:, 2:3]
    inside = ((uv[:, 0] >= 0) & (uv[:, 0] < w) & (uv[:, 1] >= 0) & (uv[:, 1] < h))
    if int(inside.sum()) < 100:
        raise RuntimeError(f"calibration projection has only {int(inside.sum())} in-image points")

    (INPUT / "rgb.txt").write_text("".join(
        f"{row['rgb_seconds_from_start']:.9f} {row['rgb_relative_path']}\n" for row in rgb_manifest))
    (INPUT / "calibration.txt").write_text(" ".join(f"{x:.9f}" for x in [K[0,0],K[1,1],K[0,2],K[1,2]]) + "\n")

    # Decode every selected image now; this is metadata/input validation, before prediction.
    sizes = set()
    for i in range(N):
        im = cv2.imread(str(INPUT / "images" / f"{i:010d}.png"), cv2.IMREAD_COLOR)
        if im is None:
            raise RuntimeError(f"RGB decode failed at {i}")
        sizes.add([im.shape[1], im.shape[0]].__repr__())
    if len(sizes) != 1:
        raise RuntimeError(f"image sizes vary: {sizes}")

    track_text = tracklet_dest.read_text()
    n_tracks = int(re.search(r"<tracklets[^>]*>.*?<count>(\d+)</count>", track_text, re.S).group(1))
    tracklet_frames = [int(x) for x in re.findall(r"<first_frame>(\d+)</first_frame>", track_text)]
    with ZipFile(drive_zip) as z:
        def member_digest(member: str) -> dict:
            info = z.getinfo(member)
            return {"member": member, "bytes": info.file_size}
        candidate_counts = [
            {"drive":"2011_09_26_drive_0005_sync","rgb_lidar_oxts_frames":154,
             "source_archive_downloaded":True,"reason_not_selected":"below 240-frame minimum"},
            {"drive":"2011_09_26_drive_0013_sync","rgb_lidar_oxts_frames":144,
             "source_archive_downloaded":False,"reason_not_selected":"central-directory range preflight below 240-frame minimum"},
            {"drive":DRIVE,"rgb_lidar_oxts_frames":counts["rgb"],
             "source_archive_downloaded":True,"selected":True},
        ]
        manifest = {
            "experiment":"E4f KITTI outdoor geometry consistency diagnostic",
            "selected_drive":DRIVE,
            "selection_order":[x["drive"] for x in candidate_counts],
            "candidate_preflight":candidate_counts,
            "selection_rule":"first candidate with >=240 synchronized RGB/LiDAR/OXTS frames, >=30m first-240 horizontal displacement and all input/data gates passing; selected before model prediction",
            "frame_range_half_open":[0,N],
            "counts_all_drive_frames":counts,
            "selected_frames":N,
            "duration_seconds":float((rgb_ns[N-1]-rgb_ns[0])/1e9),
            "first_240_horizontal_net_displacement_m":displacement,
            "first_240_horizontal_path_length_m":path_length,
            "timestamp_max_abs_offset_ms":{"rgb_lidar":float(dt_rgb_lidar_ms.max()),"rgb_oxts":float(dt_rgb_oxts_ms.max())},
            "timestamp_median_abs_offset_ms":{"rgb_lidar":float(np.median(dt_rgb_lidar_ms)),"rgb_oxts":float(np.median(dt_rgb_oxts_ms))},
            "image_size_wh":list(first_img.shape[1::-1]),
            "lidar_projection_direction":"Velodyne -> camera0 -> camera2 -> rectified camera2",
            "first_scan_projection":{"points_total":int(len(scan)),"positive_camera_z":int(positive.sum()),"positive_z_inside_image":int(inside.sum()),"inside_fraction_of_positive_z":float(inside.sum()/max(positive.sum(),1))},
            "tracklets":{"object_count":n_tracks,"first_frame_min":min(tracklet_frames) if tracklet_frames else None,"tracklet_xml_member":xml_member},
            "model_inputs":{"rgb":"image_02 only","lidar":False,"oxts":False,"tracklets":False},
            "evaluation_only":{"lidar":True,"oxts":True,"tracklets":True,"calibration":True},
            "amendment":"configs/e4f_amendment_A1.json",
            "frames":rgb_manifest,
        }

    (INPUT / "input_manifest.json").write_text(json.dumps({"frames":rgb_manifest},indent=2)+"\n")
    split = {"experiment":"E4f","selected_drive":DRIVE,"selected_range_half_open":[0,N],
             "mapping_rgb_count":N,"heldout_rgb_count":0,"frames":rgb_manifest,
             "evaluation_only_modalities":["velodyne_points","oxts","tracklets","calibration"],
             "amendment":"configs/e4f_amendment_A1.json"}
    (ROOT / "configs/e4f_kitti_input_split.json").write_text(json.dumps(split,indent=2)+"\n")
    (ROOT / "configs/e4f_kitti_selection.json").write_text(json.dumps(manifest,indent=2)+"\n")

    files = [INPUT / "rgb.txt", INPUT / "calibration.txt", tracklet_dest,
             *sorted((INPUT / "images").glob("*.png")),
             *sorted((EVAL / "lidar").glob("*.bin")), *sorted((EVAL / "oxts").glob("*.txt")),
             *sorted(calib_dir.glob("*.txt"))]
    dataset_manifest = {
        "experiment":"E4f KITTI outdoor geometry consistency diagnostic",
        "selected_drive":DRIVE,
        "sources":[
            {**digest(drive_zip),"url":"https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0015/2011_09_26_drive_0015_sync.zip"},
            {**digest(track_zip),"url":"https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_drive_0015/2011_09_26_drive_0015_tracklets.zip"},
            {**digest(calib_zip),"url":"https://s3.eu-central-1.amazonaws.com/avg-kitti/raw_data/2011_09_26_calib.zip"},
        ],
        "selection_manifest":"configs/e4f_kitti_selection.json",
        "input_split":"configs/e4f_kitti_input_split.json",
        "files":sha_file_list(files),
        "preflight":{"rgb_decode_failures":0,"image_sizes":list(first_img.shape[1::-1]),
                     "calibration_projection_first_scan_pass":True},
    }
    (ROOT / "configs/e4f_kitti_dataset_manifest.json").write_text(json.dumps(dataset_manifest,indent=2)+"\n")
    print(json.dumps({"selected_drive":DRIVE,"frames":N,"displacement_m":displacement,
                      "path_length_m":path_length,"max_dt_rgb_lidar_ms":float(dt_rgb_lidar_ms.max()),
                      "max_dt_rgb_oxts_ms":float(dt_rgb_oxts_ms.max()),
                      "projection":manifest["first_scan_projection"],"tracklets":n_tracks,
                      "manifest":"configs/e4f_kitti_dataset_manifest.json"},indent=2))


if __name__ == "__main__":
    main()
