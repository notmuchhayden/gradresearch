"""Check the fixed A1 time window using RTK metadata only, before predictions."""
import csv
import io
import json
from pathlib import Path
from zipfile import ZipFile

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
SPLIT=json.loads((ROOT/"configs/e4e_input_split.json").read_text())
WINDOW=SPLIT["window_start_offset_seconds"]
SEQUENCES=["HKairport01","AMtown01","AMvalley01"]

def check(sequence):
    archive=ROOT/f"data/E4e/archives/interval1_{sequence}.zip"
    with ZipFile(archive) as zf:
        root=f"interval1_{sequence}/"
        rows=list(csv.DictReader(io.StringIO(zf.read(root+"rtk_positions_raw.csv").decode("utf-8"))))
    rtk_t=np.asarray([float(r["headerstamp"]) for r in rows])
    rtk_xy=np.asarray([[float(r["easting"]),float(r["northing"])] for r in rows])
    rgb0=SPLIT["scene_splits"][sequence]["first_rgb_timestamp"]
    grid_t=rgb0+WINDOW+0.2*np.arange(301)
    idx=np.searchsorted(rtk_t,grid_t);idx=np.clip(idx,1,len(rtk_t)-1)
    earlier=idx-1
    use_earlier=np.abs(rtk_t[earlier]-grid_t)<=np.abs(rtk_t[idx]-grid_t)
    idx[use_earlier]=earlier[use_earlier]
    xy=rtk_xy[idx]
    speed=np.linalg.norm(np.diff(xy,axis=0),axis=1)/np.diff(rtk_t[idx])
    mapping=np.arange(300)%5!=4
    movement=float(np.linalg.norm(xy[:,None,:]-xy[None,:,:],axis=2).max())
    time_error=np.abs(rtk_t[idx]-grid_t)
    return {"sequence":sequence,"role":SPLIT["scene_splits"][sequence]["role"],
       "window_offset_seconds":[WINDOW,WINDOW+60],"rtk_speed_threshold_mps":1.0,
       "mapping_cruise_fraction":float(np.mean(speed[:300][mapping]>=1.0)),
       "horizontal_max_pairwise_displacement_m":movement,
       "rtk_nearest_time_error_p95_seconds":float(np.percentile(time_error,95)),
       "rtk_nearest_time_error_max_seconds":float(time_error.max()),
       "representative_gate_pass":bool(np.mean(speed[:300][mapping]>=1.0)>=.8 and movement>=30),
       "prediction_or_image_pixels_used":False}

if __name__=="__main__":
    results=[check(s) for s in SEQUENCES]
    out=ROOT/"results/E4e_uav_dataset_pilot/representativeness.json"
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(results,indent=2,ensure_ascii=False)+"\n")
    print(json.dumps(results,indent=2,ensure_ascii=False))
