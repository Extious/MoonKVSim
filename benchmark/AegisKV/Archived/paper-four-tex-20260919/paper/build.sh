#!/usr/bin/env sh
set -eu

AEGISKV_PAPER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AEGISKV_OUTPUT_DIR=${AEGISKV_OUTPUT_DIR:-"$AEGISKV_PAPER_DIR/../exports"}
mkdir -p "$AEGISKV_OUTPUT_DIR"
AEGISKV_OUTPUT_DIR=$(CDPATH= cd -- "$AEGISKV_OUTPUT_DIR" && pwd)
cd "$AEGISKV_PAPER_DIR"
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$AEGISKV_OUTPUT_DIR/latex-build" main.tex
cp "$AEGISKV_OUTPUT_DIR/latex-build/main.pdf" "$AEGISKV_OUTPUT_DIR/aegiskv.pdf"
printf 'PDF: %s\n' "$AEGISKV_OUTPUT_DIR/aegiskv.pdf"
