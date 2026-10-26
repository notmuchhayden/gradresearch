"""Frozen case definitions shared by A1-G and A1-M, with prior-cache adapters."""
from pathlib import Path
import json
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from a1_c_common import load_views,reference_poses,source_camera,stats,ARMS
from prepare_e2b_run import digest,save_json

SPECS={'G':ROOT/'configs/a1_g_gauge_sensitivity.json','M':ROOT/'configs/a1_m_support_sensitivity.json'}


def context(experiment):
    spec=json.loads(SPECS[experiment].read_text());c=json.loads((ROOT/spec['C_spec']).read_text());u=json.loads((ROOT/spec['U_spec']).read_text())
    return spec,ROOT/spec['output'],c,u


def cases(experiment):
    spec,_,c,_=context(experiment);result={}
    bases=spec['cases'] if experiment=='G' else spec['inherited_scopes']
    for base in bases:
        definitions=['position','orientation'] if experiment=='G' else ['position']
        for gauge in definitions:
            key=f'{base}_{gauge}' if experiment=='G' else base
            result[key]=dict(base=base,scene=c['cases'][base]['scene'],kind='strict',gauge=gauge,reuse=gauge=='position',
                expected_candidates=c['cases'][base]['expected_candidates'],target_pattern=None)
    if experiment=='M':
        for key in spec['full_mixed']:
            scene='office2' if key.startswith('office2') else 'HKairport01';base='office2_strict' if scene=='office2' else ('HKairport01_common' if key.endswith('common') else 'HKairport01_wide')
            result[key]=dict(base=base,scene=scene,kind='full_mixed',gauge='position',reuse=False,expected_candidates=1545979 if scene=='office2' else 3242219,target_pattern=None)
        for mode in ['source','target']:
            for pattern in spec['sparsification']['patterns']:
                for density in spec['sparsification']['densities']:
                    key=f'office2_{mode}_{pattern}_{int(density*100):02d}pct'
                    result[key]=dict(base='office2_strict',scene='office2',kind=mode+'_only',gauge='position',reuse=mode=='target',
                        density=density,pattern=pattern,target_pattern=pattern if mode=='target' else None)
    return result


def prior_map(base,arm):
    spec,_,_,_=context('G');p=ROOT/spec['A1_C']/'oracles'/base/'manifest.json';m=json.loads(p.read_text());return next(v for v in m['variants'] if v['id']==arm)


def prior_metric(base,arm):
    spec,_,_,_=context('G');p=ROOT/spec['A1_C']/'evaluation'/base/arm/'metrics.json';return json.loads(p.read_text())


def get_views(scene,cache):
    if scene not in cache:
        _,_,c,_=context('G');base='office2_strict' if scene=='office2' else 'HKairport01_wide';cache[scene]=load_views(c['cases'][base])[0]
    return cache[scene]
