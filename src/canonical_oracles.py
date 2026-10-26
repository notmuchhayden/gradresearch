"""Canonical local x rigid-pose interventions, independent of scale allocation."""
import numpy as np
from pointmap_contract import sim3_parts,transform_points,transform_covariance,array_hash


def build_canonical_arms(effective, reference, covariance_y, estimated_Q, reference_Q, candidate_ids, attributes):
    effective=np.asarray(effective,np.float64);reference=np.asarray(reference,np.float64);covariance_y=np.asarray(covariance_y,np.float64)
    n=len(effective)
    if effective.shape!=(n,3) or reference.shape!=(n,3) or covariance_y.shape!=(n,3,3):
        raise ValueError('Canonical geometry shapes differ')
    if not all(np.isfinite(x).all() for x in [effective,reference,covariance_y]):
        raise ValueError('Nonfinite canonical geometry')
    if np.any(effective[:,2]<=0) or np.any(reference[:,2]<=0):
        raise ValueError('Source camera Z must be positive')
    ids=np.asarray(candidate_ids)
    if ids.shape!=(n,) or len(np.unique(ids))!=n or any(len(v)!=n for v in attributes.values()):
        raise ValueError('Invalid frozen candidate registry or attributes')
    for pose in [estimated_Q,reference_Q]:
        if not np.isclose(sim3_parts(pose)[0],1.,atol=1e-10,rtol=0):
            raise ValueError('Canonical pose intervention must be rigid')
    ray_z=effective/effective[:,2:3]*reference[:,2:3]
    result={}
    for name,points,pose in [('C00',effective,estimated_Q),('C10',reference,estimated_Q),
        ('C01',effective,reference_Q),('C11',reference,reference_Q),('CZ10',ray_z,estimated_Q),('CZ11',ray_z,reference_Q)]:
        result[name]=dict(local=points.copy(),local_covariance=covariance_y.copy(),placement=np.array(pose,copy=True),
            world_points=transform_points(points,pose),world_covariance=transform_covariance(covariance_y,pose),
            candidate_ids=ids.copy(),attributes={k:np.array(v,copy=True) for k,v in attributes.items()})
    validate_canonical_arms(result)
    return result


def validate_canonical_arms(arms):
    if set(arms)!={'C00','C10','C01','C11','CZ10','CZ11'}:raise ValueError('Six canonical arms required')
    first=arms['C00']
    for name,arm in arms.items():
        for key in ['candidate_ids','local_covariance']:
            if array_hash(arm[key])!=array_hash(first[key]):raise ValueError(name+': changed '+key)
        if set(arm['attributes'])!=set(first['attributes']):raise ValueError('Attribute keys differ')
        for key in first['attributes']:
            if array_hash(arm['attributes'][key])!=array_hash(first['attributes'][key]):raise ValueError('Attributes changed')
        if not np.isclose(sim3_parts(arm['placement'])[0],1.,atol=1e-10,rtol=0):raise ValueError('Nonrigid placement')
        np.testing.assert_allclose(arm['world_points'],transform_points(arm['local'],arm['placement']),atol=1e-10,rtol=1e-9)
        np.testing.assert_allclose(arm['world_covariance'],transform_covariance(arm['local_covariance'],arm['placement']),atol=1e-10,rtol=1e-9)
    for a,b,field in [('C00','C01','local'),('C10','C11','local'),('CZ10','CZ11','local'),
                       ('C00','C10','placement'),('C00','CZ10','placement'),('C01','C11','placement'),('C01','CZ11','placement')]:
        if array_hash(arms[a][field])!=array_hash(arms[b][field]):raise ValueError('Non-independent '+field)
    for z in ['CZ10','CZ11']:
        np.testing.assert_allclose(arms[z]['local']/arms[z]['local'][:,2:3],first['local']/first['local'][:,2:3],atol=1e-10,rtol=1e-9)
        np.testing.assert_array_equal(arms[z]['local'][:,2],arms['C10']['local'][:,2])


def support_gate(rows,min_pixels,min_fraction,min_views):
    if not rows:raise ValueError('Registered views required')
    passed=[r['common_pixels']>=min_pixels and r['reference_pixels']>0 and r['common_pixels']/r['reference_pixels']>=min_fraction for r in rows]
    return dict(passed=sum(passed)/len(rows)>=min_views,qualifying_views=sum(passed),registered_views=len(rows),
                fraction=sum(passed)/len(rows),minimum_view_fraction=min_views,min_pixels=min_pixels,min_reference_fraction=min_fraction)
