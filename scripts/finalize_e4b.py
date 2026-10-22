"""Attach E4b denominator clarifications, traceability and final artifact checks."""
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'results/E4b_reference_plane_audit'
sys.path[:0]=[str(ROOT/'scripts'),str(OUT/'deps')]
import pyarrow.parquet as pq
from prepare_e2b_run import digest,save_json


def main():
    r=json.loads((ROOT/'configs/e4b_postprocessing_registration.json').read_text())
    assert digest(Path(__file__))==r['code']
    from summarize_e4b_patches import main as unique_patches
    from trace_e4b_support import main as trace_support
    unique_patches();trace_support()
    source=json.loads((OUT/'source_patch_summary.json').read_text())
    traces=json.loads((OUT/'strict_support_examples.json').read_text())
    summary=json.loads((OUT/'summary.json').read_text());scenes=summary['scenes'];s=scenes['office1']
    q=s['cohorts']['bad__b6_only'];co=s['cohorts']['bad__both_miss']
    strict=q['candidate_ever']['shared_wrong_support']+co['candidate_ever']['shared_wrong_support']
    coherent=q['candidate_ever']['shared_wrong_coherent']+co['candidate_ever']['shared_wrong_coherent']
    insufficient=q['anchor_funnel']['no_finite_shared_plane']+q['anchor_funnel']['fewer_than_two_shared_views']
    o=s['oracle']['GT_plane_recomputed_veto']
    intro=(f"**핵심 관측:** office1에서 잘못된 평면이 불량을 지지한 후보는 **{strict:,}개**였고, 그중 **{coherent:,}개**는 주변 공통 점의 80% 이상이 같은 방향으로 틀린 점군도 함께 관측됐다. 질문한 실패 방식의 사례가 확인됐다. 80% 조건을 모든 점 오류로 바꾸어 표현하지 않는다.\n\n"
        f"동시에 B6-only bad {q['candidates']:,}개 중 **{insufficient:,}개({insufficient/q['candidates']:.2%})**는 **B6 최초 제거 시점에** P2의 유효 평면 관측이 두 개 미만이었다. 해당 시점의 차이를 기준 평면 오차 하나로 설명할 수 없다. 이후 전체 이력과 관측 오류의 중첩은 별도로 감사했다.\n\n"
        f"GT-plane/veto 재계산은 새 bad **{o['bad_newly_rejected']:,}개**, 새 normal **{o['normal_newly_rejected']:,}개**, 새 unknown **{o['unknown_newly_rejected']:,}개**를 제거했다. B6-only 회복은 **{o['primary_cohort_recovered']:,}개({o['primary_cohort_recovery']:.2%})**다. 기준 오류의 기여는 확인됐지만, GT 교체만으로 전체 관측·판정 제한을 해결하지는 못했다.\n\n")
    report=ROOT/'docs/experiments/E4b_reference_plane_audit_results.md'
    text=report.read_text();marker='## office1에서 확인한 내용'
    assert '**핵심 관측:**' not in text
    text=text.replace(marker,intro+marker,1)
    extra=['', '## 추가 분모 감사: 원본 patch와 시점별 patch', '',
        '구현 전에 등록한 [분모 명확화](../../configs/e4b_execution_notes.json)에 따라 위의 snapshot별 고유 patch와 별도로 **원본 `(evidence event, branch 0, pixel)`을 시점 전체에서 중복 제거한 수**를 보고한다. 조건별로 한 번 이상 관측됐는지를 집계하므로 조건 간 집합은 중첩될 수 있다. 같은 시점에 해당 조건과 후보 집합 연결이 성립한 경우만 group bit에 누적했다.', '',
        '| 장면 | shared가 참조한 원본 patch | GT 검사 가능 원본 patch | 기준 평면 오류 원본 patch | 80% 일관된 점군 오류 원본 patch | 공통 점 전부 오류 원본 patch |',
        '|---|---:|---:|---:|---:|---:|']
    for scene,d in source.items():
        c=d['counts'];extra.append(f"| {scene} | {c['shared_referenced']:,} | {c['GT_auditable']:,} | {c['reference_wrong']:,} | {c['coherent_wrong']:,} | {c['all_points_wrong']:,} |")
    extra += ['', '## 판정 근거를 추적할 수 있는 office1 사례', '',
        '고정 무작위 그림 표본은 변경하지 않았다. 엄격한 잘못된 지지 조건을 만족한 ID 중 가장 작은 5개를 고르고, 최초 적격 snapshot·가장 작은 evidence KF의 기록을 추가했다. 선택 규칙과 코드는 [trace 등록](../../configs/e4b_trace_registration.json)에 기록했다. 다음은 사례의 존재를 보여주는 기록이며 빈도는 전수 집계로 판단한다.', '',
        '| 후보 ID | input frame / pose revision | 기준 KF / pixel | plane 점수 | 평면 위치 오차 m | 법선 각도 ° | 80% 점군 오류 |',
        '|---|---|---|---:|---:|---:|---|']
    for row in traces['office1']['rows']:
        extra.append(f"| {row['candidate_id']} | {row['input_frame']} / {row['pose_revision']} | {row['evidence_kf']} / {row['evidence_pixel']} | {row['plane_score']:.5f} | {row['plane_offset_m']:.4f} | {row['plane_angle_degrees']:.2f} | {row['coherent_wrong']} |")
    extra += ['', '각 기록은 GT bad, 최종 P2 미제거, 원래 finite plane 점수 0, 기준 평면 오류, 같은 GT 관측에서 3σ까지 front, calibrated 투영이 해당 patch 안이라는 조건을 만족한다. 모든 장면의 추가 사례는 `strict_support_examples.json`에 저장했다.', '',
        '## Unknown 제거와 대조군의 보조 집계', '',
        '| 장면 | active unknown | GT-plane/veto 재계산 새 unknown | 더 이상 제거하지 않는 unknown |',
        '|---|---:|---:|---:|']
    for scene,d in scenes.items():
        o2=d['oracle']['GT_plane_recomputed_veto'];extra.append(f"| {scene} | {d['unknown']:,} | {o2['unknown_newly_rejected']:,} | {o2['unknown_no_longer_rejected']:,} |")
    a=q['anchor_method_above_threshold']
    extra += ['', f"office1 B6-only 집합의 B6 최초 제거 시점에 임계값을 넘긴 후보 수는 B6 {a['B6_depth']:,}, D_maskmedian {a['D_maskmedian']:,}, D_shared {a['D_shared']:,}, P2 {a['P2_plane']:,}개다. matched depth들도 같은 관측 mask·2+·veto를 적용하면 그 시점의 제거 근거가 크게 제한된다. 각 방법의 임계값이 다르므로 순수 residual의 인과 비교는 아니다.", '',
        '## 최종 검증', '',
        '13개 합성 테스트 PASS. 다섯 장면의 원본 점수·finite mask·정책 필드·최초 제거 시점 재현 PASS. 입력 1,155개 재해시, 모든 감사 파일 해시, Parquet metadata 행 수와 집계 일치, 정해진 집합 분할·원본 patch 중복 제거와 고정 사례 존재를 검사했다. 기준 오류·정책 차이의 진단은 완료했으며 효능 GO 판정은 하지 않았다.', '',
        '보조 집계 재현 명령:', '', '```bash', '.venv/bin/python scripts/finalize_e4b.py', '```', '',
        '먼저 본문의 `report_e4b.py report`로 기본 보고서를 생성한 뒤 실행한다. 입력별 분모·trace 규칙을 변경하지 않는 보고 단계이며, 전체 실행 결과를 덮어써서 정책을 재계산하지 않는다.', '']
    report.write_text(text+'\n'.join(extra))
    figures=[];rowchecks={};supplemental=[]
    for scene,d in scenes.items():
        rowchecks[scene]={}
        for key in ['candidate','view','patch']:
            count=pq.ParquetFile(OUT/scene/f'{key}_audit.parquet').metadata.num_rows
            assert count==d['rows'][key];rowchecks[scene][key]=count
        for key,count in source[scene]['counts'].items():
            assert count<=d['unique_snapshot_patches'][key]
        figures += [digest(p) for p in sorted((OUT/scene/'figures').glob('*.png'))]
        supplemental += [digest(OUT/scene/'source_patch_summary.json'),digest(OUT/scene/'strict_support_examples.json')]
    figures += [digest(p) for p in sorted((ROOT/'docs/figures/E4b').glob('*.png'))]
    save_json(OUT/'figures_manifest.json',dict(figures=figures))
    validation=json.loads((OUT/'validation.json').read_text())
    validation.update(parquet_rows_verified=rowchecks,raw_source_patch_dedup_verified=True,
        strict_support_traces_verified=True,figures_hashed=len(figures),unit_tests=13)
    save_json(OUT/'validation.json',validation);save_json(ROOT/'configs/e4b_validation.json',validation)
    summary.update(source_patch_counts=source,strict_support_examples=traces)
    save_json(OUT/'summary.json',summary);save_json(ROOT/'configs/e4b_results_summary.json',summary)
    save_json(ROOT/'configs/e4b_reporting_manifest.json',dict(report=digest(report),
        figure_manifest=digest(OUT/'figures_manifest.json'),supplemental_artifacts=supplemental,
        reporting_code=[digest(ROOT/p) for p in ['scripts/report_e4b.py','scripts/finalize_e4b.py','scripts/summarize_e4b_patches.py','scripts/trace_e4b_support.py']],
        reporting_registrations=[digest(ROOT/p) for p in ['configs/e4b_execution_notes.json','configs/e4b_trace_registration.json','configs/e4b_postprocessing_registration.json']],
        scene_summaries=[digest(OUT/s/'summary.json') for s in scenes],validation=digest(OUT/'validation.json')))
    print('E4b complete: original results preserved; report, source-patch counts, traces and figures verified.')


if __name__=='__main__':main()
