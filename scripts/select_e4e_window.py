"""Apply preregistered A1 selection using HKairport01 timestamp/RTK metadata only."""
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "data/E4e/archives/interval1_HKairport01.zip"
AMENDMENT = json.loads((ROOT / "configs/e4e_window_amendment_A1.json").read_text())
OUT = ROOT / "configs/e4e_window_selection_A1.json"


def main():
    with ZipFile(ARCHIVE) as zf:
        root = "interval1_HKairport01/"
        times = sorted(float(Path(n).stem) for n in zf.namelist()
                       if n.startswith(root + "interval1_CAM/") and n.endswith(".jpg"))
        rows = list(csv.DictReader(io.StringIO(zf.read(root + "rtk_positions_raw.csv").decode("utf-8"))))
    rgb0 = times[0]
    rtk_t = np.asarray([float(r["headerstamp"]) for r in rows])
    rtk_xy = np.asarray([[float(r["easting"]), float(r["northing"])] for r in rows])
    duration = times[-1] - rgb0
    chosen = None
    for start in np.arange(0.0, duration - 60.0 + 1e-9, 20.0):
        grid_t = rgb0 + start + 0.2*np.arange(301)
        idx = np.searchsorted(rtk_t, grid_t)
        idx = np.clip(idx, 1, len(rtk_t)-1)
        earlier = idx-1
        use_earlier = np.abs(rtk_t[earlier]-grid_t) <= np.abs(rtk_t[idx]-grid_t)
        idx[use_earlier] = earlier[use_earlier]
        xy = rtk_xy[idx]
        speed = np.linalg.norm(np.diff(xy, axis=0), axis=1)/np.diff(rtk_t[idx])
        mapping = np.arange(300) % 5 != 4
        cruise = speed[:300][mapping] >= 1.0
        pair_distance = np.linalg.norm(xy[:, None, :] - xy[None, :, :], axis=2)
        movement = float(pair_distance.max())
        record = {"start_offset_seconds": float(start), "end_offset_seconds": float(start+60),
                  "mapping_count": int(mapping.sum()), "cruise_threshold_mps": 1.0,
                  "mapping_cruise_fraction": float(cruise.mean()),
                  "horizontal_max_pairwise_displacement_m": movement,
                  "rtk_nearest_time_error_p95_seconds": float(np.percentile(np.abs(rtk_t[idx]-grid_t),95)),
                  "rgb0_timestamp": rgb0}
        if record["mapping_cruise_fraction"] >= 0.80 and movement >= 30.0:
            chosen = record
            break
    if chosen is None:
        raise SystemExit("No 60-second HKairport01 window met the registered A1 gates")
    OUT.write_text(json.dumps({"amendment":"A1", "selected_by":"scripts/select_e4e_window.py",
        "registered_rule":AMENDMENT["window_selection"], "selection":chosen,
        "sequence_transfer":"Apply this same relative window to AMtown01 and AMvalley01; metadata gates only, no window reselection.",
        "selected_at":datetime.now(timezone.utc).isoformat(), "prediction_or_error_image_used":False},
        indent=2, ensure_ascii=False)+"\n")
    print(json.dumps(chosen, indent=2))


if __name__ == "__main__":
    main()
