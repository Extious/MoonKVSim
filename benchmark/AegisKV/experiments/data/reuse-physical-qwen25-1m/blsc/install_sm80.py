"""Install CPU-built kernels into the task venv after architecture/ABI checks."""
from pathlib import Path
import collections,hashlib,json,os,re,shutil,subprocess,time
r=Path(__file__).resolve().parent.parent
work=r/'setup/sm80-build';assert (work/'BUILD_COMPLETE.json').exists()
site=r/'.venv/lib/python3.12/site-packages/sgl_kernel'
cuobjdump=r/'setup/cuda_cuobjdump-linux-sbsa-12.8.90-archive/bin/cuobjdump'
backup=work/'original-wheel';backup.mkdir(exist_ok=True)
records={}
for key,rel in [('flash-ops','flash_ops.abi3.so')]:
 source=work/'build'/rel;assert source.is_file(),source
 elves=subprocess.check_output([str(cuobjdump),'--list-elf',str(source)],text=True)
 counts=dict(collections.Counter(re.findall(r'sm_[0-9]+[a-z]?',elves)))
 assert counts.get('sm_80',0)>0,(rel,counts)
 dest=site/rel;old=backup/rel;old.parent.mkdir(parents=True,exist_ok=True)
 if not old.exists():shutil.copy2(dest,old)
 temp=dest.with_suffix('.installing');shutil.copy2(source,temp);temp.replace(dest)
 record={'library':str(dest),'library_sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),
         'architectures':counts,'source':'sm80-build/sources.json',
         'build_customization':'sm80-build/build-customization.json','checked_at':time.time()}
 (r/f'setup/{key}-elf-list.txt').write_text(elves)
 (r/f'setup/{key}-architecture.json').write_text(json.dumps(record,indent=2))
 records[key]=record
 print('INSTALLED',rel,counts,flush=True)
env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=''
env['LD_LIBRARY_PATH']=str(r/'setup/cuda-12.8/lib')+':/home/bingxing2/home/scx8q31/apps/cuda-compat-12.8/lib:'+env.get('LD_LIBRARY_PATH','')
code="import torch,sgl_kernel;from sgl_kernel.flash_attn import flash_attn_varlen_func,flash_attn_with_kvcache;from sglang.srt.layers.attention.dual_chunk_flashattention_backend import DualChunkFlashAttentionBackend; print('SM80_BINARY_CPU_IMPORTS_PASSED');print(sgl_kernel.common_ops.__file__)"
p=subprocess.run([str(r/'.venv/bin/python'),'-c',code],env=env,capture_output=True,text=True)
(r/'setup/sm80-import.log').write_text(p.stdout+p.stderr)
if p.returncode:
 for rel in ['flash_ops.abi3.so']:shutil.copy2(backup/rel,site/rel)
 raise RuntimeError('CPU imports failed; previous wheel restored: '+p.stderr[-5000:])
(r/'setup/sm80-ready.json').write_text(json.dumps({'passed':True,'libraries':records,'checked_at':time.time()},indent=2))
print(p.stdout)
