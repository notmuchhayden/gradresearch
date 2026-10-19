"""Analyze a completed E0b run without a GPU or GT depth/trajectory."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from e0b_audit import Audit

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("case", choices=["short", "extended"])
    args = parser.parse_args()
    Audit(ROOT / "results/E0b_ancestry_causality" / args.case).run_all()
