"""Sequential native exports; do not modify or delete other figures."""
from pathlib import Path
import os
import subprocess

root=Path(__file__).resolve().parent
env=os.environ.copy()
env['XDG_CONFIG_HOME']='/tmp/aegiskv-prefill-drawio-config'
env['XDG_CACHE_HOME']='/tmp/aegiskv-prefill-drawio-cache'
cli='/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
for name in ['01-prefill-overview','02-nsa-branches','03-prefill-working-set']:
    for fmt in ['png','svg']:
        args=[cli,'-x','-f',fmt,'-e','-b','0']
        if fmt=='png': args+=['--width','1100']
        args+=['-o',str(root/f'{name}.drawio.{fmt}'),str(root/f'{name}.drawio')]
        subprocess.run(args,env=env,check=True)
