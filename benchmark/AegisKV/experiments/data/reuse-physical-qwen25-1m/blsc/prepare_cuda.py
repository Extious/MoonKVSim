"""Install verified NVIDIA redistributable tools and compile kernels on CPU."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,tarfile,time,urllib.request
root=Path(__file__).resolve().parent.parent
setup=root/'setup';cuda=setup/'cuda-12.8';downloads=setup/'cuda-downloads';downloads.mkdir(exist_ok=True)
base='https://developer.download.nvidia.com/compute/cuda/redist/'
manifest=json.load(urllib.request.urlopen(base+'redistrib_12.8.1.json',timeout=30))
(setup/'cuda-redistribution-manifest.json').write_text(json.dumps(manifest,indent=2))
for name in ['cuda_nvcc','cuda_cudart','cuda_cccl']:
 entry=manifest[name]['linux-sbsa'];archive=downloads/Path(entry['relative_path']).name
 if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=entry['sha256']:
  with urllib.request.urlopen(base+entry['relative_path'],timeout=90) as response,archive.open('wb') as f:shutil.copyfileobj(response,f)
 assert archive.stat().st_size==int(entry['size'])
 assert hashlib.sha256(archive.read_bytes()).hexdigest()==entry['sha256']
 with tarfile.open(archive) as tf:tf.extractall(downloads,filter='data')
 extracted=downloads/archive.name.removesuffix('.tar.xz')
 for link in extracted.rglob('*'):
  if link.is_symlink():
   dest=cuda/link.relative_to(extracted)
   if dest.is_symlink():
    assert os.readlink(dest)==os.readlink(link)
    dest.unlink()
 shutil.copytree(extracted,cuda,dirs_exist_ok=True,symlinks=True)
 print('VERIFIED_INSTALLED',name,flush=True)
compat=Path('/home/bingxing2/home/scx8q31/apps/cuda-compat-12.8/lib')
assert (compat/'libcuda.so.1').is_file()
stub=cuda/'lib/stubs/libcuda.so';stub.parent.mkdir(parents=True,exist_ok=True)
if not stub.exists():stub.symlink_to(compat/'libcuda.so.1')
if not (cuda/'lib64').exists():(cuda/'lib64').symlink_to('lib')
env=os.environ.copy();env.update(CUDA_HOME=str(cuda),PATH=str(root/'.venv/bin')+':'+str(cuda/'bin')+':'+env['PATH'],FLASHINFER_CUDA_ARCH_LIST='8.0',FLASHINFER_WORKSPACE_BASE=str(setup/'flashinfer'),MAX_JOBS='4')
nvidia_root=Path('/home/bingxing2/home/scx8q31/miniconda3/envs/megatron-reft/lib/python3.12/site-packages/nvidia')
assert (nvidia_root/'cublas/include/cublasLt.h').is_file()
assert (nvidia_root/'curand/include/curand_kernel.h').is_file()
includes=[cuda/'include',*sorted(nvidia_root.glob('*/include'))]
for key in ['CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH']:
 env[key]=':'.join(map(str,includes))
env['LIBRARY_PATH']=str(cuda/'lib')
env['CUDA_PATH']=str(cuda)
env['LD_LIBRARY_PATH']=str(cuda/'lib')+':/home/bingxing2/home/scx8q31/apps/cuda-compat-12.8/lib:'+env.get('LD_LIBRARY_PATH','')
subprocess.run([str(cuda/'bin/nvcc'),'--version'],check=True,env=env)
subprocess.run([str(root/'.venv/bin/ninja'),'--version'],check=True,env=env)
code="from flashinfer.jit.norm import gen_norm_module; gen_norm_module().build_and_load(); from flashinfer.jit.activation import gen_act_and_mul_module; gen_act_and_mul_module('silu').build_and_load(); print('CPU_KERNEL_BUILD_AND_LOAD_PASSED',flush=True)"
subprocess.run([str(root/'.venv/bin/python'),'-u','-c',code],check=True,env=env)
(setup/'cuda-ready.json').write_text(json.dumps({'passed':True,'time':time.time(),'cuda_home':str(cuda),'arch':'8.0','compiled':['norm','silu_and_mul'],'manifest':'cuda-redistribution-manifest.json'},indent=2))
