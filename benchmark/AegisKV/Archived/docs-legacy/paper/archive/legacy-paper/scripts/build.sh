#!/usr/bin/env sh
set -eu

AEGISKV_SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
AEGISKV_PAPER_DIR=$(CDPATH= cd -- "$AEGISKV_SCRIPT_DIR/.." && pwd)

sh "$AEGISKV_SCRIPT_DIR/check_design_sync.sh"
cd "$AEGISKV_PAPER_DIR"

python3 "$AEGISKV_SCRIPT_DIR/render_legacy_wct_submission.py" \
  --verify-package

if [ -f sections/05-simulation-results.tex ] || \
   [ -f simulation-results-manifest.json ]; then
  if [ ! -f sections/05-simulation-results.tex ] || \
     [ ! -f simulation-results-manifest.json ]; then
    echo "simulation result TeX and manifest must appear together" >&2
    exit 1
  fi
  python3 "$AEGISKV_SCRIPT_DIR/render_simulation_results.py" \
    --verify-package "$AEGISKV_PAPER_DIR/simulation-results-manifest.json"
fi

python3 "$AEGISKV_SCRIPT_DIR/prepare_current_mechanism_supplement.py" \
  --verify-package

AEGISKV_TEXMFHOME=${AEGISKV_TEXMFHOME:-$AEGISKV_PAPER_DIR/.texmf}
AEGISKV_TEXMFCONFIG=${AEGISKV_TEXMFCONFIG:-$AEGISKV_PAPER_DIR/.texmf-config}
AEGISKV_TEXMFVAR=${AEGISKV_TEXMFVAR:-$AEGISKV_PAPER_DIR/.texmf-var}

if [ -d "$AEGISKV_TEXMFHOME" ]; then
  TEXMFHOME="$AEGISKV_TEXMFHOME" \
  TEXMFCONFIG="$AEGISKV_TEXMFCONFIG" \
  TEXMFVAR="$AEGISKV_TEXMFVAR" \
  TEXINPUTS=template/acmart//: \
  BSTINPUTS=template/acmart//: \
  latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex
else
  TEXINPUTS=template/acmart//: \
  BSTINPUTS=template/acmart//: \
  latexmk -g -pdf -interaction=nonstopmode -halt-on-error main.tex
fi

if [ -f sections/05-simulation-results.tex ]; then
  AEGISKV_MAX_TECHNICAL_PAGES=${AEGISKV_MAX_TECHNICAL_PAGES:-99}
  python3 "$AEGISKV_SCRIPT_DIR/audit_simulation_pdf.py" \
    --pdf "$AEGISKV_PAPER_DIR/main.pdf" \
    --max-technical-pages "$AEGISKV_MAX_TECHNICAL_PAGES"
fi
