"""Read or collect one explicitly named Motivation job; never allocate GPUs."""
import argparse
import base64
import json
from pathlib import Path
import shlex
import subprocess

from transfer_weights import SSH

ROOT = Path(__file__).resolve().parent.parent
REMOTE = "/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("status", "sync"))
    ap.add_argument("--job-id", required=True)
    args = ap.parse_args()
    assert args.job_id.isdigit()
    common = f'''import base64,fcntl,json,pathlib,subprocess,sys
r=pathlib.Path({REMOTE!r});jid={args.job_id!r};p=r/'blsc/results'/jid
sys.path.insert(0,str(r/'blsc'))
from budget_submit import reconcile,write_atomic,used_or_reserved
with (r/'blsc/budget.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 ledger=json.loads((r/'blsc/budget.json').read_text())
 job=next(j for j in ledger['jobs'] if j.get('job_id')==jid)
 assert job['purpose'].startswith('Motivation Figure 2:')
 report=subprocess.check_output(['sacct','-X','-n','-P','-j',jid,'--format=JobIDRaw,State,ElapsedRaw,AllocTRES'],text=True,timeout=20)
 reconcile(ledger,report)
'''
    if args.action == "status":
        code = common + '''
print(json.dumps({'job':{k:job.get(k) for k in ('job_id','last_slurm_state','elapsed_seconds','actual_gpu_seconds')},'complete':(p/'COMPLETE').exists()}))
if (p/'progress.jsonl').exists():print('\\n'.join((p/'progress.jsonl').read_text().splitlines()[-4:]))
for f in p.glob('failure-rank*.json'):print(f.name,f.read_text())
if not (p/'progress.jsonl').exists():
 log=r/'blsc/logs'/f'aegis-motivation-exposure-{jid}.log'
 if log.exists():print('\\n'.join(log.read_text(errors='replace').splitlines()[-4:]))
'''
    else:
        # Update the authoritative ledger only under its lock and on terminal accounting.
        code = common + ''' assert job.get('terminal'),job
 write_atomic(r/'blsc/budget.json',ledger)
paths=[r/'blsc/budget.json']+list(p.glob('*'))+list((r/'sparse-archive'/jid).rglob('*'))
paths.append(r/'blsc/logs'/f'aegis-motivation-exposure-{jid}.log')
files={}
for f in paths:
 if f.is_file():
  assert f.stat().st_size<16*1024**2,f
  files[str(f.relative_to(r))]=base64.b64encode(f.read_bytes()).decode()
files[str((p/'sacct-terminal.txt').relative_to(r))]=base64.b64encode(report.encode()).decode()
print('AEGIS_EXPOSURE_DATA\\n'+json.dumps(files))
'''
    result = subprocess.run(SSH + ["python3 -c " + shlex.quote(code)],
                            capture_output=True, text=True, timeout=55)
    if result.returncode:
        print(result.stdout, result.stderr)
        raise SystemExit(result.returncode)
    if args.action == "status":
        print(result.stdout)
        return
    files = json.loads(result.stdout.split("AEGIS_EXPOSURE_DATA\n", 1)[1])
    for name, encoded in files.items():
        path = Path(name)
        assert not path.is_absolute() and ".." not in path.parts
        assert path.parts[0] in ("blsc", "sparse-archive")
        dest = ROOT / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(base64.b64decode(encoded))
    ledger = json.loads((ROOT / "blsc/budget.json").read_text())
    used = ledger['prior_inventory_gpu_seconds'] + sum(
        j['actual_gpu_seconds'] if j.get('terminal') else j['reserved_gpu_seconds'] for j in ledger['jobs'])
    print(json.dumps({'files_synced':len(files),'used_gpu_seconds':used,
                      'remaining_gpu_seconds':ledger['budget_gpu_seconds']-used,
                      'job':next(j for j in ledger['jobs'] if j.get('job_id')==args.job_id)},indent=2))


if __name__ == "__main__":
    main()
