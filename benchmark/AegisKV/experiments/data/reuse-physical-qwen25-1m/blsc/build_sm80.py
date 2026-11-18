"""CPU-only matching-source SM80 rebuild; no GPU allocation or base-env mutation."""
from pathlib import Path
import concurrent.futures,hashlib,json,os,re,shutil,socket,subprocess,tarfile,time,urllib.request
root=Path(__file__).resolve().parent.parent
work=root/'setup/sm80-build';work.mkdir(parents=True,exist_ok=True)
(work/'process.json').write_text(json.dumps({'hostname':socket.gethostname(),'pid':os.getpid(),'started':time.time()}))
versions={'sglang':('sgl-project/sglang','9b0c470a6a13bedc860c6836f5d07b6c2f62e61a'),'cutlass':('NVIDIA/cutlass','57e3cfb47a2d9e0d46eb6335c3dc411498efa198'),'flash-attention':('sgl-project/sgl-attn','bcf72ccc6816b36a5fae2c5a3c027604629785e0'),'flashinfer':('flashinfer-ai/flashinfer','bc29697ba20b7e6bdb728ded98f04788e16ee021'),'mscclpp':('microsoft/mscclpp','51eca89d20f0cfb3764ccd764338d7b22cd486a6'),'fmt':('fmtlib/fmt','553ec11ec06fbe0beebfbb45f9dc3c9eabd83d28'),'json':('nlohmann/json','v3.11.3')}
def fetch(item):
 name,(repo,revision)=item;archive=work/(name+'.tar.gz');dest=work/name
 url=f'https://codeload.github.com/{repo}/tar.gz/{revision}'
 if not archive.exists():
  with urllib.request.urlopen(url,timeout=120) as r,archive.with_suffix('.tmp').open('wb') as f:shutil.copyfileobj(r,f)
  archive.with_suffix('.tmp').replace(archive)
 if not dest.exists():
  with tarfile.open(archive) as tf:
   prefix=tf.getmembers()[0].name.split('/')[0];tf.extractall(work/'extract',filter='data')
  (work/'extract'/prefix).rename(dest)
 print('SOURCE_READY',name,flush=True)
 return name,{'repository':repo,'revision':revision,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'url':url}
records=dict(concurrent.futures.ThreadPoolExecutor(max_workers=3).map(fetch,versions.items()))
(work/'sources.json').write_text(json.dumps(records,indent=2))
venv=root/'.venv';cuda=root/'setup/cuda-12.8';env=os.environ.copy()
env.update(CUDA_HOME=str(cuda),CUDA_PATH=str(cuda),CUDACXX=str(cuda/'bin/nvcc'),PATH=str(venv/'bin')+':'+str(cuda/'bin')+':'+env['PATH'],MAX_JOBS='4',TORCH_CUDA_ARCH_LIST='8.0;9.0a',CMAKE_BUILD_PARALLEL_LEVEL='4')
nvidia=Path('/home/bingxing2/home/scx8q31/miniconda3/envs/megatron-reft/lib/python3.12/site-packages/nvidia')
# Expose already-installed CUDA 12.8 library headers and link names to CMake.
for family in sorted(nvidia.iterdir()):
 for kind in ['include','lib']:
  source=family/kind
  if source.is_dir():
   for entry in source.iterdir():
    dest=cuda/kind/entry.name
    if not dest.exists() and not dest.is_symlink():dest.symlink_to(entry)
for entry in sorted((cuda/'lib').glob('lib*.so.*')):
 dest=cuda/'lib'/(entry.name.split('.so.')[0]+'.so')
 if not dest.exists() and not dest.is_symlink():dest.symlink_to(entry)
for key in ['CPATH','C_INCLUDE_PATH','CPLUS_INCLUDE_PATH']:env[key]=':'.join(map(str,[cuda/'include',*sorted(nvidia.glob('*/include'))]))
libs=[cuda/'lib',cuda/'lib/stubs',*sorted(nvidia.glob('*/lib'))]
env['LIBRARY_PATH']=':'.join(map(str,libs));env['LD_LIBRARY_PATH']=':'.join(map(str,libs))+':/home/bingxing2/home/scx8q31/apps/cuda-compat-12.8/lib:'+env.get('LD_LIBRARY_PATH','')
subprocess.run([str(venv/'bin/python'),'-m','pip','install','--index-url','https://pypi.tuna.tsinghua.edu.cn/simple','cmake==3.31.10'],env=env,check=True)
src=work/'sglang/sgl-kernel';original=(src/('CMakeLists.upstream.txt' if (src/'CMakeLists.upstream.txt').exists() else 'CMakeLists.txt')).read_text()
# Omit unrelated optional extensions and unused source fetches. Numerical sources are unchanged.
cm=original.split('# Build spatial_ops')[0]
for name in ['deepgemm','triton']:
 cm=re.sub(r'FetchContent_Declare\(\s*repo-'+name+r'\b.*?FetchContent_Populate\(repo-'+name+r'\)', '',cm,flags=re.S)
