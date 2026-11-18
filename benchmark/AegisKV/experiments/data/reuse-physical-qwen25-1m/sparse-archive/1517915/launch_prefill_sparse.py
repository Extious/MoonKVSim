"""Spawn the two matched sparse Prefill workers in one Slurm allocation."""
import os
import socket


def worker(rank, world, port):
    os.environ.update(RANK=str(rank), LOCAL_RANK=str(rank), WORLD_SIZE=str(world),
                      MASTER_ADDR="127.0.0.1", MASTER_PORT=str(port))
    import runpy
    runpy.run_module("measure_prefill_sparse", run_name="__main__")


if __name__ == "__main__":
    import torch.multiprocessing as mp
    world = int(os.environ.get("TP", "2"))
    assert world == 2
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    mp.spawn(worker, args=(world, port), nprocs=world, join=True)
