"""Compact read-only CPU build snapshot; --after waits at most 40 seconds."""
import argparse,json,shlex,subprocess
from transfer_weights import SSH
p=argparse.ArgumentParser();p.add_argument('--after',type=int,default=-1);a=p.parse_args()
code=r'''
from pathlib import Path
import json,re,time
root=Path('/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919/setup')
start=time.monotonic()
while True:
 s=(root/'sm80-build.log').read_text();s=s[s.rfind('-- Build files have been written'):]
 steps=re.findall(r'\[(\d+)/(\d+)\] (.*)',s)
 n=int(steps[-1][0]) if steps else 0
 done=(root/'sm80-build/BUILD_COMPLETE.json').exists()
 failed='FAILED:' in s or 'ninja: build stopped' in s or 'CalledProcessError' in s
 if n>AFTER or done or failed or time.monotonic()-start>=40:break
 time.sleep(2)
print(json.dumps({'completed':n,'total':int(steps[-1][1]) if steps else None,'build_complete':done,'failed':failed,'last_step':Path(steps[-1][2]).name if steps else None,'log_age_seconds':round(time.time()-(root/'sm80-build.log').stat().st_mtime,1)}))
if failed:print(s[-6000:])
'''.replace('AFTER',str(a.after))
print(subprocess.check_output(SSH+['python3 -c '+shlex.quote(code)],text=True),end='')
