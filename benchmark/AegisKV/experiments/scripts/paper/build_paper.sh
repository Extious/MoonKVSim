#!/usr/bin/env sh
set -eu

AEGISKV_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AEGISKV_ROOT=$(CDPATH= cd -- "$AEGISKV_SCRIPT_DIR/../../.." && pwd)
AEGISKV_PAPER_DIR="$AEGISKV_ROOT/paper"
AEGISKV_OUTPUT_DIR="$AEGISKV_ROOT/exports"

for AEGISKV_SOURCE in main.tex abstract.tex introduction.tex background.tex motivation.tex system_design.tex evaluation.tex related.tex conclusion.tex references.bib evaluation-references.bib; do
  if [ ! -f "$AEGISKV_PAPER_DIR/$AEGISKV_SOURCE" ]; then
    printf 'Missing manuscript source: %s\n' "$AEGISKV_SOURCE" >&2
    exit 1
  fi
done

# Keep auxiliary files outside paper/; publish the requested manuscript PDF there.
mkdir -p "$AEGISKV_OUTPUT_DIR/latex-build"
cd "$AEGISKV_PAPER_DIR"
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$AEGISKV_OUTPUT_DIR/latex-build" main.tex
cp "$AEGISKV_OUTPUT_DIR/latex-build/main.pdf" "$AEGISKV_PAPER_DIR/main.pdf"
printf 'PDF: %s\n' "$AEGISKV_PAPER_DIR/main.pdf"
