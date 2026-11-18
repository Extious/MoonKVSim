"""Freeze new public task materials; never read historical experiment output."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import urllib.request

ROOT = Path(__file__).resolve().parent
AEGIS = ROOT.parents[1]
INPUTS = ROOT / 'inputs'
INPUTS.mkdir(exist_ok=True)
records = []


def fetch(url, name):
    req = urllib.request.Request(url, headers={'User-Agent':'AegisKV-research-input-capture'})
    with urllib.request.urlopen(req, timeout=40) as response:
        data = response.read()
    p = INPUTS / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    records.append({'path':name,'url':url,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                    'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    return p


def main():
    queries = [json.loads(x) for x in (AEGIS / 'docs/workload-decision-20261004/sources/deepresearch_bench_queries.jsonl').read_text().splitlines()]
    query = next(x for x in queries if x['id'] == 66)
    materials = []
    for name, repo in [('projects','obsmd-projects/obsidian-projects'),('db-folder','RafaelGB/obsidian-db-folder'),
                       ('dataview','blacksmithgu/obsidian-dataview')]:
        meta = json.loads(fetch(f'https://api.github.com/repos/{repo}/commits/HEAD', f'metadata/{name}-commit.json').read_text())
        commit = meta['sha']
        path = fetch(f'https://raw.githubusercontent.com/{repo}/{commit}/README.md', f'research/{name}-README.md')
        materials.append({'id':name,'path':str(path.relative_to(ROOT)),'commit':commit})
    # The source subset is frozen before observing timing or recovery outcomes.
    (INPUTS / 'research-task.json').write_text(json.dumps({'task_id':'DRB-66','application':'research',
        'source':'DeepResearchBench query 66','original_prompt':query['prompt'],
        'scope':'Compare supplied plugin documents against Table, Kanban, Calendar, and List requirements; mark unverified features and omitted alternatives.',
        'materials':materials,'material_selection':'Three established candidate projects, chosen from task requirements before model execution; pilot source subset, not exhaustive market research.'},indent=2)+'\n')
    task = json.loads((AEGIS / 'docs/workload-decision-20261004/sources/swebench_verified_task_sample.json').read_text())
    base = f'https://raw.githubusercontent.com/{task["repo"]}/{task["base_commit"]}'
    paths = []
    for name in ['astropy/modeling/separable.py','astropy/modeling/tests/test_separable.py','astropy/modeling/core.py','docs/modeling/compound-models.rst']:
        paths.append(fetch(f'{base}/{name}', f'review/{name}'))
    core = paths[2]
    text = core.read_text(); lines = text.splitlines(keepends=True)
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='CompoundModel')
    snippets = []
    for n in cls.body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name in ['__init__','inputs','outputs','_evaluate','evaluate']:
            snippets.append(f'Original core.py lines {n.lineno}-{n.end_lineno}:\n'+''.join(lines[n.lineno-1:n.end_lineno]))
    selected = INPUTS / 'review/compound-model-core-excerpts.txt'
    selected.write_text('\n\n'.join(snippets))
    task.update(application='review', task_id=task['instance_id'],
        scope='Analyze cause and propose changes/tests from the pre-fix snapshot. Do not apply or read the benchmark solution patch.',
        materials=[{'id':'separable','path':str(paths[0].relative_to(ROOT))},
                   {'id':'tests','path':str(paths[1].relative_to(ROOT))},
                   {'id':'core-excerpts','path':str(selected.relative_to(ROOT))},
                   {'id':'compound-docs','path':str(paths[3].relative_to(ROOT))}],
        material_selection='Issue-named module, existing tests, documented CompoundModel semantics, and named pre-fix CompoundModel functions. Exact source lines retained.')
    (INPUTS / 'review-task.json').write_text(json.dumps(task,indent=2)+'\n')
    (INPUTS / 'SOURCE_MANIFEST.json').write_text(json.dumps(records,indent=2)+'\n')
    for name in ['research-task.json','review-task.json']:
        print(name, (INPUTS/name).stat().st_size)
    print('Frozen public files:',len(records))


if __name__ == '__main__':
    main()
