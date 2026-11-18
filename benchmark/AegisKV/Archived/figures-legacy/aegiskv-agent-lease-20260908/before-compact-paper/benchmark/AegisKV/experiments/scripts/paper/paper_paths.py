"""Locations shared by paper tools; the manuscript has only two subdirectories."""
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[4]
AEGISKV = ROOT / "benchmark/AegisKV"
PAPER = AEGISKV / "paper"
DOCS = AEGISKV / "docs/paper"
ARTIFACTS = AEGISKV / "experiments/results/paper"
DATA = ARTIFACTS / "data"
BUILD = ARTIFACTS / "build"
DELIVERY = ARTIFACTS / "delivery"
TEMPLATE = TOOLS / "templates/results-template.tex"
