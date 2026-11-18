"""Two-GPU layer placement; native attention inside each layer is unchanged."""
import os
import subprocess
import torch


def device_map(rotary=False):
    assert torch.cuda.device_count() == 2, 'This capture needs exactly two allocated GPUs'
    result = {'model.embed_tokens': 'cuda:0', 'model.norm': 'cuda:1', 'lm_head': 'cuda:1'}
    result.update({f'model.layers.{i}': f'cuda:{int(i >= 16)}' for i in range(32)})
    if rotary:
        result['model.rotary_emb'] = 'cuda:0'
    return result


def gpu_snapshot():
    rows = subprocess.check_output([
        'nvidia-smi', '--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory',
        '--format=csv,noheader,nounits'], text=True).splitlines()
    devices = []
    assert torch.cuda.device_count() == 2
    for i in range(2):
        props = torch.cuda.get_device_properties(i)
        uuid = str(props.uuid)
        if not uuid.startswith('GPU-'):
            uuid = 'GPU-' + uuid
        foreign = [r for r in rows if r.split(',')[0].strip() == uuid
                   and int(r.split(',')[1].strip()) != os.getpid()]
        assert not foreign, f'Foreign processes on assigned GPU {i}; refusing to interfere'
        devices.append(dict(index=i, uuid=uuid, name=props.name,
                            total_bytes=props.total_memory, foreign_processes=foreign))
    return dict(pid=os.getpid(), devices=devices, compute_processes=rows)
