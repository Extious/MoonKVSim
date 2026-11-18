#!/usr/bin/env python3
"""Two business application DAGs with shared inputs and local readiness.

Only Agent nodes and task dependencies are drawn; the topology is a proposed design.
There is no captured application trace or measured performance here.
"""
from pathlib import Path
import argparse
import importlib.util
import json
import xml.etree.ElementTree as ET

BASE_PATH = Path(__file__).resolve().parent.parent / 'two-workflow-scenarios-20261004/build_two_workflows.py'
spec = importlib.util.spec_from_file_location('workflow_drawing_base', BASE_PATH)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

WIDTH, HEIGHT = 1080, 426
POSITIONS = (
    {'A': (12, 60), 'B': (180, 60), 'C': (348, 60),
     'D': (12, 156), 'E': (348, 156), 'F': (12, 252), 'G': (180, 348)},
    {'H': (12, 60), 'I': (180, 60), 'J': (348, 60),
     'K': (12, 156), 'L': (348, 156), 'M': (12, 252),
     'N': (348, 252), 'O': (180, 348)},
)
EDGES = (
    [('A', 'D'), ('B', 'D'), ('B', 'E'), ('C', 'E'),
     ('D', 'F'), ('C', 'F'), ('F', 'G'), ('E', 'G')],
    [('H', 'K'), ('I', 'K'), ('I', 'L'), ('J', 'L'),
     ('K', 'M'), ('J', 'M'), ('K', 'N'), ('L', 'N'),
     ('M', 'O'), ('N', 'O')],
)
TEXT = {'zh': {'titles': ('(a) 软件采购选型', '(b) 新品发布营销'), 'roles': ({'A': 'A：需求分析', 'B': 'B：产品比较', 'C': 'C：安全约束', 'D': 'D：需求匹配', 'E': 'E：风险审查', 'F': 'F：选型草案', 'G': 'G：决策报告'}, {'H': 'H：产品卖点', 'I': 'I：客群分析', 'J': 'J：品牌规范', 'K': 'K：传播主题', 'L': 'L：渠道策略', 'M': 'M：渠道文案', 'N': 'N：活动排期', 'O': 'O：交付编辑'})}, 'en': {'titles': ('(a) Software procurement', '(b) Product launch'), 'roles': ({'A': 'A: Needs', 'B': 'B: Products', 'C': 'C: Security', 'D': 'D: Fit', 'E': 'E: Risks', 'F': 'F: Shortlist', 'G': 'G: Decision'}, {'H': 'H: Benefits', 'I': 'I: Audience', 'J': 'J: Brand', 'K': 'K: Messages', 'L': 'L: Channels', 'M': 'M: Copy', 'N': 'N: Schedule', 'O': 'O: Package'})}}


