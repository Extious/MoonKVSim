from pathlib import Path
import json,subprocess,time
root=Path.cwd()
art=root/'output/aegiskv-revision-20260909'
start=time.monotonic()
while not all((art/s/'points.json').exists() for s in ['scaling','scaling-rate']):
    time.sleep(5)
commands=[
 ['.venv/bin/python','benchmark/AegisKV/experiments/scripts/paper/render_revision_scaling.py'],
 ['.venv/bin/python','benchmark/AegisKV/experiments/scripts/paper/build_revision_story.py'],
 ['python3','benchmark/AegisKV/experiments/scripts/paper/render_agent_lease_markdown.py'],
 ['.venv/bin/python','benchmark/AegisKV/experiments/scripts/paper/audit_revision_story.py','--prepare-visuals'],
]
print(json.dumps({'stage':'all_complete_points_ready','wait_s':round(time.monotonic()-start)}),flush=True)
for cmd in commands:
    print(json.dumps({'command':cmd}),flush=True)
    subprocess.run(cmd,check=True)
print('REVISION_READY_FOR_VISUAL_REVIEW',flush=True)
