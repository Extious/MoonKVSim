"""Build the pinned upstream sparse SM80 kernels without a GPU allocation.

Only the operator namespace and build target change. Installed SGLang binaries
remain untouched. All attention/index CUDA sources come from the existing,
revision-pinned source checkout used for the earlier dense build.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import shutil
import time


def main():
    root = Path(__file__).resolve().parent.parent
    source = root / "setup/sm80-build"
    sgl = source / "sglang/sgl-kernel"
    fa = source / "flash-attention"
    dest = root / "setup/sparse-sm80"
    dest.mkdir(parents=True, exist_ok=True)
    os.environ.update(CUDA_VISIBLE_DEVICES="", TORCH_CUDA_ARCH_LIST="8.0",
                      MAX_JOBS="2")
    import torch
    from torch.utils.cpp_extension import load
    assert not torch.cuda.is_initialized()
    extension = (sgl / "csrc/common_extension.cc").read_text()
    header = (sgl / "include/sgl_kernel_ops.h").read_text()
    declarations = header[header.index("namespace flash {"):header.index("/*\n * From csrc/grammar")]
    declarations = declarations.replace("namespace flash {", "namespace aegis_flash_sparse {")
    begin = extension.index('  m.def(\n      "fwd_sparse(')
    end = extension.index("  /*\n   * From csrc/grammar", begin)
    registrations = extension[begin:end].replace("&flash::", "&aegis_flash_sparse::")
    binding = dest / "bindings.cpp"
    binding.write_text("#include <torch/all.h>\n#include <torch/library.h>\n" + declarations
                       + "\nTORCH_LIBRARY(aegis_sparse, m) {\n" + registrations + "\n}\n")
    cuda = fa / "csrc/flash_attn/src"
    files = [binding, sgl / "csrc/attention/vertical_slash_index.cu",
             fa / "csrc/flash_attn/flash_sparse_api.cpp"]
    for dtype in ("bf16", "fp16"):
        for causal in ("", "_causal"):
            files.append(cuda / f"flash_fwd_sparse_hdim128_{dtype}{causal}_sm80.cu")
    # Sparse headers still contain literal flash:: qualifications as well as
    # FLASH_NAMESPACE. Rename both through build flags, preserving CUDA math.
    defines = ["-DFLASH_NAMESPACE=aegis_flash_sparse", "-Dflash=aegis_flash_sparse", "-DFLASHATTENTION_DISABLE_BACKWARD",
               "-DFLASHATTENTION_DISABLE_DROPOUT", "-DFLASHATTENTION_DISABLE_UNEVEN_K"]
    includes = [source / "cutlass/include", source / "cutlass/tools/util/include", cuda]
    assert all(p.exists() for p in files + includes), files + includes
    build = dest / "build"
    build.mkdir(exist_ok=True)
    start = time.time()
    load(name="aegis_sparse_ops", sources=[str(p) for p in files],
         extra_include_paths=[str(p) for p in includes],
         extra_cflags=["-O3", "-std=c++17", *defines],
         extra_cuda_cflags=["-O3", "-std=c++17", "--use_fast_math",
                           "-U__CUDA_NO_HALF_OPERATORS__", "-U__CUDA_NO_HALF_CONVERSIONS__",
                           "-U__CUDA_NO_BFLOAT16_CONVERSIONS__", "-U__CUDA_NO_HALF2_OPERATORS__",
                           "--expt-relaxed-constexpr", "--expt-extended-lambda", *defines],
         build_directory=str(build), with_cuda=True, is_python_module=False, verbose=True)
    assert not torch.cuda.is_initialized()
    library = build / "aegis_sparse_ops.so"
    candidates = [root/"setup/cuda-12.8/bin/cuobjdump",
                  *root.glob("setup/**/cuobjdump")]
    if shutil.which("cuobjdump"):
        candidates.append(Path(shutil.which("cuobjdump")))
    binary = next((p for p in candidates if p.is_file()), None)
    assert binary is not None, "cuobjdump needed for the CPU architecture gate"
    elf = subprocess.check_output([str(binary),
                                   "--list-elf", str(library)], text=True)
    assert "sm_80" in elf
    (dest / "elf.txt").write_text(elf)
    wrapper = sgl / "python/sgl_kernel/sparse_flash_attn.py"
    if not wrapper.exists():
        import sgl_kernel
        wrapper = Path(sgl_kernel.__file__).parent / "sparse_flash_attn.py"
    wrapper_text = wrapper.read_text().replace("torch.ops.sgl_kernel.", "torch.ops.aegis_sparse.")
    (dest / "sparse_wrapper.py").write_text(wrapper_text)
    manifest = {"cpu_build_only": True, "cuda_initialized": False,
                "library": str(library), "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
                "wrapper": str(dest / "sparse_wrapper.py"),
                "wrapper_sha256": hashlib.sha256(wrapper_text.encode()).hexdigest(),
                "source_sha256": {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                "namespace": "aegis_sparse", "architecture": "sm_80", "head_dim": 128,
                "dtypes": ["BF16", "FP16"], "cuda_sources_modified": False,
                "source_revisions": json.loads((source / "sources.json").read_text()),
                "build_seconds": time.time()-start, "torch": torch.__version__}
    (dest / "READY.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps(manifest), flush=True)


if __name__ == "__main__":
    main()
