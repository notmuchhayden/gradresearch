"""Provisional admission and cumulative subgroup risk calibration; no GT in policy."""
import numpy as np

UNBORN, PROVISIONAL, KEEP, REJECT, EXCLUDED = range(5)


def cumulative_scores(history, total_count):
    """Pure development helper: caller supplies a full causal score stream."""
    peak = np.full(total_count,np.nan,np.float32)
    previous = np.full(total_count,np.nan,np.float32)
    persistent = peak.copy()
    for values in history:
        values = np.asarray(values).reshape(-1)
        count = len(values)
        peak[:count] = np.fmax(peak[:count],values)
        valid = np.isfinite(previous[:count])&np.isfinite(values)
        pair = np.where(valid,np.minimum(previous[:count],values),np.nan)
        persistent[:count] = np.fmax(persistent[:count],pair)
        previous[:] = np.nan
        previous[:count] = values
    return peak,persistent


def calibrate(score, labels, active, common, anchors, retention=.99, minimum=100):
    """Control candidate-ever rejection, both full finite and named subgroups."""
    normal = active&np.isin(labels,[1,2])&np.isfinite(score)
    masks = [('own_finite',normal,True),('common_finite',normal&common,True)]
    masks += [(f'anchor_{a}',normal&(anchors==a),False) for a in np.unique(anchors[active])]
    groups,quantiles,missing = [],[],[]
    for name,mask,mandatory in masks:
        count = int(mask.sum())
        enough = count>=minimum
        t = float(np.quantile(score[mask],retention,method='higher')) if enough else None
        groups.append(dict(group=name,normal=count,used=enough,mandatory=mandatory,quantile=t))
        if enough:
            quantiles.append(t)
        elif mandatory:
            missing.append(name)
    threshold = max(quantiles) if quantiles and not missing else None
    return dict(threshold=threshold,calibrated=threshold is not None,groups=groups,
                missing_required_groups=missing,normal_retention_target=retention)


class ProvisionalAdmission:
    def __init__(self, definition, active, anchors, threshold):
        self.definition,self.active,self.anchors,self.threshold = definition,active,anchors,threshold
        self.state = np.where(active,UNBORN,EXCLUDED).astype(np.uint8)
        n = len(active)
        self.first_admit = np.full(n,-1,np.int32)
        self.first_reject = np.full(n,-1,np.int32)
        self.reject_revision = np.full(n,-1,np.int32)
        self.ever_finite = np.zeros(n,bool)
        self.reason = np.zeros(n,np.uint8)  # 0 none, 1 unknown provisional, 2 supported, 3 conflict, 4 persistent
        self.previous = np.full(n,np.nan,np.float32)
        self.previous_snapshot = -1
        self.timeline = []

    def advance(self, index, input_frame, revision, values):
        if index!=self.previous_snapshot+1:
            raise ValueError('Actual KF snapshots must be contiguous and strictly ordered')
        self.previous_snapshot = index
        seen = self.active&(self.anchors<=index)
        birth = seen&(self.anchors==index)
        self.state[birth] = PROVISIONAL
        self.reason[birth] = 1
        # Log actual instantaneous birth admission even if same-event rejection follows.
        self.first_admit[birth] = input_frame
        kind = self.definition['kind']
        live = seen&(self.state!=REJECT)
        eligible = np.zeros(len(seen),bool)
        reject = eligible.copy()
        if kind=='original':
            self.state[live] = KEEP
            self.reason[live] = 2
        else:
            score = np.full(len(seen),np.nan,np.float32)
            values = np.asarray(values).reshape(-1)
            if len(values)>len(seen) or np.any(self.anchors[:len(values)]>index):
                raise ValueError('Future candidate scores cannot enter a decision')
            score[:len(values)] = values
            target = birth if kind in {'creation','dog'} else seen
            if kind=='persistent':
                pair = np.isfinite(self.previous)&np.isfinite(score)
                decision_score = np.where(pair,np.minimum(self.previous,score),np.nan)
            else:
                decision_score = score
            eligible = target&np.isfinite(decision_score)
            self.ever_finite |= eligible
            if self.threshold is not None:
                reject = live&eligible&(decision_score>self.threshold)
            if kind=='persistent':
                self.previous = score
            supported = live&eligible&~reject
            self.state[supported] = KEEP
            self.reason[supported] = 2
            self.state[reject] = REJECT
            self.reason[reject] = 4 if kind=='persistent' else 3
            self.first_reject[reject] = input_frame
            self.reject_revision[reject] = revision
        admitted = np.isin(self.state,[PROVISIONAL,KEEP])
        assert not (admitted&~seen).any()
        self.timeline.append(dict(snapshot=index,input_frame=input_frame,pose_revision=revision,
            active=int(admitted.sum()),rejected=int((self.state==REJECT).sum()),
            provisional=int((self.state==PROVISIONAL).sum()),keep=int((self.state==KEEP).sum()),deferred=0))
        return admitted

    def arrays(self):
        return {k:getattr(self,k) for k in ['state','first_admit','first_reject','reject_revision','ever_finite','reason']}


def metrics(d,labels,mask):
    active = np.isin(d['state'],[PROVISIONAL,KEEP])&mask
    reject = (d['state']==REJECT)&mask
    normal = mask&np.isin(labels,[1,2]);bad = mask&(labels==3)
    finite_normal = normal&d['ever_finite']
    ratio = lambda a,b:float(a/b) if b else None
    tp,fp = int((reject&bad).sum()),int((reject&normal).sum())
    return dict(candidates=int(mask.sum()),normal=int(normal.sum()),bad=int(bad.sum()),
        active=int(active.sum()),rejected=int(reject.sum()),bad_rejected=tp,normal_rejected=fp,
        unknown_rejected=int((reject&~normal&~bad).sum()),precision=ratio(tp,tp+fp),
        bad_recall=ratio(tp,int(bad.sum())),normal_active_retention=ratio(int((normal&active).sum()),int(normal.sum())),
        finite_normal_retention=ratio(int((finite_normal&active).sum()),int(finite_normal.sum())),
        finite_normal=int(finite_normal.sum()),finite_candidates=int((mask&d['ever_finite']).sum()),
        provisional=int((mask&(d['state']==PROVISIONAL)).sum()),deferred=0)
