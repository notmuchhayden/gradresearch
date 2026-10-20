"""Capture an immutable input/code manifest for each E2b baseline run."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    path = Path(path)
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size, sha256=h.hexdigest())


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def main():
    scene = sys.argv[1]
    cfg = ROOT / 'configs/e2b_observation_transfer.json'
    spec = json.loads(cfg.read_text())
    prereg = json.loads((ROOT / 'configs/e2b_preregistration.json').read_text())
    assert digest(cfg) == prereg['configuration'], 'Preregistered configuration changed'
    case = spec['scenes'][scene]
    dataset = ROOT / 'data/E2b/Replica' / scene
    run = ROOT / spec['output'] / 'baselines' / scene
    if (run / 'audit/events.jsonl').exists():
        raise RuntimeError('Existing baseline must be preserved; select a new run path')
    images = sorted((dataset / 'results').glob('frame*.jpg'))
    assert len(images) == case['original_frame_stop']
    assert [p.stem for p in images] == [f'frame{i:06d}' for i in range(len(images))]
    upstream = ROOT / 'thirdparty/Splatt3R-SLAM'
    code = [cfg, ROOT / 'configs/e2b_preregistration.json', ROOT / 'configs/e0b_replica_office0.yaml', Path(__file__),
            ROOT / 'scripts/run_e2b_baseline.sh', ROOT / 'src/e0_export.py', ROOT / 'src/e0b_export.py']
    code += [upstream / p for p in ('main.py', 'config/base.yaml', 'splatt3r_slam/frame.py',
                                   'splatt3r_slam/tracker.py', 'splatt3r_slam/dataloader.py',
                                   'splatt3r_slam/splatt3r_utils.py')]
    for p in code:
        archive = run / 'code' / p.relative_to(ROOT)
        archive.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, archive)
    weights = json.loads((ROOT / 'configs/e0_weights_manifest.json').read_text())
    for weight in weights:
        assert digest(ROOT / weight['file'])['sha256'] == weight['sha256'], weight['file']
    save_json(run / 'run_manifest.json', dict(scene=scene, specification=spec, dataset=str(dataset),
        code=[digest(p) for p in code], inputs=[digest(p) for p in images[::spec['input_subsample']]],
        weights=weights,
        upstream_commit=subprocess.check_output(['git', '-C', str(upstream), 'rev-parse', 'HEAD'], text=True).strip(),
        seed=spec['seed'], gt_depth_trajectory_used=False,
        calibration='original loader reads camera metadata; use_calib=false, predicted rays used by tracker'))


if __name__ == '__main__':
    main()
