"""Repeated-view semantics and cumulative decision metrics; no GT feature use."""
import numpy as np


def repeat_score(views, n, veto=True):
    """Second largest score; absence and inconsistent surface support abstain."""
    if not views:
        return np.full(n, np.nan, np.float32), np.zeros(n, np.uint16), np.zeros(n, bool)
    a = np.asarray(views)
    count = np.isfinite(a).sum(0).astype(np.uint16)
    support = np.any(np.isfinite(a) & (a == 0), axis=0)
    score = np.full(n, np.nan, np.float32)
    if len(a) >= 2:
        clean = np.where(np.isfinite(a), a, -np.inf)
        score[:] = np.partition(clean, -2, axis=0)[-2]
        score[count < 2] = np.nan
        if veto:
            score[support] = np.nan
    return score, count, support


def temporal_max(old, current):
    return np.fmax(old, current)


def operation(score, labels, threshold, eligible, mask=None):
    mask = np.ones(len(score), bool) if mask is None else mask
    bad, normal = (labels == 3) & mask, np.isin(labels, [1, 2]) & mask
    reject = np.isfinite(score) & mask & (score > threshold) if threshold is not None else np.zeros(len(score), bool)
    tp, fp = int((reject & bad).sum()), int((reject & normal).sum())
    nb, nn = int(bad.sum()), int(normal.sum())
    eb, en = int((eligible & bad).sum()), int((eligible & normal).sum())
    ratio = lambda a, b: float(a / b) if b else None
    return dict(threshold=threshold, rejected=int(reject.sum()), bad_rejected=tp, normal_rejected=fp,
                unknown_gt_rejected=int((reject & ~bad & ~normal).sum()),
                bad=nb, normal=nn, eligible_bad=eb, eligible_normal=en,
                precision=ratio(tp, tp + fp), global_bad_recall=ratio(tp, nb), eligible_bad_recall=ratio(tp, eb),
                global_normal_retention=1 - fp / nn if nn else None,
                eligible_normal_retention=1 - fp / en if en else None)


def progress_checks(coverage, op, rule):
    ge = lambda value, cutoff: value is not None and value >= cutoff
    return dict(repeat_coverage=ge(coverage, rule['repeat_coverage_min']),
                eligible_bad=ge(op['eligible_bad'], rule['eligible_bad_min']),
                eligible_normal=ge(op['eligible_normal'], rule['eligible_normal_min']),
                global_normal_retention=ge(op['global_normal_retention'], rule['global_normal_retention_min']),
                eligible_normal_retention=ge(op['eligible_normal_retention'], rule['eligible_normal_retention_min']),
                global_bad_recall=ge(op['global_bad_recall'], rule['global_bad_recall_min']),
                eligible_bad_recall=ge(op['eligible_bad_recall'], rule['eligible_bad_recall_min']),
                bad_rejected=ge(op['bad_rejected'], rule['bad_rejected_min']), calibrated=op['threshold'] is not None)