# Keep upstream source coverage and valid Hopper/Blackwell compile targets; omit duplicate architectures.
cm=re.sub(r'^\s*"-gencode=arch=compute_(?:86|87|89|101a|120a),code=sm_(?:86|87|89|101a|120a)"\s*$', '',cm,flags=re.M)
# Compile only this experiment's BF16/head-dimension-128 FA specializations.
# Use the upstream feature switches; do not alter the kernel implementation.
cm=cm.replace('set(FA3_GEN_SRCS ${FA3_BF16_GEN_SRCS} ${FA3_FP16_GEN_SRCS} ${FA3_FP8_GEN_SRCS} ${FA3_SM8X_GEN_SRCS})', '''file(GLOB AEGIS_FA_SRCS
        "${repo-flash-attention_SOURCE_DIR}/hopper/instantiations/flash_fwd_hdim128_bf16*_sm80.cu"
        "${repo-flash-attention_SOURCE_DIR}/hopper/instantiations/flash_fwd_hdim128_bf16*_sm90.cu")
    set(FA3_GEN_SRCS ${AEGIS_FA_SRCS})''')
cm=cm.replace('set(FLASH_OPS_COMPILE_DEFS', '''set(FLASH_OPS_COMPILE_DEFS
        FLASHATTENTION_DISABLE_FP16
        FLASHATTENTION_DISABLE_FP8
        FLASHATTENTION_DISABLE_HDIM64
        FLASHATTENTION_DISABLE_HDIM96
        FLASHATTENTION_DISABLE_HDIM192
        FLASHATTENTION_DISABLE_HDIM256''')
(src/'CMakeLists.upstream.txt').write_text(original);(src/'CMakeLists.txt').write_text(cm)
(work/'build-customization.json').write_text(json.dumps({'purpose':'Add official SM80 support to ARM64 wheel','enable_below_sm90':True,'numerical_source_changes':False,'flash_attention_specializations':'BF16 head_dim 128; upstream disable flags for other dtypes/head dimensions','upstream_cmake_sha256':hashlib.sha256(original.encode()).hexdigest(),'build_cmake_sha256':hashlib.sha256(cm.encode()).hexdigest(),'targets':['flash_ops'],'jobs':4},indent=2))
cmd=[str(venv/'bin/cmake'),'-S',str(src),'-B',str(work/'build'),'-G','Ninja','-DMSCCLPP_BUILD_PYTHON_BINDINGS=OFF','-DMSCCLPP_BUILD_APPS_NCCL=OFF','-DFETCHCONTENT_SOURCE_DIR_JSON='+str(work/'json'),'-DCUDA_NVRTC_LIB='+str(cuda/'lib/libnvrtc.so'),'-DCUDA_nvrtc_LIBRARY='+str(cuda/'lib/libnvrtc.so'),'-DCMAKE_BUILD_TYPE=Release','-DENABLE_BELOW_SM90=ON','-DSGL_KERNEL_COMPILE_THREADS=1','-DCMAKE_CUDA_ARCHITECTURES=80','-DSKBUILD_SABI_VERSION=3.9','-DSKBUILD_SABI_COMPONENT=Development.SABIModule','-DPython_EXECUTABLE='+str(venv/'bin/python'),'-DPython3_EXECUTABLE='+str(venv/'bin/python'),'-DCMAKE_PREFIX_PATH=/home/bingxing2/home/scx8q31/miniconda3/envs/megatron-reft/lib/python3.12/site-packages/torch/share/cmake']
for name in versions:
 if name!='sglang':cmd.append('-DFETCHCONTENT_SOURCE_DIR_REPO-'+name.upper()+'='+str(work/name))
subprocess.run(cmd,env=env,check=True)
subprocess.run([str(venv/'bin/cmake'),'--build',str(work/'build'),'--target','flash_ops','--parallel','4'],env=env,check=True)
(work/'BUILD_COMPLETE.json').write_text(json.dumps({'finished':time.time(),'installed':False}))
