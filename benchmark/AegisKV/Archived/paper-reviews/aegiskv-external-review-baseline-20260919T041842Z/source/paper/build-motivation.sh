#!/usr/bin/env sh
set -eu
AEGISKV_PAPER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AEGISKV_MOTIVATION_OUT="$AEGISKV_PAPER_DIR/../../../output/pdf/aegiskv-motivation-eurosys2027"
mkdir -p "$AEGISKV_MOTIVATION_OUT"
cd "$AEGISKV_PAPER_DIR"
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$AEGISKV_MOTIVATION_OUT" motivation-preview.tex
