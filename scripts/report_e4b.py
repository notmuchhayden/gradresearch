"""Render fixed E4b examples and report all scenes without changing registration."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/E4b_reference_plane_audit'
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src'),str(OUT/'deps')]
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np
from prepare_e2b_run import digest,save_json
from e4b_audit import COHORTS,FUNNELS


def show_examples(scene):
    dest=OUT/scene;rows=json.loads((dest/'example_ids.json').read_text());figdir=dest/'figures';figdir.mkdir(exist_ok=True)
    for row in rows:
        cid=row['candidate_id'];g=dict(np.load(dest/'examples'/f'{cid}_geometry.npz'))
        t=dict(np.load(dest/'examples'/f'{cid}_timeline.npz'))
        fig,axes=plt.subplots(2,4,figsize=(16,8));a=axes.ravel()
        a[0].imshow(g['source_rgb']);h,w=g['source_rgb'].shape[:2];y,x=divmod(int(g['source_pixel']),w)
        a[0].plot(x,y,'rx',ms=8);a[0].set_title('Candidate source RGB')
        if int(g['evidence_kf'])>=0:
            ep=int(g['evidence_pixel']);yy,xx=divmod(ep,w)
            a[1].imshow(g['evidence_rgb']);a[1].add_patch(Rectangle((xx-2,yy-2),5,5,fill=False,color='red',lw=1.5))
            a[1].set_title(f"Evidence KF {int(g['evidence_kf'])}, 5x5 patch")
            vmax=float(np.nanpercentile(g['GT_depth'],99))
            for ax,key,title in [(a[2],'predicted_depth','Predicted z-depth (m)'),(a[3],'GT_depth','GT z-depth (m)')]:
                im=ax.imshow(g[key],vmin=0,vmax=vmax,cmap='viridis');ax.plot(xx,yy,'rx');ax.set_title(title);fig.colorbar(im,ax=ax,shrink=.65)
            pred=g['predicted_patch_m'].reshape(-1,3);gt=g['GT_patch_m'].reshape(-1,3);p=g['candidate_m']
            a[4].scatter(pred[:,0],pred[:,2],s=9,label='Predicted patch');a[4].scatter(gt[:,0],gt[:,2],s=9,label='GT patch')
            a[4].scatter([p[0]],[p[2]],marker='x',c='red',s=70,label='Candidate')
            for mean,norm,label,color in [(g['predicted_mean_m'],g['predicted_normal'],'Predicted plane','C0'),(g['GT_mean_m'],g['GT_normal'],'GT plane','C1')]:
                span=max(np.ptp(np.r_[pred[:,0],gt[:,0],p[0]]),.05);xs=np.linspace(mean[0]-span,mean[0]+span,50)
                if abs(norm[2])>1e-6:a[4].plot(xs,mean[2]-norm[0]*(xs-mean[0])/norm[2],color=color,label=label)
            a[4].set_xlabel('camera x (m)');a[4].set_ylabel('camera z (m)');a[4].set_title('x-z projection; plane slices at own mean y');a[4].legend(fontsize=7)
            text=(f"GT plane reliable: {bool(g['GT_reliable'])}\nOffset: {float(g['plane_offset_m']):.4f} m\n"
                  f"Normal angle: {float(g['plane_angle_degrees']):.2f} deg\nNative depth view score: {float(g['depth_score']):.5f}\n"
                  f"Plane view score: {float(g['plane_score']):.5f}\nStrict wrong support: {bool(g['shared_wrong_support'])}")
        else:
            for ax in a[1:5]:ax.text(.5,.5,'No causal evidence at anchor',ha='center',va='center',transform=ax.transAxes)
            text='No causal evidence at the protocol-defined anchor.\nExample retained without replacement.'
        for method in ['B6_depth','D_maskmedian','D_shared','P2_plane']:
            a[5].plot(t['input_frame'],t[method+'_score'],'.-',label=method)
        a[5].set_title('Snapshot scores (different frozen thresholds)');a[5].set_xlabel('Input frame');a[5].legend(fontsize=7)
        a[6].step(t['input_frame'],t['shared_count'],where='post',label='Shared count')
        a[6].step(t['input_frame'],t['plane_zero_veto'].astype(int),where='post',label='Plane-zero veto')
        a[6].set_title('Evidence / support history');a[6].set_xlabel('Input frame');a[6].legend(fontsize=8)
        a[7].axis('off');a[7].text(0,.95,text,va='top',fontsize=10)
        for ax in a[:4]:ax.axis('off')
        fig.suptitle(f"{scene} | ID {cid} | {row['cohort']} | GT label {row['label']} | anchor {int(g['anchor_frame'])}")
        fig.tight_layout();fig.savefig(figdir/f'{cid}.png',dpi=110);plt.close(fig)
    return len(rows)


def verify_all():
    from run_e4b import checked,verify
    spec,reg=checked();source=json.loads((OUT/'input_manifest.json').read_text())
    for entry in source['inputs']:verify(entry)
    scenes=[spec['primary_scene'],*spec['secondary_scenes']];artifacts=0;figures=0
    for scene in scenes:
        check=json.loads((OUT/'reproduction'/scene/'check.json').read_text());assert check['status']=='PASS'
        for entry in check['artifacts']:verify(entry)
        manifest=json.loads((OUT/scene/'manifest.json').read_text())
        for entry in manifest['artifacts']:verify(entry);artifacts+=1
        s=json.loads((OUT/scene/'summary.json').read_text());assert s['status']=='COMPLETE' and s['factual_exact']
        assert sum(s['cohorts']['bad__'+c]['candidates'] for c in COHORTS)==s['bad']
        for cl in ['bad','normal','unknown']:
            for co in COHORTS:
                q=s['cohorts'][cl+'__'+co];assert sum(q['anchor_funnel'].values())==q['candidates']
        rows=json.loads((OUT/scene/'example_ids.json').read_text())
        for row in rows:assert (OUT/scene/'figures'/f"{row['candidate_id']}.png").is_file()
        figures+=len(rows)
    result=dict(status='PASS',scenes=scenes,source_inputs_rehashed=len(source['inputs']),
        analysis_artifacts_rehashed=artifacts,fixed_examples=figures,
        factual_scores_masks_states_first_reject_exact=True,all_four_cohorts_partition=True,
        source_results_preserved=True,efficacy_decision='E4 REVISE unchanged')
    save_json(OUT/'validation.json',result);save_json(ROOT/'configs/e4b_validation.json',result)
    print(json.dumps(result,indent=2))


def report():
    spec=json.loads((ROOT/'configs/e4b_reference_plane_audit.json').read_text())
    scenes=[spec['primary_scene'],*spec['secondary_scenes']]
    data={s:json.loads((OUT/s/'summary.json').read_text()) for s in scenes}
    p=data[spec['primary_scene']];q=p['cohorts']['bad__b6_only'];allmiss=p['cohorts']['bad__both_miss']
    lines=['# E4b 결과: 기준 평면 오류와 B6/plane 판정 경로', '',
        '**상태: 실행 완료. E4 REVISE 및 E5/E6 효능 검증 보류 유지.**', '',
        '기존 E4의 5장면을 재사용한 사후 진단이다. [등록된 설계](E4b_reference_plane_audit.md)와 설정·등록 파일은 보존했다. 모든 실제 snapshot의 원래 기하 점수·finite mask와 자연 정책의 상태·최초 제거 시점·revision을 정확히 재현한 뒤 GT 감사와 oracle을 실행했다.', '',
        '## office1에서 확인한 내용', '',
        f"전체 active {p['active']:,}개 중 GT bad는 {p['bad']:,}개다. B6만 제거한 bad는 **{q['candidates']:,}개**, 두 방식 모두 놓친 bad는 **{allmiss['candidates']:,}개**다.", '',
        '| B6-only bad: B6 최초 제거 시점의 P2 차단 단계 | 후보 수 | 해당 집합 비율 |','|---|---:|---:|']
    for key,value in q['anchor_funnel'].items():lines.append(f"| {key} | {value:,} | {value/max(q['candidates'],1):.2%} |")
    lines += ['', '차단 단계는 정해진 순서의 첫 실패이며 중첩된 원인을 모두 분리한 인과 효과는 아니다. 예를 들어 반복 수 부족과 veto가 동시에 있을 수 있다. 후보별 전체 이력과 중첩 flag는 Parquet에 보존했다.', '',
        '| office1 bad 집합 | 후보 | GT 평면 검사 가능 후보 | 기준 평면 오류 관측 후보 | 80% 일관된 점군 오류 후보 | 엄격한 잘못된 지지 후보 |',
        '|---|---:|---:|---:|---:|---:|']
    for co in COHORTS:
        c=p['cohorts']['bad__'+co];e=c['candidate_ever']
        lines.append(f"| {co} | {c['candidates']:,} | {e['GT_auditable']:,} | {e['reference_wrong']:,} | {e['coherent_wrong']:,} | {e['shared_wrong_support']:,} |")
    lines += ['', '**기준 오류 관측**은 원래 shared finite 관측에서 GT 평면 위치 또는 법선 오차를 확인한 후보 수다. **엄격한 잘못된 지지**는 미제거 bad·plane 점수 0·기준 오류·같은 관측의 GT-front·patch 내 calibrated 대응을 모두 만족한다. 전수 후보에서 한 번이라도 관측된 수이며, 같은 patch를 여러 후보가 쓴 것은 후보 수에 각각 포함된다.', '',
        '## GT 평면 교체 진단', '',
        '| office1 arm | 새로 제거한 bad | 더 이상 제거하지 않는 bad | 새로 제거한 normal | 더 이상 제거하지 않는 normal | 전체 bad recall | 정상 보존 | B6-only bad 회복 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for arm,o in p['oracle'].items():
        lines.append(f"| {arm} | {o['bad_newly_rejected']:,} | {o['bad_no_longer_rejected']:,} | {o['normal_newly_rejected']:,} | {o['normal_no_longer_rejected']:,} | {o['global_bad_recall']:.4%} | {o['normal_retention']:.4%} | {o['primary_cohort_recovered']:,} |")
    fixed=p['oracle']['GT_plane_fixed_veto'];rec=p['oracle']['GT_plane_recomputed_veto']
    lines += ['', f"원래 shared 관측 중 GT 평면으로 교체 가능한 관측 기록 비율은 **{rec['GT_pair_coverage']:.2%}**, active 후보 중 한 번 이상 교체 가능한 후보 비율은 **{rec['GT_candidate_coverage']:.2%}**다. 검사 불가 pair는 원래 값을 유지했고, 원래 없던 관측은 만들지 않았다.", '',
        f"기준 평면 오류가 판정 전환 이전 또는 같은 시점에 관측되고 oracle에서 새로 제거된 bad는 fixed-veto **{fixed['reference_error_and_same_candidate_transition']:,}개**, recomputed-veto **{rec['reference_error_and_same_candidate_transition']:,}개**다. 엄격한 잘못된 지지 사례와 oracle 전환이 겹친 bad는 각각 **{fixed['shared_wrong_support_and_transition']:,} / {rec['shared_wrong_support_and_transition']:,}개**다. 이는 해당 후보 판정에 대한 기여의 근거이며, 단일 원인이나 모델 편향의 인과성을 확정하지 않는다.", '',
        'Oracle은 원래 대응·후보·covariance·추정 pose·finite pair mask·정규화·임계값을 유지한다. 바뀐 법선 방향의 σ만 같은 covariance에서 다시 계산했다. fixed-veto는 원래 지지를 유지하고 recomputed-veto는 교체 점수의 0 여부로 veto만 다시 계산했다. 추가 정상 손상과 bad 제거 손실을 함께 해석해야 한다.', '',
        '## 장면별 결과', '',
        '| 장면 | active bad | B6-only bad | both-miss bad | 엄격한 잘못된 지지 bad | GT oracle 새 bad / 새 normal (veto 재계산) |',
        '|---|---:|---:|---:|---:|---:|']
    for scene,s in data.items():
        strict=sum(s['cohorts']['bad__'+c]['candidate_ever']['shared_wrong_support'] for c in COHORTS)
        o=s['oracle']['GT_plane_recomputed_veto']
        lines.append(f"| {scene} | {s['bad']:,} | {s['cohorts']['bad__b6_only']['candidates']:,} | {s['cohorts']['bad__both_miss']['candidates']:,} | {strict:,} | {o['bad_newly_rejected']:,} / {o['normal_newly_rejected']:,} |")
    lines += ['', '## 분모·검사 불가·민감도', '']
    for scene,s in data.items():
        u=s['unique_snapshot_patches'];o=s['oracle']['GT_plane_recomputed_veto'];sensitivity=o['label_sensitivity']
        lines += [f"### {scene}", '',
            f"후보×시점 {s['rows']['candidate']:,}행, 후보×시점×출처 적격 관측 {s['rows']['view']:,}행, 참조된 snapshot별 고유 patch {s['rows']['patch']:,}행. 그중 shared pair가 참조한 고유 `(snapshot, evidence KF, pixel)`는 {u['shared_referenced']:,}개, GT 검사 가능 {u['GT_auditable']:,}개, 기준 평면 오류 {u['reference_wrong']:,}개, 일관된 점군 오류 {u['coherent_wrong']:,}개, 공통 점 전부 오류 {u['all_points_wrong']:,}개다.", '',
            'GT 상태별 shared 고유 patch 수: '+', '.join(f'{k}={v:,}' for k,v in s['GT_reference_status_counts'].items())+'.', '',
            '평면 오류 민감도(절대 허용 cm_법선 각도 deg; 상대 2% 유지): '+', '.join(f'{k}: {v:,}' for k,v in s['reference_error_sensitivity'].items())+'.', '',
            f"기준 관측 자기 좌표의 오류와 별도로, 동일 shared 대응에서 GT-anchor 상대 pose를 넣었을 때 GT-front 판단이 달라진 bad 후보는 {sum(s['cohorts']['bad__'+c]['candidate_ever']['pose_front_changed'] for c in COHORTS):,}개다. 두 pose 모두 calibrated patch 대응이 가능한 경우만 센다.", '',
            'GT-plane/veto 재계산의 라벨 민감도: '+ '; '.join(f"{k}: 새 bad {v['bad_newly_rejected']:,}, 손실 bad {v['bad_no_longer_rejected']:,}, 새 normal {v['normal_newly_rejected']:,}, 정상 보존 {v['normal_retention']:.4%}" for k,v in sensitivity.items())+'.', '']
    lines += ['## 고정 사례·검증·재현', '',
        '각 장면의 `example_ids.json`을 GT 품질·그림 검사 전에 seed 0으로 저장했다. 네 bad 집합당 최대 8개와 normal 최대 8개이며, 관측 부재나 검사 불가 예시도 교체하지 않았다. 전체 사례 그림은 `results/E4b_reference_plane_audit/<scene>/figures/`에 있다.', '',
        '![office1: B6-only 후보의 P2 차단 단계](../figures/E4b/office1_funnel.png)', '',
        '원본 등록 문서는 보존했다. 실행 설정·입력 manifest·코드 봉인·환경·검증·장면별 요약은 결과 디렉터리와 `configs/e4b_*`에 기록했다. Parquet에는 모든 active 후보 이력, 출처 적격 관측의 실패 gate, GT 품질과 oracle 값이 남아 있다. source-ineligible 관측쌍은 `pair_audit.jsonl`에 출처 중복과 함께 기록했다.', '',
        '```bash', 'OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 .venv/bin/python -m unittest discover -s tests -p test_e4b.py',
        '.venv/bin/python scripts/run_e4b.py initialize',
        'for scene in office1 office0 room0 room1 room2; do .venv/bin/python scripts/run_e4b.py reproduce "$scene"; done',
        'for scene in office1 office0 room0 room1 room2; do .venv/bin/python scripts/run_e4b.py audit "$scene"; done',
        'MPLCONFIGDIR=/tmp/e4b-mpl .venv/bin/python scripts/report_e4b.py all', '```', '',
        '완료된 출력은 덮어쓰지 않는다. 위는 이번 실행 순서이며 독립 재실행에는 별도 output·봉인을 사용한다. CPU 분석이며 tracker·학습·SLAM 기준선·기존 E4 결과는 변경하지 않았다.', '',
        '## 해석 범위', '',
        '잘못된 기준이 불량을 지지한 관측과 oracle 판정 변화의 수를 보고한다. GT가 없는 곳·비평면 표면·잘못된 대응·pose 오류·원래 관측 부재는 여전히 남으며, 0 회복을 공통 오류 부재로 해석하지 않는다. GT bad는 반복 front 오류 proxy이고 모든 시각적 불량을 뜻하지 않는다. GT oracle의 추가 제거를 실제 알고리즘 효능으로 보고하지 않는다. RGB/TSDF 재평가를 하지 않았으므로 E4의 Chamfer 격차의 원인 비율이나 개선, 단일 지배 원인, 다장면 일반화를 확정하지 않는다.', '',
        '**후속 판단:** 기준 오류와 관측/정책 제한을 함께 고려해 개선 가설을 개발할 수 있다. 변경 알고리즘의 성공 판정에는 별도 봉인과 아직 살펴보지 않은 평가 데이터가 필요하다. E4 REVISE는 유지한다.', '']
    path=ROOT/'docs/experiments/E4b_reference_plane_audit_results.md';path.write_text('\n'.join(lines))
    fd=ROOT/'docs/figures/E4b';fd.mkdir(parents=True,exist_ok=True)
    fig,ax=plt.subplots(figsize=(10,5));vals=list(q['anchor_funnel'].values());ax.barh(FUNNELS,vals);ax.invert_yaxis()
    ax.set_xlabel('B6-only GT-bad candidates');ax.set_title('office1: P2 gate at B6 first rejection')
    for i,v in enumerate(vals):ax.text(v,i,f' {v:,}',va='center')
    fig.tight_layout();fig.savefig(fd/'office1_funnel.png',dpi=150);plt.close(fig)
    summary=dict(status='COMPLETE',primary_scene=spec['primary_scene'],scenes=data,efficacy_decision='E4 REVISE unchanged')
    save_json(OUT/'summary.json',summary);save_json(ROOT/'configs/e4b_results_summary.json',summary)
    save_json(ROOT/'configs/e4b_reporting_manifest.json',dict(report=digest(path),figure=digest(fd/'office1_funnel.png'),
        code=digest(Path(__file__)),scene_summaries=[digest(OUT/s/'summary.json') for s in scenes]))


def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['figures','check','report','all']);p.add_argument('scene',nargs='?');a=p.parse_args()
    if a.stage in ['figures','all']:
        reg=json.loads((ROOT/'configs/e4b_protocol_registration.json').read_text())
        for scene in ([a.scene] if a.scene else reg['scene_sources']):print(scene,show_examples(scene),'fixed examples',flush=True)
    if a.stage in ['check','all']:verify_all()
    if a.stage in ['report','all']:report()


if __name__=='__main__':main()
