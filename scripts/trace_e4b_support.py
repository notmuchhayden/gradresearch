"""Publish deterministic strict-support traces, separate from random plot samples."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/E4b_reference_plane_audit'
sys.path[:0]=[str(OUT/'deps'),str(ROOT/'scripts')]
import numpy as np
import pyarrow.dataset as ds
from prepare_e2b_run import digest,save_json


def main():
    registration=json.loads((ROOT/'configs/e4b_trace_registration.json').read_text())
    assert digest(Path(__file__))==registration['code']
    reg=json.loads((ROOT/'configs/e4b_protocol_registration.json').read_text())
    result={}
    for scene in reg['scene_sources']:
        directory=OUT/scene;flags=np.load(directory/'candidate_flags.npz')
        ids=np.flatnonzero(flags['shared_wrong_support'])[:5]
        columns=['candidate_id','snapshot','input_frame','pose_revision','candidate_kf','evidence_kf',
                 'evidence_pixel','label','cohort','plane_score','depth_score','GT_front',
                 'GT_correspondence','plane_offset_m','plane_angle_degrees','coherent_wrong',
                 'oracle_plane_score','shared_wrong_support']
        rows=[]
        if len(ids):
            table=ds.dataset(directory/'view_audit.parquet',format='parquet').to_table(columns=columns,
                filter=ds.field('candidate_id').isin(ids.tolist())&ds.field('shared_wrong_support'))
            table=table.sort_by([('candidate_id','ascending'),('snapshot','ascending'),('evidence_kf','ascending')])
            seen=set()
            for row in table.to_pylist():
                if row['candidate_id'] in seen:continue
                seen.add(row['candidate_id']);rows.append(row)
        result[scene]=dict(selection='Lowest five strict-support candidate IDs; first qualifying snapshot then evidence KF. These are criterion traces, not replacements for the fixed random plots.',rows=rows)
        save_json(directory/'strict_support_examples.json',result[scene])
    save_json(OUT/'strict_support_examples.json',result)
    save_json(ROOT/'configs/e4b_strict_support_examples.json',result)
    print(json.dumps({s:len(r['rows']) for s,r in result.items()}))


if __name__=='__main__':main()