class ComplexDrawing(base.Drawing):
    def __init__(self, diagram, language):
        super().__init__(diagram, language)
        diagram.find('mxGraphModel').set('pageHeight', str(HEIGHT))

    def agent_task(self, workflow, letter, role, x, y):
        self.box(f'{workflow}-{letter}', role, x, y, 160, 48,
                 parent=workflow, fill=base.MINT, stroke=base.TEAL)

    def dependency(self, workflow, first, second, *, skip=False, **routing):
        ident = f'{workflow}-{first}-complete-to-{second}'
        self.edge(ident, parent=workflow, source=f'{workflow}-{first}',
                  target=f'{workflow}-{second}', color=base.INK, **routing)
        cell = self.root[-1]
        cell.set('style', cell.get('style') + 'jumpStyle=arc;jumpSize=10;')

    def panel(self, index):
        cfg = TEXT[self.language]
        workflow = f'w{index + 1}'
        self.box(workflow, '', 10 if index == 0 else 550, 8, 520, 410,
                 fill='none', stroke='none', extra='container=1;pointerEvents=0;')
        self.text(workflow + '-title', cfg['titles'][index], 20, 3, 480, 34,
                  parent=workflow, size=27, bold=True)
        for letter, (x, y) in POSITIONS[index].items():
            self.agent_task(workflow, letter, cfg['roles'][index][letter], x, y)
        initial = 'ABC' if index == 0 else 'HIJ'

        left, middle, right = initial
        next_left, next_right = ('D', 'E') if index == 0 else ('K', 'L')
        self.dependency(workflow, left, next_left, exit_xy=(.5, 1), entry_xy=(.5, 0))
        self.dependency(workflow, middle, next_left, exit_xy=(.25, 1), entry_xy=(.85, 0),
                        points=((220, 138), (148, 138)))
        self.dependency(workflow, middle, next_right, exit_xy=(.75, 1), entry_xy=(.15, 0),
                        points=((300, 138), (372, 138)))
        self.dependency(workflow, right, next_right, exit_xy=(.5, 1), entry_xy=(.5, 0))
        third_left = 'F' if index == 0 else 'M'
        self.dependency(workflow, next_left, third_left, exit_xy=(.5, 1), entry_xy=(.5, 0))
        self.dependency(workflow, right, third_left, skip=True,
                        exit_xy=(1, .5), entry_xy=(.8, 0),
                        points=((518, 84), (518, 240), (140, 240)))
        if index == 0:
            self.dependency(workflow, 'E', 'G', skip=True,
                            exit_xy=(.5, 1), entry_xy=(.85, 0),
                            points=((428, 330), (316, 330)))
            self.dependency(workflow, 'F', 'G', exit_xy=(.5, 1), entry_xy=(.15, 0),
                            points=((92, 330), (204, 330)))
        else:
            self.dependency(workflow, 'K', 'N', exit_xy=(.8, 1), entry_xy=(.2, 0),
                            points=((140, 228), (380, 228)))
            self.dependency(workflow, 'L', 'N', exit_xy=(.5, 1), entry_xy=(.5, 0))
            self.dependency(workflow, 'M', 'O', exit_xy=(.5, 1), entry_xy=(.15, 0),
                            points=((92, 330), (204, 330)))
            self.dependency(workflow, 'N', 'O', exit_xy=(.5, 1), entry_xy=(.85, 0),
                            points=((428, 330), (316, 330)))


def build(destination):
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    for language, name in [('zh', 'Agent 依赖关系（中文）'), ('en', 'Agent dependencies (paper)')]:
        page = ET.SubElement(mx, 'diagram', id='complex-workflows-' + language, name=name)
        drawing = ComplexDrawing(page, language)
        drawing.box('canvas', '', 0, 0, WIDTH, HEIGHT, stroke='none', extra='rounded=0;')
        drawing.panel(0)
        drawing.panel(1)
    if hasattr(ET, 'indent'):
        ET.indent(mx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(mx).write(destination, encoding='utf-8', xml_declaration=True)
    contract = {
        'evidence_level': 'constructed_application_design',
        'implemented_or_measured': False,
        'request_templates_materialized': True,
        'application_spec': '../../../docs/business-workflows-20261004/application-spec.json',
        'target_width_mm': 168,
        'diagram_scope': 'Agent nodes and task-completion dependencies only',
        'task_semantics': 'one complete Agent task per node; all incoming predecessors must complete',
        'invocation_semantics': 'not drawn; role-specific consecutive calls and optional repairs defined in the application spec',
        'history_semantics': 'Agent-local append-only history; compatible token prefix and KV residency must be measured',
        'readiness': 'launch a task once its own predecessors complete; no barrier across a full drawn layer',
        'tools': 'none inside Agent invocation chains',
        'workflows': {
            'w1': {'agents': list(POSITIONS[0]), 'task_edges': EDGES[0],
                   'source_parallel_set': list('ABC'),
                   'cross_layer_edges': [['C', 'F'], ['E', 'G']],
                   'additional_incomparable_pairs': [['D', 'C'], ['E', 'F']],
                   'final_agent': 'G'},
            'w2': {'agents': list(POSITIONS[1]), 'task_edges': EDGES[1],
                   'source_parallel_set': list('HIJ'),
                   'cross_layer_edges': [['J', 'M']],
                   'additional_incomparable_pairs': [['K', 'L'], ['M', 'L'], ['M', 'N']],
                   'final_agent': 'O'},
        },
        'execution_limits': 'dependency independence permits overlap; serving resources and framework synchronization must be verified',
        'no_claim_of_positive_slack_or_application_representativeness': True,
        'provenance': {'exact_roles_counts_and_edges': 'authored_in_this_project',
                       'public_sources_support': 'application categories and collaboration patterns',
                       'source_audit': '../../../docs/business-workflows-20261004/README.md',
                       'exact_topology_and_runtime_representativeness_established': False},
    }
    destination.with_name('scenario-contract.json').write_text(json.dumps(contract, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
