#!/usr/bin/env python3
"""Fixed-view scientific figures and an offline center-proxy viewer for A0."""
import json
from pathlib import Path
import sys

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT/"results/E4_matched_budget/deps"))


def main():
    out=ROOT/"results/A0_pointmap_pose_factorial/office2";analysis=out/"analysis"
    r=json.loads((analysis/"results.json").read_text());names=["A00","A10","A01","A11"]
    rows=[next(v for v in r["table"] if v["scope"]=="strict" and v["arm"]==arm) for arm in names]
    figures=ROOT/"docs/figures/A0";figures.mkdir(parents=True,exist_ok=True)
    colors=["#667085","#d97706","#c43c4a","#14836b"]
    fig,axes=plt.subplots(1,3,figsize=(12,3.5),constrained_layout=True)
    metrics=[("common_covered_MAE_m","Common-covered depth MAE (m)"),("correct_depth_coverage","Correct-depth coverage"),("sample_chamfer_m","Observed TSDF sample Chamfer (m)")]
    for ax,(key,label) in zip(axes,metrics):
        values=[v[key] for v in rows];ax.bar(names,values,color=colors);ax.set_title(label)
        ax.set_ylim(0,max(values)*1.2)
        for i,value in enumerate(values):ax.text(i,value,f"{value:.3f}",ha="center",va="bottom",fontsize=9)
        ax.grid(axis="y",alpha=.2);ax.set_axisbelow(True)
    fig.suptitle("office2 | 1,200,827 fixed candidates | 400 held-out views | one diagnostic scene")
    fig.savefig(figures/"office2_four_arm_metrics.png",dpi=180);plt.close(fig)
    shared=json.loads((analysis/"strict_common4.json").read_text())
    fig,axes=plt.subplots(2,1,figsize=(11,6),sharex=True,constrained_layout=True)
    for arm,color in zip(names,colors):
        xs=[v["frame"] for v in shared["per_frame"]];ys=[v["mae_m"][f"strict_{arm}_C1"] for v in shared["per_frame"]]
        axes[0].plot(xs,ys,label=arm,color=color,lw=1)
        values=json.loads((out/"evaluation"/f"strict_{arm}_C1"/"metrics.json").read_text())["frames"]
        axes[1].plot([v["frame"] for v in values],[v["correct_coverage"] for v in values],label=arm,color=color,lw=1)
    axes[0].set_ylabel("Common-covered MAE (m)");axes[1].set_ylabel("Correct-depth coverage");axes[1].set_xlabel("Original held-out frame ID")
    for ax in axes:ax.legend(ncol=4);ax.grid(alpha=.2)
    fig.savefig(figures/"office2_frame_metrics.png",dpi=180);plt.close(fig)
    # Frame 601 was registered before inference; colour scales are fixed.
    snapshots={a:np.load(out/"evaluation"/f"strict_{a}_C1"/"frame0601.npz") for a in names}
    first=snapshots["A00"];fig,axes=plt.subplots(3,5,figsize=(15,6.7),constrained_layout=True)
    axes[0,0].imshow(first["target"]);axes[1,0].imshow(first["gt"],vmin=0,vmax=10,cmap="viridis")
    axes[2,0].imshow(first["valid"]&~first["edge"],cmap="gray",vmin=0,vmax=1)
    axes[0,0].set_title("GT RGB");axes[1,0].set_title("GT Z-depth [0,10] m");axes[2,0].set_title("GT interior mask")
    error_cmap=plt.get_cmap("magma").copy();error_cmap.set_bad("#9b9b9b")
    for column,arm in enumerate(names,1):
        s=snapshots[arm];axes[0,column].imshow(s["rgb"]);axes[0,column].set_title(arm)
        axes[1,column].imshow(np.ma.masked_where(~s["covered"],s["depth"]),vmin=0,vmax=10,cmap="viridis")
        error=np.abs(s["depth"]-s["gt"]);good=s["covered"]&s["valid"]&~s["edge"]
        axes[2,column].imshow(np.ma.masked_where(~good,error),vmin=0,vmax=.5,cmap=error_cmap)
    for ax in axes.ravel():ax.axis("off")
    fig.suptitle("Registered frame 601: RGB / expected Z-depth / |depth error| (0-0.5 m; grey = excluded or uncovered)")
    fig.savefig(figures/"office2_frame601_comparison.png",dpi=180);plt.close(fig)
    import plotly.graph_objects as go
    viewer=go.Figure()
    reference=np.load(out/"evaluation/reference_surface_samples.npy")[::5]
    viewer.add_trace(go.Scatter3d(x=reference[:,0],y=reference[:,1],z=reference[:,2],mode="markers",name="Observed GT-depth TSDF samples",
                                marker={"size":1,"color":"#a0a0a0","opacity":.25}))
    for arm,color in zip(names,colors):
        points=np.load(out/"oracles"/f"strict_{arm}_C1_center_proxy.npy")
        viewer.add_trace(go.Scatter3d(x=points[:,0],y=points[:,1],z=points[:,2],mode="markers",name=arm,
             visible=True if arm=="A00" else "legendonly",marker={"size":2,"color":color,"opacity":.7}))
    # Show the registered target view and its last preceding source KF.
    sys.path.insert(0,str(ROOT/"src"))
    from pointmap_contract import sim3_from_xyzw,metric_placement,sim3_parts
    import torch
    gt=np.loadtxt(ROOT/"data/N2/Replica/office2/groundtruth.txt")
    dump=torch.load(out/"baseline/map/office2_kfgauss.pt",weights_only=True,map_location="cpu")
    kf=max((k for k in dump["keyframes"] if 2*k["frame_id"]<=601),key=lambda k:k["frame_id"])
    anchor=2*kf["frame_id"];alignment=json.loads((out/"oracles/alignment.json").read_text())
    estimated=metric_placement(sim3_from_xyzw(kf["T_WC"].numpy()),np.array(alignment["matrix"]),alignment["local_C"])
    cameras=[("GT target 601",sim3_from_xyzw([*gt[601,1:8],1])),
             (f"GT source KF {anchor}",sim3_from_xyzw([*gt[anchor,1:8],1])),(f"Estimated source KF {anchor}",estimated)]
    for name,pose in cameras:
        _,rotation,origin=sim3_parts(pose)
        for axis,color in enumerate(["#e33b3b","#249b42","#2468d8"]):
            end=origin+.25*rotation[:,axis]
            viewer.add_trace(go.Scatter3d(x=[origin[0],end[0]],y=[origin[1],end[1]],z=[origin[2],end[2]],
                mode="lines",name=f"{name}: {'xyz'[axis]}",legendgroup=name,marker={"color":color},line={"color":color,"width":5}))
    viewer.update_layout(title="office2 center proxy viewer: toggle arms in legend; these points are not rendered surfaces",
         scene={"aspectmode":"data","xaxis_title":"world x (m)","yaxis_title":"world y (m)","zaxis_title":"world z (m)"},height=850)
    viewer.write_html(out/"A0_center_proxy_viewer.html",include_plotlyjs=True,auto_open=False)
    print("Saved three scientific figures and offline center viewer.")


if __name__=="__main__":main()
