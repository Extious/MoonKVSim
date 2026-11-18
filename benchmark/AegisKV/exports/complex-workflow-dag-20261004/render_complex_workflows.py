#!/usr/bin/env python3
"""Render native sources without opening or modifying the manuscript."""
from pathlib import Path
import argparse
import os
import subprocess


def render(language, formats):
    root = Path(__file__).resolve().parent
    source = root / 'sources/complex-workflow-dag.drawio'
    env = dict(os.environ, FONTCONFIG_FILE=str(root / 'fontconfig.conf'))
    for fmt in formats:
        target = root / f'complex-workflow-dag-{language}.drawio.{fmt}'
        args = ['/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli',
                '-x', '-f', fmt, '-e', '-p', '1' if language == 'zh' else '2',
                '-b', '0', '-o', str(target)]
        args += ['--crop'] if fmt == 'pdf' else []
        args += ['-s', '2'] if fmt == 'png' else []
        result = subprocess.run(args + [str(source)], env=env, capture_output=True,
                                text=True, timeout=90)
        (root / f'export-{language}-{fmt}.log').write_text(result.stdout + result.stderr)
        if result.returncode or not target.is_file():
            raise RuntimeError(f'Export failed: {language}/{fmt}; inspect export log')
        print(target.name, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=('zh', 'en'), required=True)
    parser.add_argument('--formats', nargs='+', choices=('png', 'pdf', 'svg'), default=['png', 'pdf', 'svg'])
    args = parser.parse_args()
    render(args.language, args.formats)
