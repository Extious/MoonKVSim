#!/usr/bin/env sh
# Build the independent teacher-text edition. The original paper is untouched.
set -eu
AEGISKV_TEACHER_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AEGISKV_TEACHER_ROOT=$(CDPATH= cd -- "$AEGISKV_TEACHER_SCRIPT_DIR/../../.." && pwd)
AEGISKV_TEACHER_PAPER="$AEGISKV_TEACHER_ROOT/paper_teacher"
AEGISKV_TEACHER_BUILD="$AEGISKV_TEACHER_ROOT/exports/latex-build-teacher"
for AEGISKV_TEACHER_SOURCE in main.tex abstract.tex background.tex motivation.tex system_design.tex evaluation.tex; do
  test -f "$AEGISKV_TEACHER_PAPER/$AEGISKV_TEACHER_SOURCE"
done
mkdir -p "$AEGISKV_TEACHER_BUILD"
cd "$AEGISKV_TEACHER_PAPER"
latexmk -pdf -interaction=nonstopmode -halt-on-error \
  -outdir="$AEGISKV_TEACHER_BUILD" main.tex
cp "$AEGISKV_TEACHER_BUILD/main.pdf" "$AEGISKV_TEACHER_PAPER/main.pdf"
printf 'Teacher edition PDF: %s\n' "$AEGISKV_TEACHER_PAPER/main.pdf"
