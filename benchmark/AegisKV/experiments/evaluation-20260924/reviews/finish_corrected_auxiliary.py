"""Read-only-audit/figure follow-up; never launches experiment jobs."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'benchmark/AegisKV/experiments/evaluation-20260924'
HERE = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv/bin/python'
SCRIPTS = ROOT / 'benchmark/AegisKV/experiments/scripts/current_design'


def read(path):
    return json.loads(path.read_text())


def command(script, *args):
    subprocess.run([str(PYTHON), str(SCRIPTS / script), *map(str, args)], cwd=ROOT, check=True)


def main():
    while True:
        state = read(HERE / 'AUXILIARY_V2_STATUS.json')
        if all(row['exit_code'] is not None for row in state['groups']):
            assert all(row['exit_code'] == 0 for row in state['groups']), state
            break
        time.sleep(15)
    command('audit_corrected_capacity_slack.py', '--out', BASE / 'capacity-slack-ablation-v2-corrected')
    command('plot_corrected_sensitivity.py', '--source', BASE / 'sensitivity-campaign-v2-corrected')
    print('AUXILIARY_AUDIT_FIGURES_READY', flush=True)
    primary = BASE / 'formal-core-v2-corrected'
    while True:
        audit_path = primary / 'AUDIT.json'
        if audit_path.exists():
            audit = read(audit_path)
            if audit.get('passed') and audit.get('verified_runs') == 180:
                break
        time.sleep(20)
    command('audit_o1_dma_evidence.py', '--primary', primary,
            '--sensitivity', BASE / 'sensitivity-campaign-v2-corrected',
            '--out', HERE / 'o1-dma-corrected-v2-audit',
            '--label', 'corrected-v2-causal-domain1-queued-history1')
    print('CORRECTED_O1_DMA_AUDIT_READY', flush=True)


if __name__ == '__main__':
    main()
