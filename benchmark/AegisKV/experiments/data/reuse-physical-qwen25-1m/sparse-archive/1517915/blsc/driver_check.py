"""Fast allocation checks before importing Torch or loading paid model state."""
import argparse
import csv
import ctypes
import json
from pathlib import Path
import socket
import subprocess
import sys
import time


def select_mode(rows, gpus):
    if len(rows) != gpus:
        raise ValueError(f'Expected {gpus} visible GPUs; got {len(rows)}')
    names = {row[0].strip() for row in rows}
    versions = {row[1].strip() for row in rows}
    memory = {int(row[2].strip()) for row in rows}
    if len(names) != 1 or not all('A100' in n for n in names):
        raise ValueError(f'Expected homogeneous A100 GPUs; got {names}')
    if len(versions) != 1 or len(memory) != 1 or min(memory) < 40000:
        raise ValueError('GPU driver/memory mismatch or insufficient device capacity')
    major = int(next(iter(versions)).split('.')[0])
    if major < 535:
        raise ValueError(f'Driver {major} is outside this CUDA 12.8 experiment configuration')
    return 'compat' if major < 570 else 'native'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--gpus', type=int, required=True)
    ap.add_argument('--cuda-init', action='store_true')
    args = ap.parse_args()
    record = {'host': socket.gethostname(), 'time': time.time(), 'passed': False}
    try:
        if args.cuda_init:
            driver = ctypes.CDLL('libcuda.so.1')
            error = driver.cuInit(0)
            record['cuInit_error'] = error
            if error != 0:
                raise RuntimeError(f'cuInit returned {error}')
            count = ctypes.c_int()
            error = driver.cuDeviceGetCount(ctypes.byref(count))
            record.update(cuDeviceGetCount_error=error, accessible_gpus=count.value)
            if error or count.value < args.gpus:
                raise RuntimeError('Insufficient accessible GPUs after CUDA initialization')
            mode = 'cuda_init_passed'
        else:
            result = subprocess.check_output([
                'nvidia-smi', '--query-gpu=name,driver_version,memory.total',
                '--format=csv,noheader,nounits'], text=True, timeout=10)
            rows = list(csv.reader(result.splitlines()))
            record['devices'] = rows
            mode = select_mode(rows, args.gpus)
            record['library_mode'] = mode
        record['passed'] = True
    except Exception as exc:
        record['error'] = str(exc)
    args.output.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record), file=sys.stderr, flush=True)
    if not record['passed']:
        raise SystemExit(86)
    print(mode, flush=True)


if __name__ == '__main__':
    main()
