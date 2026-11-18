import subprocess,json,pathlib,time
r=pathlib.Path('/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919/setup')
p=subprocess.run(['/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919/.venv/bin/python', '-m', 'pip', 'install', '--index-url', 'https://pypi.tuna.tsinghua.edu.cn/simple', '--cache-dir', '/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919/setup/pip-cache', '--only-binary=:all:', '--no-binary=torch-memory-saver', '-c', '/home/bingxing2/home/scx8q31/aegiskv_reuse_qwen25_1m_20260919/setup/constraints.txt', 'sglang==0.5.10rc0'])
(r/'pip-result.json').write_text(json.dumps({'exit_code':p.returncode,'finished_at':time.time()}))
