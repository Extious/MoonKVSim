#!/usr/bin/env python3
"""Export native Draw.io assets without opening or changing the manuscript."""
from pathlib import Path
import argparse
import os
import subprocess


def render(language, formats):
    root = Path(__file__).resolve().parent
    source = root / 'sources/two-workflow-scenarios.drawio'
    cli = '/home/comp/zhanzhao/.codex/skills/drawio/scripts/drawio-cli'
    env = dict(os.environ, FONTCONFIG_FILE=str(root / 'fontconfig.conf'))
    index = '1' if language == 'zh' else '2'
    for fmt in formats:
        target = root / f'two-workflow-scenarios-{language}.drawio.{fmt}'
        args = [cli, '-x', '-f', fmt, '-e', '-p', index, '-b', '0', '-o', str(target)]
        args += ['--crop'] if fmt == 'pdf' else []
        args += ['-s', '2'] if fmt == 'png' else []
        result = subprocess.run(args + [str(source)], env=env, capture_output=True, text=True, timeout=90)
        (root / f'export-{language}-{fmt}.log').write_text(result.stdout + result.stderr)
        if result.returncode or not target.is_file():
            raise RuntimeError(f'Export failed: {language}/{fmt}; see export log')
        print(target.name, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--language', choices=('zh', 'en'), required=True)
    parser.add_argument('--formats', nargs='+', choices=('png', 'svg', 'pdf'), default=['png', 'svg', 'pdf'])
    options = parser.parse_args()
    render(options.language, options.formats)
