#!/usr/bin/env sh
set -eu

AEGISKV_PAPER_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AEGISKV_BUILD_DIR="$AEGISKV_PAPER_DIR/build"   # latexmk intermediates; ignored by git (build/)
mkdir -p "$AEGISKV_BUILD_DIR"
cd "$AEGISKV_PAPER_DIR"
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$AEGISKV_BUILD_DIR" main.tex
cp "$AEGISKV_BUILD_DIR/main.pdf" "$AEGISKV_PAPER_DIR/main.pdf"
