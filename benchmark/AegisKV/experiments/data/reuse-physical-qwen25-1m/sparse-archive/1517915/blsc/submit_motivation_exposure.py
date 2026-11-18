"""Bounded Figure 2 measurements at the four frozen trace-prefix sizes."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

from budget_submit import reconcile, reservation, used_or_reserved, write_atomic


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    root = Path(__file__).resolve().parent
    contexts = [100865, 105921, 108865, 113665]  # C=M+1; M is the trace's block-count proxy.
    minutes = 12
    with (root/'budget.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger_path = root/'budget.json'
        ledger = json.loads(ledger_path.read_text())
        ids = [j['job_id'] for j in ledger['jobs'] if j.get('job_id')]
        report = subprocess.check_output(['sacct', '-X', '-n', '-P', '-j', ','.join(ids),
                   '--format=JobIDRaw,State,ElapsedRaw,AllocTRES'], text=True, timeout=20)
        reconcile(ledger, report)
        write_atomic(ledger_path, ledger)
        seconds = reservation(ledger, 2, minutes)
        ready = json.loads((root/'READY.json').read_text())
        sparse = json.loads((root.parent/'setup/sparse-sm80/READY.json').read_text())
        assert sparse['architecture'] == 'sm_80' and sparse['cpu_build_only']
        checks = [(v['library'], v['library_sha256']) for v in ready['sm80_libraries'].values()]
        checks += [(sparse['library'], sparse['library_sha256']),
                   (sparse['wrapper'], sparse['wrapper_sha256'])]
        for name, digest in checks:
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
        names = ['measure_prefill_sparse.py', 'launch_prefill_sparse.py', 'sg_sparse_backend.py',
                 'layerwise_restore.py', 'sg_backend.py', 'dca_grouped.py', 'measure.py',
                 'measure_prefill_optimized.py', 'sparse-config/Qwen2.5_7B_Instruct_1M.json',
                 'sparse-config/manifest.json', 'blsc/run_prefill_sparse.sbatch',
                 'blsc/submit_motivation_exposure.py', 'blsc/budget_submit.py', 'blsc/driver_check.py']
        sources = {name: hashlib.sha256((root.parent/name).read_bytes()).hexdigest() for name in names}
        job = dict(submitted_at_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                   requested_gpus=2, time_limit_minutes=minutes, reserved_gpu_seconds=seconds,
                   terminal=False, status='submission_pending',
                   purpose='Motivation Figure 2: measured Prefill at four trace-prefix proxies; 1 warmup + 3 repeats',
                   contexts=contexts, source_sha256=sources, full_repeats=3, full_warmups=1,
                   required_gpu_name='NVIDIA A100-PCIE-40GB', sparse_head_group=2,
                   sparse_library_sha256=sparse['library_sha256'], shared_storage_files_created=False)
        if args.dry_run:
            print(json.dumps({'planned_job':job, 'used_gpu_seconds':used_or_reserved(ledger),
                              'remaining_gpu_seconds':ledger['budget_gpu_seconds']-used_or_reserved(ledger)}))
            return
        ledger['jobs'].append(job)
        write_atomic(ledger_path, ledger)
        env = os.environ.copy()
        env.pop('AEGIS_SHARED_FS', None)
        env.update(AEGIS_ROOT=str(root.parent), AEGIS_PYTHON=ready['python'], AEGIS_MODEL=ready['model'],
                   TP='2', AEGIS_CONTEXTS=','.join(map(str,contexts)), AEGIS_SPARSE_HEAD_GROUP='2',
                   AEGIS_FULL_REPEATS='3', AEGIS_FULL_WARMUPS='1',
                   AEGIS_REQUIRE_GPU_NAME=job['required_gpu_name'])
        reply = subprocess.check_output(['sbatch', '--parsable', '--partition=gpu', '--nodes=1', '--ntasks=1',
                 '--gpus-per-node=2', '--cpus-per-task=64', f'--time={minutes}', '--no-requeue',
                 '--signal=B:TERM@20', '--exclude=paraai-n32-h-01-agent-4',
                 '--job-name=aegis-motivation-exposure', '--output=logs/%x-%j.log',
                 str(root/'run_prefill_sparse.sbatch')], cwd=root, env=env, text=True).strip()
        jid = reply.split(';')[0]
        assert jid.isdigit(), reply
        job.update(job_id=jid,status='submitted')
        write_atomic(ledger_path,ledger)
        archive = root.parent/'sparse-archive'/jid
        for name in names:
            dst=archive/name; dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(root.parent/name,dst)
        (archive/'source-sha256.json').write_text(json.dumps(sources,indent=2)+'\n')
        print(json.dumps({'job':job,'used_or_reserved_gpu_seconds':used_or_reserved(ledger)}))


if __name__ == '__main__':
    main()
