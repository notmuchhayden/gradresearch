"""E3b fresh-scene features: copied E2b equations, unchanged eligibility and masks."""
import argparse
import builtins
from contextlib import contextmanager
import io
import inspect
import json
from pathlib import Path
import shutil
import sys
import time

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts'), str(ROOT / 'thirdparty/Splatt3R-SLAM/splatt3r_core')]
from prepare_e2b_run import digest, save_json
from score_e2 import forbid_gt_reads
from e0b_audit import sim3_matrix, transform
from e2_signals import causal_pair, cross_pair, prepare_observation, image_rgb, original_active, match_rays, fit_camera, median_views
from e2b_transfer import repeat_score, temporal_max
from utils.geometry import build_covariance


@contextmanager
def forbid_e2b_gt_reads():
    with forbid_gt_reads():
        original, original_io = builtins.open, io.open
        def checked(file, *args, **kwargs):
            if isinstance(file, (str, Path)):
                path = Path(file)
                if ('evaluation' in path.parts or path.name.endswith('_frames.txt') or
                        path.name in {'labels.npz', 'thresholds_development_only.json'}):
                    raise RuntimeError(f'E2b GT/trajectory/calibration feature read forbidden: {path}')
            return original(file, *args, **kwargs)
        builtins.open = io.open = checked
        try:
            yield
        finally:
            builtins.open, io.open = original, original_io


def load_scene(scene, spec):
    run = ROOT / spec['output'] / 'baselines' / scene
    dump_path = run / 'map' / f'{scene}_kfgauss.pt'
    dump = torch.load(dump_path, map_location='cpu', weights_only=True)
    fields = ('kf_idx', 'frame_id', 'img', 'img_shape', 'means', 'scales', 'rotations', 'opacities', 'conf')
    kfs = [{k: row[k] for k in fields} for row in dump['keyframes']]
    del dump
    events_path = run / 'audit/events.jsonl'
    events = [json.loads(line) for line in events_path.read_text().splitlines()]
    assert not any(e['kind'] == 'keyframe_pop' for e in events), 'KF slot reuse needs an explicit event replay'
    assert [e['sequence'] for e in events] == list(range(1, len(events) + 1))
    decisions = [e for e in events if e['kind'] == 'snapshot' and e['stage'] == 'decision']
    assert len(kfs) == len(decisions)
    return run, kfs, events, decisions, [dump_path, events_path, run / 'run_manifest.json']


