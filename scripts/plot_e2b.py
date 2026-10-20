"""Publication-exportable E2b availability, calibration and operating points."""
import json
from pathlib import Path
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'scripts')]
from prepare_e2b_run import digest, save_json


def main():
    spec = json.loads((ROOT/'configs/e2b_observation_transfer.json').read_text())
    out = ROOT/spec['output']
    metric = json.loads((out/'metrics.json').read_text())
    seal = json.loads((out/'thresholds_development_only.json').read_text())
    selected = metric['selected_method']
    dest = ROOT/'docs/figures/E2b'
    dest.mkdir(parents=True,exist_ok=True)
    files = []
    def save(fig,name):
        fig.tight_layout()
        for ext in ('png','pdf'):
            p = dest/f'{name}.{ext}'
            fig.savefig(p,dpi=170,bbox_inches='tight')
            files.append(digest(p))
        plt.close(fig)
    counts = []
    for scene in ('office0','room0'):
        f = np.load(out/'scores'/scene/'features.npz')
        counts.append([100*(f['creation_count']>=2).mean(),100*f['repeat_ever'].mean(),100*(f['first_single']>=0).mean()])
    fig,ax = plt.subplots(figsize=(7.5,4))
    x = np.arange(2)
    for j,(label,color) in enumerate([('2+ at creation','#9467bd'),('2+ causal eventual','#1f77b4'),('1+ causal eventual','#999999')]):
        bars=ax.bar(x+(j-1)*0.24,np.array(counts)[:,j],0.24,label=label,color=color)
        ax.bar_label(bars,fmt='%.2f%%',fontsize=8)
    ax.set_xticks(x,['office0 development','room0 evaluation'])
    ax.set_ylabel('All raw candidates (%)')
    ax.set_title('Repeated-view availability (same snapshot, source-disjoint)')
    ax.legend(fontsize=8)
    save(fig,'availability')
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for ax,scene in zip(axes,('office0','room0')):
        f=np.load(out/'scores'/scene/'features.npz')
        values=f['max__'+selected]
        values=values[np.isfinite(values)]
        if len(values):
            ax.hist(values,bins=80,color='#1f77b4',alpha=.7)
            ax.set_yscale('log')
        threshold=seal['thresholds']['raw'][selected]['0.99']
        if threshold is not None:
            ax.axvline(threshold,color='#d62728',label=f'Frozen 99% threshold={threshold:.4g}')
            ax.legend(fontsize=8)
        ax.set_title(f'{scene}: causal candidate maxima (n={len(values):,})')
        ax.set_xlabel(selected.replace('P1_second_front_','P1 '))
        ax.set_ylabel('Candidates')
    save(fig,'threshold_transfer')
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    table=metric['results']['creation']['raw']
    methods=['B2_confidence','B6_depth_front','B7_rgb_ncc_region','B8_dog_redundancy',selected]
    labels=['Confidence','Depth','RGB NCC','DoG','P1 selected']
    for ax,key,title in zip(axes,['global_normal_retention','eligible_normal_retention'],['All normal candidates','Eligible normal candidates']):
        for method,name in zip(methods,labels):
            op=table[method]['operating_points']['0.99']
            if op[key] is not None and op['global_bad_recall'] is not None:
                ax.scatter(100*(1-op[key]),100*op['global_bad_recall'],s=45)
                ax.annotate(name,(100*(1-op[key]),100*op['global_bad_recall']),xytext=(4,4),textcoords='offset points',fontsize=8)
        ax.axvline(1.,color='red',linestyle='--',linewidth=1)
        ax.axhline(1.,color='gray',linestyle=':',linewidth=1)
        ax.set_xlabel('Normal rejection (%)')
        ax.set_ylabel('Global bad recall (%)')
        ax.set_title(title)
    save(fig,'operating_points')
    save_json(out/'figure_manifest.json',dict(code=digest(Path(__file__)),metrics=digest(out/'metrics.json'),figures=files))
    print(f'Wrote {len(files)} E2b figures')


if __name__=='__main__':
    main()
