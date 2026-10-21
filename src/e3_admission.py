"""Label-free admission state machine on a frozen candidate pool."""
import numpy as np

UNBORN, KEEP, REJECT, DEFER, BYPASS, EXCLUDED = range(6)
P_NAMES = {'P1', 'P2_bypass', 'P2', 'P2_unbounded', 'P3'}


class Admission:
    def __init__(self, policy, active, anchors, created_input, thresholds, ttl=2):
        self.policy, self.thresholds, self.ttl = policy, thresholds, ttl
        self.active, self.anchors, self.created_input = active, anchors, created_input
        self.state = np.where(active,UNBORN,EXCLUDED).astype(np.uint8)
        n = len(active)
        self.first_admit = np.full(n,-1,np.int32)
        self.first_reject = np.full(n,-1,np.int32)
        self.rejected_revision = np.full(n,-1,np.int32)
        self.queue_enter = np.full(n,-1,np.int32)
        self.queue_exit = np.full(n,-1,np.int32)
        self.timed_out = np.zeros(n,bool)
        self.ever_eligible = np.zeros(n,bool)
        # 0 unborn/excluded, 1 missing, 2 baseline, 3 below/support,
        # 4 threshold conflict, 5 RGB-confirmed conflict, 6 timeout.
        self.reason = np.zeros(n,np.uint8)
        self.rows = []

    def advance(self, index, input_frame, revision, history, b8=None):
        seen = self.active & (self.anchors<=index)
        birth = seen & (self.anchors==index)
        queued_policy = self.policy in {'P2','P2_unbounded','P3'}
        self.state[birth] = DEFER if queued_policy else BYPASS
        self.reason[birth] = 1
        if queued_policy:
            self.queue_enter[birth] = input_frame
        alive = seen & (self.state!=REJECT)
        method = {'B2':'B2_confidence','B6':'B6_depth_front','B7':'B7_rgb_ncc_region',
                  'B8':'B8_dog_redundancy'}.get(self.policy)
        def full(key):
            a = np.full(len(seen),np.nan,np.float32)
            v = history[key].reshape(-1)
            a[:len(v)] = v
            return a
        reject = np.zeros(len(seen),bool)
        resolved = np.zeros(len(seen),bool)
        if self.policy=='B1':
            resolved = alive
            self.reason[resolved] = 2
        elif method:
            score = b8 if self.policy=='B8' else full(method)
            eligible = seen & np.isfinite(score)
            self.ever_eligible |= eligible
            target = alive & (birth if self.policy in {'B2','B8'} else True)
            reject = target & eligible & (score>self.thresholds[method])
            resolved = target & eligible & ~reject
        elif self.policy in P_NAMES:
            score = full('P1_second_front_relative')
            count = np.zeros(len(seen),np.uint16)
            v = history['support_count'].reshape(-1)
            count[:len(v)] = v
            eligible = seen & (count>=2)
            target = alive & (birth if self.policy=='P1' else True)
            self.ever_eligible |= (birth if self.policy=='P1' else seen) & np.isfinite(score)
            conflict = np.isfinite(score) & (score>self.thresholds['P1_second_front_relative'])
            resolved = target & eligible
            reject = resolved & conflict
            if self.policy=='P3':
                photo = full('B7_rgb_ncc_region')
                # Missing RGB cannot confirm a geometric rejection.
                resolved &= ~conflict | np.isfinite(photo)
                reject &= np.isfinite(photo) & (photo>self.thresholds['B7_rgb_ncc_region'])
        else:
            raise ValueError(self.policy)
        self.state[resolved & ~reject] = KEEP
        if self.policy!='B1':
            self.reason[resolved & ~reject] = 3
        self.state[reject] = REJECT
        self.reason[reject] = 5 if self.policy=='P3' else 4
        self.first_reject[reject] = input_frame
        self.rejected_revision[reject] = revision
        if queued_policy and self.policy!='P2_unbounded':
            timeout = (self.state==DEFER) & ((index-self.anchors)>=self.ttl)
            self.state[timeout] = BYPASS
            self.timed_out[timeout] = True
            self.reason[timeout] = 6
        admitted = (self.state==KEEP)|(self.state==BYPASS)
        new_admit = admitted & (self.first_admit<0)
        self.first_admit[new_admit] = input_frame
        exit_queue = (self.queue_enter>=0)&(self.queue_exit<0)&(self.state!=DEFER)
        self.queue_exit[exit_queue] = input_frame
        self.rows.append(dict(snapshot=index,input_frame=input_frame,pose_revision=revision,
            active=int(admitted.sum()),rejected=int((self.state==REJECT).sum()),
            deferred=int((self.state==DEFER).sum()),bypass=int((self.state==BYPASS).sum()),
            keep=int((self.state==KEEP).sum()),timed_out=int(self.timed_out.sum())))
        return admitted

    def arrays(self):
        return {k:getattr(self,k) for k in ('state','first_admit','first_reject','rejected_revision',
            'queue_enter','queue_exit','timed_out','ever_eligible','reason')}


def decision_metrics(state, labels, universe, eligible):
    bad = universe & (labels==3)
    normal = universe & np.isin(labels,[1,2])
    rejected = universe & (state==REJECT)
    admitted = universe & np.isin(state,[KEEP,BYPASS])
    deferred = universe & (state==DEFER)
    tp,fp = int((rejected&bad).sum()),int((rejected&normal).sum())
    ratio = lambda a,b: float(a/b) if b else None
    return dict(candidates=int(universe.sum()),bad=int(bad.sum()),normal=int(normal.sum()),
        rejected=int(rejected.sum()),bad_rejected=tp,normal_rejected=fp,
        unknown_gt_rejected=int((rejected&~bad&~normal).sum()),
        precision=ratio(tp,tp+fp),bad_recall=ratio(tp,int(bad.sum())),
        normal_not_rejected=ratio(int((normal&~rejected).sum()),int(normal.sum())),
        normal_active_retention=ratio(int((normal&admitted).sum()),int(normal.sum())),
        normal_deferred=int((normal&deferred).sum()),
        finite_normal_retention=ratio(int((normal&eligible&~rejected).sum()),int((normal&eligible).sum())),
        finite_normal=int((normal&eligible).sum()),finite_candidates=int((universe&eligible).sum()),
        active=int((admitted&universe).sum()),deferred=int((deferred&universe).sum()))