def main(scene):
    started = time.monotonic()
    torch.set_num_threads(2)
    cfg = ROOT / 'configs/e3b_provisional.json'
    spec = json.loads(cfg.read_text())
    spec = dict(spec, output=spec['fresh_source'], methods=json.loads((ROOT/'configs/e2b_observation_transfer.json').read_text())['methods'])
    base_path = ROOT / spec['feature_base_config']
    base = json.loads(base_path.read_text())
    out = ROOT / spec['output'] / 'scores' / scene
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'score_manifest.json').exists():
        raise RuntimeError('Existing completed scores are preserved; use a fresh output')
    run, kfs, events, decisions, inputs = load_scene(scene, spec)
    inputs += [cfg, base_path, ROOT/'configs/e2b_observation_transfer.json']
    raw_events = {e['event_id']: e for e in events if e['kind'] == 'raw_pair'}
    observations, covariances, lineage, cameras = [], [], [], []
    for i, (kf, decision) in enumerate(zip(kfs, decisions)):
        snapshot_path = run / 'audit' / decision['file']
        snap = torch.load(snapshot_path, map_location='cpu', weights_only=True)
        assert len(snap['metadata']) == i + 1 and snap['pose_revision'] == decision['pose_revision']
        meta = snap['metadata'][i]
        assert kf['frame_id'] == meta['frame_id']
        path = run / 'exports/raw_pairs' / f"{meta['candidate_event']}.pt"
        raw = torch.load(path, map_location='cpu', weights_only=True)
        assert raw['source_image_ids'] == meta['candidate_sources']
        assert meta['candidate_sources'] and max(meta['candidate_sources']) <= kf['frame_id']
        assert torch.equal(raw['outputs'][0]['means'].reshape(-1, 3), kf['means'])
        assert raw_events[meta['candidate_event']]['sequence'] < decision['sequence']
        obs = prepare_observation(raw['outputs'][0], image_rgb(kf), base)
        observations.append(obs)
        q = kf['rotations'] / kf['rotations'].norm(dim=-1, keepdim=True).clamp_min(1e-6)
        covariances.append(build_covariance(kf['scales'], q).numpy())
        K, _, camera = fit_camera(obs['points'], obs['confidence'], obs['hw'], base)
        cameras.append(dict(K=K.tolist(), **camera))
        lineage.append(dict(anchor_kf=i, input_frame=kf['frame_id'], original_frame=2 * kf['frame_id'],
            event_id=meta['candidate_event'], source_images=meta['candidate_sources'],
            raw_sequence=raw_events[meta['candidate_event']]['sequence'],
            decision_sequence=decision['sequence'], decision_file=decision['file'],
            pose_revision=decision['pose_revision']))
        inputs += [path, snapshot_path]
        del raw, snap
    nk, n = len(kfs), len(kfs[0]['means'])
    methods = [m for m in spec['methods'] if not m.startswith('B8')]
    totals = {m: np.full((nk, n), np.nan, np.float32) for m in methods}
    creation = {m: np.full((nk, n), np.nan, np.float32) for m in methods}
    first_repeat = np.full((nk, n), -1, np.int32)
    first_single = np.full((nk, n), -1, np.int32)
    creation_count = np.zeros((nk, n), np.uint16)
    repeat_ever = np.zeros((nk, n), bool)
    creation_poses = np.zeros((nk, 4, 4))
    pair_rows, snapshot_rows = [], []
    history = out / 'history'
    history.mkdir(exist_ok=True)
    for index, event in enumerate(decisions):
        snap = torch.load(run / 'audit' / event['file'], map_location='cpu', weights_only=True)
        count = len(snap['metadata'])
        poses = [sim3_matrix(p.numpy()) for p in snap['poses']]
        snapshot = {m: np.full((count, n), np.nan, np.float32) for m in methods}
        support_counts = np.zeros((count, n), np.uint16)
        for i in range(count):
            views = dict(B6_depth_front=[], B7_rgb_ncc_region=[], P1_median_1view=[])
            relative_planes = []
            means = kfs[i]['means'].numpy().astype(float)
            assert snap['metadata'][i]['candidate_event'] == lineage[i]['event_id']
            assert snap['metadata'][i]['candidate_sources'] == lineage[i]['source_images']
            for j in range(count):
                if i == j:
                    continue
                assert snap['metadata'][j]['candidate_event'] == lineage[j]['event_id']
                assert snap['metadata'][j]['candidate_sources'] == lineage[j]['source_images']
                assert max(lineage[j]['source_images']) <= snap['input_frame']
                eligible = causal_pair(lineage[i]['source_images'], lineage[j]['source_images'],
                                       event['sequence'], lineage[j]['raw_sequence'])
                if not eligible:
                    continue
                scores, stats = cross_pair(means, covariances[i], observations[i], observations[j], poses[i], poses[j], base)
                views['B6_depth_front'].append(scores['B6_depth_front'])
                views['B7_rgb_ncc_region'].append(scores['B7_rgb_ncc_region'])
                plane = scores['P1_plane_front_1view']
                views['P1_median_1view'].append(plane)
                p = transform(means, np.linalg.inv(poses[j]) @ poses[i])
                ids, _, _, _ = match_rays(p, observations[j], base['ray_angle_max_degrees'])
                relative_planes.append(plane * observations[j]['spacing'][ids] / observations[j]['radius'][ids])
                pair_rows.append(dict(snapshot=index, decision_sequence=event['sequence'],
                    pose_revision=snap['pose_revision'], candidate_kf=i, evidence_kf=j,
                    source_disjoint=True, shared_candidate_images=[],
                    evidence_raw_sequence=lineage[j]['raw_sequence'], **stats))
            for method, per_view in views.items():
                snapshot[method][i], _ = median_views(per_view, n)
            for norm, values in (('spacing', views['P1_median_1view']), ('relative', relative_planes)):
                for veto in (True, False):
                    method = f'P1_second_front_{norm}' + ('' if veto else '_no_veto')
                    score, plane_count, supports = repeat_score(values, n, veto=veto)
                    snapshot[method][i] = score
            support_counts[i] = plane_count
            snapshot['B2_confidence'][i] = -kfs[i]['conf'].numpy()
            single = (plane_count >= 1) & (first_single[i] < 0)
            repeat = (plane_count >= 2) & (first_repeat[i] < 0)
            first_single[i, single] = snap['input_frame']
            first_repeat[i, repeat] = snap['input_frame']
            repeat_ever[i] |= plane_count >= 2
            for m, values in snapshot.items():
                totals[m][i] = temporal_max(totals[m][i], values[i])
                if i == count - 1:
                    creation[m][i] = values[i]
            if i == count - 1:
                creation_poses[i] = poses[i]
                creation_count[i] = plane_count
            snapshot_rows.append(dict(snapshot=index, candidate_kf=i, input_frame=snap['input_frame'],
                decision_sequence=event['sequence'], pose_revision=snap['pose_revision'],
                plane_1plus=int((plane_count >= 1).sum()), plane_2plus=int((plane_count >= 2).sum()),
                score_2plus_without_veto=int(np.isfinite(snapshot['P1_second_front_spacing_no_veto'][i]).sum()),
                score_2plus_with_veto=int(np.isfinite(snapshot['P1_second_front_spacing'][i]).sum())))
        np.savez_compressed(history / f'snapshot{index:04d}.npz', **snapshot,
                            support_count=support_counts, input_frame=snap['input_frame'],
                            pose_revision=snap['pose_revision'], decision_sequence=event['sequence'])
        print(f'{scene}: snapshot {index + 1}/{nk}, input={snap["input_frame"]}, repeated={int(repeat_ever.sum())}', flush=True)
    arrays = {f'max__{m}': a.reshape(-1) for m, a in totals.items()}
    arrays.update({f'creation__{m}': a.reshape(-1) for m, a in creation.items()})
    arrays.update(active=np.concatenate([original_active(kf) for kf in kfs]),
        anchor_kf=np.repeat(np.arange(nk, dtype=np.int32), n), pixel_index=np.tile(np.arange(n), nk),
        first_repeat=first_repeat.reshape(-1), first_single=first_single.reshape(-1),
        creation_count=creation_count.reshape(-1), repeat_ever=repeat_ever.reshape(-1), creation_poses=creation_poses)
    np.savez_compressed(out / 'features.npz', **arrays)
    save_json(out / 'score_metadata.json', dict(scene=scene, candidate_count=nk*n, keyframes=nk,
        raw_per_kf=n, active=int(arrays['active'].sum()), lineage=lineage, predicted_cameras=cameras,
        evidence_pair_overlap=[dict(a=i,b=j,shared_images=sorted(set(lineage[i]['source_images']) &
            set(lineage[j]['source_images']))) for i in range(nk) for j in range(i+1,nk)],
        snapshots=snapshot_rows, snapshot_count=nk, cpu_seconds=time.monotonic()-started,
        repeated_creation=int((creation_count>=2).sum()), repeated_eventual=int(repeat_ever.sum()),
        gt_reads='forbidden', final_pose_fields_used=False))
    (out / 'pair_audit.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in pair_rows))
    code = [ROOT / p for p in ('scripts/score_e3b_fresh.py', 'scripts/prepare_e2b_run.py', 'src/e2b_transfer.py',
                               'src/e2_signals.py', 'src/e0b_audit.py', 'scripts/score_e2.py')]
    code.append(Path(inspect.getfile(build_covariance)))
    for p in code:
        archive = out / 'code' / p.relative_to(ROOT)
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, archive)
    save_json(out / 'score_manifest.json', dict(code=[digest(p) for p in code], inputs=[digest(p) for p in inputs],
        features=digest(out/'features.npz'), metadata=digest(out/'score_metadata.json'),
        history=[digest(p) for p in sorted(history.glob('*.npz'))],
        gt_reads='forbidden', final_poses=False, scene=scene, spec_hash=digest(cfg)['sha256']))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('scene', choices=['room1'])
    with forbid_e2b_gt_reads():
        main(parser.parse_args().scene)
