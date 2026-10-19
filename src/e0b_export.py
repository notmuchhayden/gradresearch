"""Opt-in, process-safe provenance and pose snapshots for the E0b audit.

No admission policy is applied. Ancestry is the conservative image-level union
of all raw pointmap contributions, not per-pixel ancestry or independence.
"""
import fcntl
import json
import os
from pathlib import Path
import time

import torch


def enabled():
    return bool(os.environ.get("E0B_AUDIT_DIR"))


def journal(kind, **payload):
    root = Path(os.environ["E0B_AUDIT_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    # A separate lock serializes writers in the tracker and backend processes.
    with (root / "journal.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        counter = root / "sequence.txt"
        seq = int(counter.read_text()) + 1 if counter.exists() else 1
        record = dict(sequence=seq, kind=kind, monotonic_ns=time.monotonic_ns(),
                      pid=os.getpid(), **payload)
        with (root / "events.jsonl").open("a") as out:
            out.write(json.dumps(record) + "\n")
        counter.write_text(str(seq))
    return record


def pair_created(frame, reference, record):
    stamp = journal("raw_pair", event_id=record["event_id"],
                    source_image_ids=record["source_image_ids"],
                    source_pair_ids=record["source_pair_ids"],
                    input_frame=int(frame.frame_id))
    update = dict(event_id=record["event_id"], images=record["source_image_ids"],
                  pairs=record["source_pair_ids"], sequence=stamp["sequence"])
    frame.e0b_update = dict(update, branch=0)
    reference.e0b_update = dict(update, branch=1)
    if frame is reference:
        frame.e0b_update["branch"] = 0
    frame.e0b_candidate_event = record["event_id"]
    frame.e0b_candidate_sources = record["source_image_ids"]


def merge_lineage(previous, update, first=False):
    old = {} if first else previous or {}
    return {
        "images": sorted(set(old.get("images", [])) | set((update or {}).get("images", []))),
        "pairs": [list(p) for p in sorted(set(map(tuple, old.get("pairs", []))) |
                                           set(map(tuple, (update or {}).get("pairs", []))))],
        "events": sorted(set(old.get("events", [])) |
                         ({update["event_id"]} if update else set())),
        "status": "traced" if update and (first or old.get("status") == "traced") else "unknown",
    }


def pointmap_update(frame, filtering_mode):
    update = getattr(frame, "e0b_update", None)
    first = frame.N == 0
    previous = getattr(frame, "e0b_fused", None)
    lineage = merge_lineage(previous, update, first)
    if filtering_mode != "weighted_pointmap":
        # Only this deployed mode is audited. Never silently certify other modes.
        lineage["status"] = "unknown"
    frame.e0b_fused = lineage
    journal("pointmap_update", target_frame=int(frame.frame_id), first=first,
            filtering_mode=filtering_mode, update=update,
            transform=getattr(frame, "e0b_update_transform", None), fused=lineage)


def shared_write(keyframes, idx, frame):
    previous = dict(keyframes.e0b_metadata[idx])
    fresh = frame.gaussian_pred is not None
    metadata = {
        "frame_id": int(frame.frame_id), "kf_idx": int(idx),
        "candidate_event": getattr(frame, "e0b_candidate_event", None) if fresh else previous.get("candidate_event"),
        "candidate_sources": getattr(frame, "e0b_candidate_sources", []) if fresh else previous.get("candidate_sources", []),
        "fused": getattr(frame, "e0b_fused", {"status": "unknown"}),
    }
    keyframes.e0b_metadata[idx] = metadata
    keyframes.e0b_revision.value += 1
    stamp = journal("keyframe_write", fresh_candidates=fresh, metadata=metadata,
                    pose_revision=keyframes.e0b_revision.value,
                    pose=frame.T_WC.data.detach().cpu().tolist())
    if fresh:
        metadata["created_sequence"] = stamp["sequence"]
        metadata["created_monotonic_ns"] = stamp["monotonic_ns"]
        keyframes.e0b_metadata[idx] = metadata
    else:
        for key in ("created_sequence", "created_monotonic_ns"):
            metadata[key] = previous.get(key)
        keyframes.e0b_metadata[idx] = metadata


def pose_update(keyframes, indices, before):
    keyframes.e0b_revision.value += 1
    ids = indices.detach().cpu().reshape(-1).tolist()
    journal("pose_update", kf_indices=ids, pose_revision=keyframes.e0b_revision.value,
            before=before, after=keyframes.T_WC[indices].detach().cpu().tolist())


def snapshot(keyframes, frame, stage):
    root = Path(os.environ["E0B_AUDIT_DIR"])
    with keyframes.lock:
        n = len(keyframes)
        name = f"input{int(frame.frame_id):06d}_{stage}.pt"
        record = {
            "input_frame": int(frame.frame_id), "stage": stage,
            "pose_revision": keyframes.e0b_revision.value,
            "captured_monotonic_ns": time.monotonic_ns(),
            "poses": keyframes.T_WC[:n].detach().cpu().clone(),
            "metadata": [dict(keyframes.e0b_metadata[i]) for i in range(n)],
            "fused_points": keyframes.X[:n].detach().cpu().clone(),
            "fused_confidence": (keyframes.C[:n] / keyframes.N[:n, None, None]).detach().cpu().clone(),
            "pointmap_updates": keyframes.N_updates[:n].cpu().clone(),
            "image_shape": [keyframes.h, keyframes.w],
        }
        (root / "snapshots").mkdir(parents=True, exist_ok=True)
        torch.save(record, root / "snapshots" / name)
        journal("snapshot", file=f"snapshots/{name}", stage=stage,
                input_frame=int(frame.frame_id), pose_revision=record["pose_revision"],
                keyframes=n)
