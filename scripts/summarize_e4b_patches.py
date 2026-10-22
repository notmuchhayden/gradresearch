"""Supplement E4b's snapshot-patch tables with distinct raw-source-patch counts."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/E4b_reference_plane_audit'
sys.path[:0]=[str(OUT/'deps'),str(ROOT/'scripts')]
import numpy as np
import pyarrow.parquet as pq
from prepare_e2b_run import digest,save_json


def summarize(scene,paths):
    meta=json.loads((ROOT/paths['scores']/'score_metadata.json').read_text())
    n,nk=meta['raw_per_kf'],meta['keyframes'];N=n*nk
    metrics=['shared_referenced','GT_auditable','reference_wrong','coherent_wrong','all_points_wrong']
    flags={k:np.zeros(N,bool) for k in metrics}
    groups={k:np.zeros(N,np.uint16) for k in metrics}
    columns=['evidence_kf','pixel','shared_references','gt_reliable','wrong_5_10',
             'coherent_front','coherent_behind','all_points_wrong','cohort_group_bits']
    for batch in pq.ParquetFile(OUT/scene/'patch_audit.parquet').iter_batches(columns=columns):
        a={key:batch.column(key).to_numpy(zero_copy_only=False) for key in columns}
        ids=a['evidence_kf'].astype(np.int64)*n+a['pixel']
        shared=a['shared_references']>0;aud=shared&a['gt_reliable']
        masks=[shared,aud,aud&a['wrong_5_10'],aud&(a['coherent_front']|a['coherent_behind']),aud&a['all_points_wrong']]
        for key,mask in zip(metrics,masks):
            flags[key][ids[mask]]=True
            np.bitwise_or.at(groups[key],ids[mask],a['cohort_group_bits'][mask])
    result=dict(scene=scene,unit='distinct raw (evidence event, self branch 0, pixel) across all decision snapshots',
        aggregation='A source patch qualifies if the condition holds in at least one snapshot; each condition and cohort association is accumulated at the same snapshot.',
        counts={key:int(mask.sum()) for key,mask in flags.items()},
        group_counts={key:[int(((bits&(1<<g))!=0).sum()) for g in range(12)] for key,bits in groups.items()},
        group_order='unknown, normal, bad; within each: both_miss, b6_only, both_reject, plane_only',
        source=digest(OUT/scene/'patch_audit.parquet'))
    save_json(OUT/scene/'source_patch_summary.json',result)
    return result


def main():
    reg=json.loads((ROOT/'configs/e4b_protocol_registration.json').read_text())
    notes=json.loads((ROOT/'configs/e4b_execution_notes.json').read_text())
    assert digest(Path(__file__))==notes['supplemental_code']
    # Same raw patch in two snapshots must count once, not twice.
    trial=np.zeros(2,np.uint16);np.bitwise_or.at(trial,[0,0],np.array([1,2],np.uint16))
    assert int((trial!=0).sum())==1 and trial[0]==3
    data={scene:summarize(scene,paths) for scene,paths in reg['scene_sources'].items()}
    save_json(OUT/'source_patch_summary.json',data)
    save_json(ROOT/'configs/e4b_source_patch_summary.json',data)
    print(json.dumps({s:r['counts'] for s,r in data.items()},indent=2))


if __name__=='__main__':main()
