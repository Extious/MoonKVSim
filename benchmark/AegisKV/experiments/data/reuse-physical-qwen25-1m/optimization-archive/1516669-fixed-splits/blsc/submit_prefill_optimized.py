"""One bounded diagnostic reservation in the existing cumulative GPU ledger."""
import fcntl
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from budget_submit import reconcile, reservation, write_atomic, used_or_reserved

root = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument('--minutes',type=int,default=10)
ap.add_argument('--pilot', action='store_true', help='8K only, hard limit three minutes')
args = ap.parse_args()
minutes = 3 if args.pilot else args.minutes
contexts = '8192,65536' if args.pilot else '8192,65536,262144,1010000'
with (root / 'budget.lock').open('a') as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    path = root / 'budget.json'
    ledger = json.loads(path.read_text())
    ids = [j['job_id'] for j in ledger['jobs'] if j.get('job_id')]
    report = subprocess.check_output(['sacct', '-X', '-n', '-P', '-j', ','.join(ids),
                                     '--format=JobIDRaw,State,ElapsedRaw,AllocTRES'], text=True, timeout=20)
    reconcile(ledger, report)
    assert ledger['budget_gpu_seconds'] == 10800
    seconds = reservation(ledger, 2, minutes)
    ready = json.loads((root / 'READY.json').read_text())
    assert ready['flash_ops_sm80_available']
    for lib in ready['sm80_libraries'].values():
        assert hashlib.sha256(Path(lib['library']).read_bytes()).hexdigest() == lib['library_sha256']
    sources = {str(p.relative_to(root.parent)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in [root.parent/'measure_prefill_optimized.py', root.parent/'launch_prefill_optimized.py', root.parent/'dca_grouped.py', root.parent/'sg_optimized_backend.py', root.parent/'sg_backend.py', root.parent/'measure.py', root/'run_prefill_optimized.sbatch', Path(__file__)]}
    job = {'submitted_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
           'requested_gpus': 2, 'time_limit_minutes': minutes, 'reserved_gpu_seconds': seconds,
           'terminal': False, 'status': 'submission_pending',
           'purpose': 'optimized grouped-head DCA Prefill; native-reference and operator-boundary checks',
           'contexts': contexts, 'pilot': args.pilot,
           'source_sha256': sources}
    ledger['jobs'].append(job)
    write_atomic(path, ledger)
    env = os.environ.copy()
    env.update(AEGIS_ROOT=str(root.parent), AEGIS_PYTHON=ready['python'],
               AEGIS_MODEL=ready['model'], TP='2', AEGIS_CONTEXTS=contexts)
    command = ['sbatch', '--parsable', '--partition=gpu', '--nodes=1', '--ntasks=1',
               '--gpus-per-node=2', '--cpus-per-task=64', f'--time={minutes}', '--no-requeue',
               '--signal=B:TERM@15', '--exclude=paraai-n32-h-01-agent-4',
               '--job-name=aegis-qwen1m-budget', '--output=logs/%x-%j.log',
               str(root/'run_prefill_optimized.sbatch')]
    reply = subprocess.check_output(command, cwd=root, env=env, text=True).strip()
    jid = reply.split(';')[0]
    assert jid.isdigit(), reply
    job.update(job_id=jid, status='submitted')
    write_atomic(path, ledger)
    print(json.dumps({'job': job, 'used_or_reserved_gpu_seconds': used_or_reserved(ledger)}))
