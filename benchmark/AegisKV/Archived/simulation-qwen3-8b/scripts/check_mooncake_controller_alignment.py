#!/usr/bin/env python3
"""Differential checks against actual native Mooncake policy source."""
from __future__ import annotations
import argparse
from dataclasses import asdict
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import subprocess

from moonkvsim.aegiskv.experiment import AIMD_PARAMETERS
from moonkvsim.aegiskv.hbm_quota_aimd import AIMDTargetState, HBMQuotaAIMD
from moonkvsim.aegiskv.recovery_harm import (
    AdmissionHarmDelta, RecoveryHarmSnapshot, RecoveryTimeBreakdown,
)
from moonkvsim.aegiskv.types import PolicyPool, SlackSignal

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--mooncake-root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    harness = Path(__file__).with_name('mooncake_controller_probe.cpp')
    native = args.mooncake_root / 'mooncake-store/src/aegiskv_controller.cpp'
    header = args.mooncake_root / 'mooncake-store/include/aegiskv_controller.h'
    binary = args.output_dir / 'controller-probe'
    command = ['g++', '-std=c++20', '-O2', '-pthread', '-I', str(header.parent),
               str(harness), str(native), '-o', str(binary)]
    subprocess.run(command, check=True)
    rng = random.Random(20260906)
    cases = [(1000,0,0,100,300), (1000,1200,0,100,300),
             (1000,1200,800,100,300), (1000,0,0,1200,1100)]
    cases += [tuple(rng.randint(0,2000) for _ in range(5)) for _ in range(256)]
    output = subprocess.run([str(binary)], input=''.join(
        ' '.join(map(str,c))+'\n' for c in cases), text=True,
        capture_output=True, check=True)
    rows = [json.loads(line) for line in output.stdout.splitlines()]
    assert len(rows) == len(cases)
    comparisons = []
    for values, actual in zip(cases, rows, strict=True):
        full, slack, elapsed, hbm, dram = values
        signal = SlackSignal(Fraction(slack),1000,1)
        def snapshot(pool, duration):
            return RecoveryHarmSnapshot('r',pool,1000+elapsed,signal,
                RecoveryTimeBreakdown(Fraction(duration),Fraction(0),Fraction(0)))
        expected = {}
        for name,pool,after in [('h',PolicyPool.PEER_HBM,hbm),
                                ('d',PolicyPool.STORE_DRAM,dram)]:
            gain = AdmissionHarmDelta(snapshot(pool,full),
                                      snapshot(pool,min(full,after))).gain_ns
            expected[name+'_gain'] = float(gain)
            expected[name+'_decision'] = (3 if name=='h' else 1) if gain>0 else 0
        expected['pending_harm'] = float(snapshot(PolicyPool.PEER_HBM,full).harm_ns)
        expected['harm'] = max(min(full,hbm,dram)-max(slack-elapsed,0),0)
        state = AIMDTargetState('hbm',1000,Decimal('.2'))
        controller = HBMQuotaAIMD(AIMD_PARAMETERS)
        quotas = []
        used = 100 if expected['h_decision']==3 else 0
        for i in range(6):
            decision = controller.update(state,foreground_pressure=i==4,
                current_protection_bytes=used,timestamp_ns=1000+elapsed+i+1)
            state = decision.next_state; quotas.append(decision.quota_bytes)
        expected['quotas'] = quotas
        # The C++ controller uses double; all test inputs are exact integers.
        assert actual == expected, (values, actual, expected)
        comparisons.append({'input':values,'native':actual,'simulator':expected})
    result = {'status':'PASS','case_count':len(cases),
              'checks':['tier-local independent gain','pending invisibility',
                        'zero/expired Slack','gain-zero bypass','six AIMD windows'],
              'scope':'policy arithmetic; not physical latency calibration',
              'command':command,'reference_sha256':{str(p):hashlib.sha256(
                  p.read_bytes()).hexdigest() for p in (native,header,harness)},
              'cases':comparisons}
    (args.output_dir/'alignment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(f'PASS: {len(cases)} native Controller differential cases')

if __name__ == '__main__':
    main()
