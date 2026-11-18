"""Read only this experiment's remote status and small evidence files."""
import json
from pathlib import Path
import shlex
import subprocess
import time
from transfer_weights import SSH

root = Path(__file__).resolve().parent
code = r'''
from pathlib import Path
import json,subprocess,time
r=Path('/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919')
subprocess.run(['python3',str(r/'blsc/budget_submit.py'),'status'],check=True,stdout=subprocess.DEVNULL)
ledger=json.loads((r/'blsc/budget.json').read_text())
ids=[j['job_id'] for j in ledger['jobs'] if j.get('job_id')]
status={'recorded_at_utc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'budget':ledger}
for name,cmd in {
 'queue':['squeue','-j',','.join(ids),'-o','%.18i %.10T %.10M %.10l %R'],
 'accounting':['sacct','-X','-n','-P','-j',','.join(ids),'--format=JobIDRaw,State,ElapsedRaw,AllocTRES,NodeList,ExitCode'],
}.items():
 p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
 status[name]={'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr}
paths=[r/n for n in ['blsc/budget.json','blsc/READY.json','setup/cpu-check.json','setup/cpu-check.log','setup/pip-result.json','setup/install.py','setup/constraints.txt','setup/pip-install.log']]
paths.extend(r/n for n in ['setup/cuda-ready.json','setup/cuda-prepare.log','setup/cuda-redistribution-manifest.json'])
paths.extend(r/n for n in ['setup/flash-ops-architecture.json','setup/flash-ops-elf-list.txt','blsc/READY_BLOCKED.json','blsc/expand-candidates-cancellation.json'])
paths.extend(r/n for n in ['setup/sm80-ready.json', 'setup/sm80-import.log',
 'setup/sm80-build.log', 'setup/sm80-build/sources.json',
 'setup/sm80-build/build-customization.json', 'setup/sm80-build/BUILD_COMPLETE.json',
 'setup/sm80-build/sglang/sgl-kernel/CMakeLists.txt',
 'setup/sm80-build/sglang/sgl-kernel/CMakeLists.upstream.txt'])
for jid in ids:
 paths.append(r/f'blsc/logs/aegis-qwen1m-budget-{jid}.log')
 paths.extend((r/f'blsc/results/{jid}').glob('*'))
files={str(p.relative_to(r)):p.read_text(errors='replace') for p in paths if p.is_file() and p.stat().st_size<16*1024**2}
print('AEGIS_STATUS_JSON\n'+json.dumps({'status':status,'files':files}))
'''
reply = subprocess.check_output(SSH + ['python3 -c ' + shlex.quote(code)], text=True)
data = json.loads(reply.split('AEGIS_STATUS_JSON\n', 1)[1])
if 'blsc/READY.json' not in data['files'] and (root / 'READY.json').exists():
    # A read-only snapshot must not retain a gate revoked on the remote host.
    (root / 'READY.json').rename(root / f'READY-cached-historical-{int(time.time())}.json')
for name, content in data['files'].items():
    relative = Path(name)
    assert not relative.is_absolute() and '..' not in relative.parts
    dest = root.parent / relative if relative.parts[0] == 'blsc' else root / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content)
(root / 'latest-status.json').write_text(json.dumps(data['status'], indent=2) + '\n')
print(json.dumps(data['status'], indent=2))
