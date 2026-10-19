"""Opt-in E0 exports; no model, pose or admission decisions are changed."""
import json
import os
from pathlib import Path
import time

import torch


def dump_pair(frame, reference, outputs):
    root = Path(os.environ["E0_EXPORT_DIR"])
    event = f"{os.getpid()}_{time.time_ns()}"
    source = [int(frame.frame_id), int(reference.frame_id)]
    record = {
        "event_id": event,
        "source_image_ids": sorted(set(source)),
        "source_pair_ids": [source],
        "anchor_frame_id": source[0],
        "created_at_input_frame": source[0],
        "coordinate_frame": "first_source_camera",
        "model_id": "brandonsmart/splatt3r_v1.0",
        "outputs": [{k: v.detach().cpu().clone() for k, v in output.items()
                     if k in {"pts3d", "conf", "means", "scales", "rotations", "sh", "opacities"}}
                    for output in outputs],
    }
    (root / "raw_pairs").mkdir(parents=True, exist_ok=True)
    torch.save(record, root / "raw_pairs" / f"{event}.pt")
    frame.e0_prediction_event = event
    if os.environ.get("E0B_AUDIT_DIR"):
        from e0b_export import pair_created
        pair_created(frame, reference, record)


def record_keyframe(index, frame):
    root = Path(os.environ["E0_EXPORT_DIR"])
    (root / "candidate_sources").mkdir(parents=True, exist_ok=True)
    event = getattr(frame, "e0_prediction_event", None)
    record = {
        "anchor_kf": int(index), "frame_id": int(frame.frame_id),
        "prediction_event_id": event,
        "candidate_id_format": "<prediction_event_id>:self:<row-major-pixel-index>",
        "gaussian_coordinate_frame": "anchor_camera",
        "pose_at_insertion": frame.T_WC.data.detach().cpu().tolist(),
        "fused_ancestry_status": "unknown",
        "pose_revision": "insertion_snapshot_unversioned",
    }
    # One file per event also preserves transient keyframes later removed by SLAM.
    (root / "candidate_sources" / f"kf{int(index):04d}_{event}.json").write_text(
        json.dumps(record, indent=2) + "\n")
