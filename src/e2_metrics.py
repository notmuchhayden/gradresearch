"""Tie-aware ranking and development-only safe thresholds for E2."""
import numpy as np


def pr_metrics(y, score):
    y, score = np.asarray(y, bool), np.asarray(score, float)
    good = np.isfinite(score)
    y, score = y[good], score[good]
    positives, negatives = int(y.sum()), int((~y).sum())
    base = dict(n=len(y), bad=positives, normal=negatives,
                bad_prevalence=positives / len(y) if len(y) else None)
    if not positives or not negatives:
        return dict(**base, average_precision=None, trapezoid_pr_auc=None), (np.array([]), np.array([]))
    order = np.argsort(-score, kind="stable")
    y, score = y[order], score[order]
    ends = np.r_[np.flatnonzero(score[:-1] != score[1:]), len(score) - 1]
    tp = np.cumsum(y)[ends]
    fp = 1 + ends - tp
    precision = tp / (tp + fp)
    recall = tp / positives
    ap = np.sum(np.diff(np.r_[0., recall]) * precision)
    trap = np.trapezoid(np.r_[1., precision], np.r_[0., recall])
    return dict(**base, average_precision=float(ap), trapezoid_pr_auc=float(trap),
                distinct_scores=len(ends)), (np.r_[0., recall], np.r_[1., precision])


def calibrate_normal_threshold(score, normal, retention):
    values = np.asarray(score)[np.asarray(normal, bool) & np.isfinite(score)]
    if not len(values):
        return None
    return float(np.quantile(values, retention, method="higher"))


def operating_point(score, bad, normal, threshold, universe=None):
    score, bad, normal = np.asarray(score), np.asarray(bad, bool), np.asarray(normal, bool)
    universe = np.ones(len(score), bool) if universe is None else np.asarray(universe, bool)
    eligible = np.isfinite(score) & universe
    reject = eligible & (score > threshold) if threshold is not None else np.zeros(len(score), bool)
    tp, fp = int((reject & bad).sum()), int((reject & normal).sum())
    nb, nn = int((bad & universe).sum()), int((normal & universe).sum())
    en = int((normal & eligible).sum())
    return dict(threshold=threshold, rejected=int(reject.sum()), bad_rejected=tp, normal_rejected=fp,
                unknown_gt_rejected=int((reject & ~bad & ~normal).sum()),
                precision=tp / (tp + fp) if tp + fp else None,
                global_bad_recall=tp / nb if nb else None,
                global_normal_retention=1 - fp / nn if nn else None,
                eligible_normal_retention=1 - fp / en if en else None,
                global_false_rejection=fp / nn if nn else None)
