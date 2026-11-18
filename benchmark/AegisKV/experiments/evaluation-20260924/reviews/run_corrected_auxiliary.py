"""Run the three already-frozen matched replacements within sixteen workers."""
from __future__ import annotations

import datetime
import gzip
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
BASE = ROOT / 'benchmark/AegisKV/experiments/evaluation-20260924'
HERE = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv/bin/python'
SCRIPTS = ROOT / 'benchmark/AegisKV/experiments/scripts/current_design'
GROUPS = [
    ('sensitivity-campaign', 'run_sensitivity_campaign.py', 10),
    ('capacity-slack-ablation', 'run_capacity_slack_ablation.py', 5),
    ('slack-mechanism-posthoc', 'run_slack_mechanism_diagnostic.py', 1),
]


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def freeze_audit():
    gate = read(HERE / 'QUEUED_HISTORY_APPLICATION.json')
    assert gate['status'] == 'PASS' and gate['freeze_ready'] and gate['source_edits_finished']
    reports = []
    common = None
    for stem, _, _ in GROUPS:
        old, new = BASE / (stem + '-v1'), BASE / (stem + '-v2-corrected')
        before, after = read(old / 'PLAN.json'), read(new / 'PLAN.json')
        manifest = read(new / 'MANIFEST.json')
        assert manifest['design_version'] == gate['design_version']
        assert manifest['duration_profile'] == 'GridDurationProfile'
        assert 'AIConfigurator HYBRID' in manifest['timing']
        snapshot = new / 'source_snapshot'
        sources = {k: v for k, v in manifest['source_sha256'].items() if k.startswith('python/')}
        if common is None:
            common = sources
        else:
            assert sources == common
        for relative, expected in sources.items():
            assert sha(snapshot / relative) == expected
        for relative, expected in gate['source_sha256'].items():
            assert sha(snapshot / relative) == expected
        changes = []
        assert len(before['jobs']) == len(after['jobs'])
        for a, b in zip(before['jobs'], after['jobs'], strict=True):
            if a != b:
                assert stem == 'sensitivity-campaign'
                assert b == {**a, 'config': {**a['config'], 'slack_mode': 'dag'}}
                changes.append(b['id'])
        def payload(plan):
            value = plan['workload']
            return value['path'] if isinstance(value, dict) else value
        assert gzip.decompress((old / payload(before)).read_bytes()) == gzip.decompress((new / payload(after)).read_bytes())
        assert sha(old / before['profile']) == sha(new / after['profile'])
        priors_identical = None
        if (old / 'PRIORS.json').exists():
            priors_identical = sha(old / 'PRIORS.json') == sha(new / 'PRIORS.json')
            assert priors_identical
        report = dict(
            status='PASS', historical_campaign=str(old), corrected_campaign=str(new),
            old_manifest_sha256=sha(old / 'MANIFEST.json'), new_manifest_sha256=sha(new / 'MANIFEST.json'),
            old_plan_sha256=sha(old / 'PLAN.json'), new_plan_sha256=sha(new / 'PLAN.json'),
            jobs=len(after['jobs']), decoded_workload_identical=True, profile_bytes_identical=True,
            priors_file_identical=priors_identical,
            manually_assigned_agent_priors_identical_in_workload=True,
            same_job_ids_failures_parameters_and_logging=True,
            explicit_old_default_slack_mode_dag_added_to_jobs=changes,
            design_version=manifest['design_version'],
            runtime_sha256=sources['python/moonkvsim/aegiskv/current/runtime.py'],
            metadata='GridDurationProfile with actual DMA levels; sealed before execution',
            evidence='matched replacement conditions; no additional independent samples',
        )
        assert not (new / 'MATCHED_INPUTS.json').exists()
        write(new / 'MATCHED_INPUTS.json', report)
        reports.append(report)
    freeze = dict(status='PASS', gate_sha256=sha(HERE / 'QUEUED_HISTORY_APPLICATION.json'),
                  common_python_source_sha256=common, campaigns=reports, max_workers=16)
    write(HERE / 'AUXILIARY_V2_FREEZE.json', freeze)
    return freeze


def main():
    freeze_audit()
    processes = []
    for stem, script, workers in GROUPS:
        out = BASE / (stem + '-v2-corrected')
        log = (out / 'EXECUTION.log').open('x')
        command = [str(PYTHON), str(SCRIPTS / script), 'run', '--out', str(out)]
        if workers != 1:
            command += ['--workers', str(workers)]
        process = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        processes.append((stem, workers, process, log, command))
    while True:
        rows = []
        for stem, workers, process, _, command in processes:
            path = BASE / (stem + '-v2-corrected') / 'STATUS.json'
            status = read(path) if path.exists() else {'completed': 0}
            rows.append(dict(group=stem, workers=workers, pid=process.pid,
                             exit_code=process.poll(), status=status, command=command))
        report = dict(updated_utc=datetime.datetime.now(datetime.UTC).isoformat(), groups=rows,
                      max_workers=16, active_workers=sum(r['workers'] for r in rows if r['exit_code'] is None))
        write(HERE / 'AUXILIARY_V2_STATUS.json', report)
        print(json.dumps({r['group']: {'exit': r['exit_code'], 'done': r['status']['completed']} for r in rows}), flush=True)
        if all(row['exit_code'] is not None for row in rows):
            for _, _, _, log, _ in processes:
                log.close()
            assert all(row['exit_code'] == 0 for row in rows), report
            break
        time.sleep(15)


if __name__ == '__main__':
    main()
