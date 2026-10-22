#!/usr/bin/env python3
"""Register E4f A2's fixed 5 Hz RGB input subset before its prediction run."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
selection=json.loads((ROOT/'configs/e4f_kitti_selection.json').read_text())
rows=selection['frames']
if len(rows)!=240:
    raise RuntimeError(f'expected original 240-frame sealed interval, got {len(rows)}')
for r in rows:
    r['model_input_rgb']=(r['index']%2==0)
    r['model_input_lidar']=False
    r['model_input_oxts']=False
    r['model_input_tracklets']=False
split={
 'experiment':'E4f KITTI outdoor geometry consistency diagnostic',
 'amendment':'configs/e4f_amendment_A2.json',
 'selected_drive':selection['selected_drive'],
 'selected_range_half_open':[0,240],
 'mapping_rgb_count':120,
 'rgb_sample_stride':2,
 'model_input_rate_hz_approx':5,
 'evaluation_rgb_count':240,
 'heldout_rgb_count':0,
 'frames':rows,
 'evaluation_only_modalities':['velodyne_points','oxts','tracklets','calibration'],
}
(ROOT/'configs/e4f_kitti_input_split.json').write_text(json.dumps(split,indent=2)+'\n')
spec=json.loads((ROOT/'configs/e4f_kitti_geometry_diagnostic.json').read_text())
spec['amendment_A2']='configs/e4f_amendment_A2.json'
spec['mapping']['rgb_frames']=120
spec['mapping']['rgb_sample_stride']=2
spec['mapping']['approximate_input_rate_hz']=5
spec['native_filter']['keyframe_buffer']=128
spec['failed_attempt_10hz_manifest']='results/E4f_kitti_geometry_diagnostic/2011_09_26_drive_0015_sync/baseline/run_manifest.json'
(ROOT/'configs/e4f_kitti_geometry_diagnostic.json').write_text(json.dumps(spec,indent=2)+'\n')
yaml=(ROOT/'configs/e4f_kitti_b1.yaml').read_text().replace('  subsample: 1','  subsample: 2')
(ROOT/'configs/e4f_kitti_b1.yaml').write_text(yaml)
print(json.dumps({'registered':'A2','rgb_input_count':120,'sample_stride':2,'keyframe_buffer':128},indent=2))
