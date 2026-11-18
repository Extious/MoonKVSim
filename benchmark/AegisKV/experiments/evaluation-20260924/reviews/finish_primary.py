from pathlib import Path
import subprocess,time
root=Path("/home/comp/zhanzhao/MoonKVSim")
campaign=root/"benchmark/AegisKV/experiments/evaluation-20260924/formal-core-v1"
while len(list((campaign/"runs").glob("*/COMPLETE.json"))) < 180:
    failures=list((campaign/"runs").glob("*/FAILED.json"))
    if failures: raise RuntimeError(f"failed runs: {failures}")
    time.sleep(20)
for script in ["audit_profile_campaign.py", "plot_profile_campaign.py"]:
    subprocess.run([str(root/".venv/bin/python"), str(root/"benchmark/AegisKV/experiments/scripts/current_design"/script), "--campaign", str(campaign)],cwd=root,check=True)
print("PRIMARY AUDIT AND FIGURES COMPLETE",flush=True)
