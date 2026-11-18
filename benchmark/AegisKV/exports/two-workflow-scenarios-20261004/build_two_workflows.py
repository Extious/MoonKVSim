#!/usr/bin/env python3
"""Native workflow schematics, with continuous per-Agent invocation chains.

This figure specifies application dependencies; it is not a measured trace,
a GPU schedule, or evidence of application representativeness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

INK = '#243746'
EDGE = '#70808A'
TEAL = '#39756A'
MINT = '#E1EEE8'
BLUE = '#23688D'
PALE_BLUE = '#DDEBF3'
GRAY = '#F1F3F4'
AMBER = '#9B6428'
WARM = '#F3E5D1'
WIDTH, HEIGHT = 1080, 824

TEXT = {
    'zh': {
        'font': 'FandolSong',
        'titles': ('(a) W1：论文证据问答', '(b) W2：多文档新闻摘要'),
        'inputs': ('论文全文 + 研究问题', '多篇新闻 + 摘要要求'),
        'roles': (
            ('A：方法分析', 'B：实验\n与证据', 'C：局限\n与条件', 'D：证据整合\n与回答'),
            ('E：事件\n与时间线', 'F：来源\n与事实', 'G：事实对齐\n与冲突', 'H：摘要撰写\n与修订'),
        ),
        'chain': '同一 Agent 连续调用',
        'task': '输入 / 任务完成依赖',
        'prefix': '可复用历史 KV',
        'new': '本轮新增 KV',
        'parallel': 'W1：A/B/C 并行；W2：E/F 并行。小框编号表示同 Agent 连续调用。',
        'wait': 'D 等待全部\n分支任务完成',
        'scope': 'R 因 Agent 而异；链内无外部等待；图为构造的 DAG，并非实测时间线。',
    },
    'en': {
        'font': 'Linux Libertine O',
        'titles': ('(a) W1: Research-paper QA', '(b) W2: Multi-document summary'),
        'inputs': ('Full paper + research question', 'News documents + summary request'),
        'roles': (
            ('A: Methods', 'B: Experiments\nand evidence', 'C: Scope and\nlimitations', 'D: Evidence-grounded\nanswer'),
            ('E: Events\nand timeline', 'F: Sources\nand facts', 'G: Fact alignment\nand conflicts', 'H: Summary drafting\nand revision'),
        ),
        'chain': 'Continuous Agent calls',
        'task': 'Input / task dependencies',
        'prefix': 'Reusable history KV',
        'new': 'New KV',
        'parallel': 'W1: A/B/C in parallel; W2: E/F in parallel. Numbers denote consecutive Agent calls.',
        'wait': 'D waits for all\nthree branches',
        'scope': 'R varies by Agent; no external wait within chains. Constructed DAGs, not measured timelines.',
    },
}


class Drawing:
    def __init__(self, diagram: ET.Element, language: str):
        self.language = language
        self.font = TEXT[language]['font']
        model = ET.SubElement(diagram, 'mxGraphModel', grid='1', gridSize='10',
                              page='1', pageWidth=str(WIDTH), pageHeight=str(HEIGHT),
                              background='#FFFFFF')
        self.root = ET.SubElement(model, 'root')
        ET.SubElement(self.root, 'mxCell', id='0')
        ET.SubElement(self.root, 'mxCell', id='1', parent='0')

    def box(self, ident, value, x, y, w, h, *, parent='1', fill='#FFFFFF',
            stroke=EDGE, size=24, bold=False, extra=''):
        style = (
            f'rounded=1;arcSize=6;whiteSpace=wrap;html=0;'
            f'fontFamily={self.font};fontSize={size};fontColor={INK};'
            f'fontStyle={int(bold)};align=center;verticalAlign=middle;'
            f'fillColor={fill};strokeColor={stroke};strokeWidth=1.2;spacing=0;{extra}'
        )
        cell = ET.SubElement(self.root, 'mxCell', id=ident, value=value, style=style,
                             vertex='1', parent=parent)
        ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h),
                      **{'as': 'geometry'})
        return ident

    def text(self, ident, value, x, y, w, h, **kwargs):
        return self.box(ident, value, x, y, w, h, fill='none', stroke='none', **kwargs)

    def edge(self, ident, *, parent='1', source=None, target=None, points=(),
             color=INK, dashed=False, arrow='block', exit_xy=(1, .5), entry_xy=(0, .5)):
        style = (f'rounded=0;html=0;strokeColor={color};strokeWidth=1.6;'
                 f'endArrow={arrow};endSize=5;endFill=1;dashed={int(dashed)};dashPattern=5 3;')
        attrs = dict(id=ident, value='', edge='1', parent=parent)
        if source:
            attrs['source'] = source
            style += f'exitX={exit_xy[0]};exitY={exit_xy[1]};exitPerimeter=0;'
        if target:
            attrs['target'] = target
            style += f'entryX={entry_xy[0]};entryY={entry_xy[1]};entryPerimeter=0;'
        attrs['style'] = style
        cell = ET.SubElement(self.root, 'mxCell', **attrs)
        geom = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as': 'geometry'})
        if not source and points:
            ET.SubElement(geom, 'mxPoint', x=str(points[0][0]), y=str(points[0][1]), **{'as': 'sourcePoint'})
        if not target and points:
            ET.SubElement(geom, 'mxPoint', x=str(points[-1][0]), y=str(points[-1][1]), **{'as': 'targetPoint'})
        waypoints = points if source and target else points[1:-1]
        if waypoints:
            array = ET.SubElement(geom, 'Array', **{'as': 'points'})
            for x, y in waypoints:
                ET.SubElement(array, 'mxPoint', x=str(x), y=str(y))

    def kv(self, ident, center_x, y, prefix, new, parent):
        x = center_x - (prefix + new) / 2
        if prefix:
            self.box(ident + '-prefix', '', x, y, prefix, 12, parent=parent,
                     fill=MINT, stroke=TEAL, extra='rounded=0;')
        self.box(ident + '-new', '', x + prefix, y, new, 12, parent=parent,
                 fill=WARM, stroke=AMBER, extra='rounded=0;')
        for offset in range(7, new + 7, 7):
            end = min(offset, new)
            start = max(0, end - 6)
            self.edge(f'{ident}-hatch-{offset}', parent=parent,
                      points=((x + prefix + start, y + 12), (x + prefix + end, y)),
                      arrow='none', color=AMBER)

    def agent(self, workflow, letter, role, x, y, width=160, parent=None):
        lane = self.box(f'{workflow}-{letter}', '', x, y, width, 134,
                        parent=parent or workflow, fill='#FAFCFB',
                        extra='container=1;pointerEvents=0;')
        self.text(lane + '-title', role, 6, 2, width - 12, 58, parent=lane)
        offset = (width - 144) / 2
        positions = ((offset, 32), (offset + 40, 32),
                     (offset + 80, 24), (offset + 112, 32))
        suffixes = ('1', '2', 'dots', 'R')
        for (x, width), suffix in zip(positions, suffixes):
            value = '...' if suffix == 'dots' else suffix
            node = f'{lane}-{suffix}'
            self.box(node, value, x, 66, width, 34, parent=lane,
                     fill=MINT if suffix != 'dots' else 'none',
                     stroke=TEAL if suffix != 'dots' else 'none')
        for left, right in zip(suffixes, suffixes[1:]):
            self.edge(f'{lane}-{left}-to-{right}', parent=lane,
                      source=f'{lane}-{left}', target=f'{lane}-{right}', color=INK)
        # First call builds fresh KV; later calls extend an eligible prefix.
        self.kv(lane + '-kv-1', offset + 16, 114, 0, 20, lane)
        self.kv(lane + '-kv-2', offset + 56, 114, 20, 12, lane)
        self.kv(lane + '-kv-R', offset + 128, 114, 30, 12, lane)

    def panel(self, index):
        cfg = TEXT[self.language]
        workflow = f'w{index + 1}'
        left = 10 if index == 0 else 550
        self.box(workflow, '', left, 8, 520, 680, fill='#FFFFFF',
                 extra='container=1;pointerEvents=0;')
        self.text(workflow + '-title', cfg['titles'][index], 20, 3, 480, 34,
                  parent=workflow, size=27, bold=True)
        source = self.box(workflow + '-input', cfg['inputs'][index], 30, 45, 456, 36,
                          parent=workflow, fill=GRAY)
        letters = 'ABCD' if index == 0 else 'EFGH'
        initial = letters[:3] if index == 0 else letters[:2]
        parallel = self.box(workflow + '-parallel', '', 12, 154, 496, 152,
                            parent=workflow, fill=PALE_BLUE, stroke='none',
                            extra='container=1;pointerEvents=0;')
        initial_positions = (0, 168, 336) if index == 0 else (52, 284)
        for letter, x in zip(initial, initial_positions):
            self.agent(workflow, letter, cfg['roles'][index][letters.index(letter)],
                       x, 9, parent=parallel)
        fork = self.box(workflow + '-fork', '', 256, 116, 8, 8,
                        parent=workflow, fill=BLUE, stroke=BLUE,
                        extra='shape=ellipse;')
        self.edge(workflow + '-input-to-fork', parent=workflow, source=source,
                  target=fork, color=BLUE, dashed=True, arrow='none',
                  exit_xy=(.5, 1), entry_xy=(.5, 0))
        for letter, x in zip(initial, initial_positions):
            center = 12 + x + 80
            self.edge(f'{workflow}-fork-to-{letter}', parent=workflow, source=fork,
                      target=f'{workflow}-{letter}', color=BLUE, dashed=True,
                      exit_xy=(.5, .5), entry_xy=(.5, 0), points=((center, 120),))
        join_y = 336
        join = self.box(workflow + '-join', 'AND', 216, join_y - 25, 88, 50,
                        parent=workflow, fill=PALE_BLUE, stroke=BLUE,
                        extra='shape=rhombus;rounded=0;')
        for letter, x in zip(initial, initial_positions):
            center = 12 + x + 80
            entry = (.5, 0) if center == 260 else ((0, .5) if center < 260 else (1, .5))
            self.edge(f'{workflow}-{letter}-complete', parent=workflow,
                      source=f'{workflow}-{letter}', target=join, color=BLUE,
                      dashed=True, exit_xy=(.5, 1), entry_xy=entry,
                      points=() if center == 260 else ((center, join_y),))
        successor = letters[3] if index == 0 else letters[2]
        successor_y = 516 if index == 0 else 376
        self.agent(workflow, successor, cfg['roles'][index][letters.index(successor)],
                   130, successor_y, width=260)
        self.edge(f'{workflow}-join-to-{successor}', parent=workflow, source=join,
                  target=f'{workflow}-{successor}', color=BLUE, dashed=True,
                  exit_xy=(.5, 1), entry_xy=(.5, 0))
        if index == 0:
            self.text(workflow + '-wait-label', cfg['wait'], 281, 386, 220, 76,
                      parent=workflow, extra='align=left;')
        if index == 1:
            self.agent(workflow, 'H', cfg['roles'][index][3], 130, 524, width=260)
            self.edge('w2-G-complete-to-H', parent=workflow, source='w2-G', target='w2-H',
                      color=BLUE, dashed=True,
                      exit_xy=(.5, 1), entry_xy=(.5, 0))

    def legends(self):
        cfg = TEXT[self.language]
        self.text('parallel-and-number-rule', cfg['parallel'], 22, 690, 1036, 30)
        self.edge('legend-continuous', points=((24, 738), (67, 738)))
        self.text('legend-continuous-text', cfg['chain'], 76, 722, 425, 32,
                  extra='align=left;')
        self.edge('legend-task', points=((553, 738), (596, 738)), color=BLUE, dashed=True)
        self.text('legend-task-text', cfg['task'], 613, 722, 430, 32,
                  extra='align=left;')
        self.box('legend-prefix', '', 24, 767, 28, 13, fill=MINT, stroke=TEAL, extra='rounded=0;')
        self.text('legend-prefix-text', cfg['prefix'], 66, 758, 425, 32,
                  extra='align=left;')
        self.kv('legend-new', 567, 768, 0, 28, '1')
        self.text('legend-new-text', cfg['new'], 613, 758, 430, 32,
                  extra='align=left;')
        self.text('schematic-scope', cfg['scope'], 22, 792, 1036, 30)


def build(destination: Path):
    mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
    for language, name in (('zh', '两个 workflow（中文）'), ('en', 'Two workflows (paper)')):
        diagram = ET.SubElement(mx, 'diagram', id=f'two-workflows-{language}', name=name)
        drawing = Drawing(diagram, language)
        drawing.box('canvas', '', 0, 0, WIDTH, HEIGHT, stroke='none', extra='rounded=0;')
        drawing.panel(0)
        drawing.panel(1)
        drawing.legends()
    if hasattr(ET, 'indent'):
        ET.indent(mx)
    destination.parent.mkdir(parents=True, exist_ok=True)
    ET.ElementTree(mx).write(destination, encoding='utf-8', xml_declaration=True)

    manifest = {
        'evidence_level': 'constructed_application_schematic',
        'not_a_measured_trace': True,
        'continuity': {
            'one_active_invocation_per_agent': True,
            'next_invocation_ready_after_previous_completion_and_local_stop_check': True,
            'no_external_tool_or_other_agent_wait_inside_chain': True,
            'server_queue_delay_is_not_excluded': True,
            'history_is_agent_local_and_append_only': True,
            'kv_reuse_requires_actual_compatible_token_prefix': True,
        },
        'graph_semantics': {
            'outer_boxes': 'Agent tasks',
            'small_numbered_nodes': 'consecutive invocations of the enclosing Agent',
            'task_edges': 'successors wait for complete predecessor tasks',
            'join': 'AND: all required predecessors complete',
            'blue_regions': 'independent parallel branches; not measured time overlap',
        },
        'workflows': {
            'w1': {'agents': list('ABCD'), 'task_edges': [['A', 'D'], ['B', 'D'], ['C', 'D']], 'parallel_groups': [list('ABC')]},
            'w2': {'agents': list('EFGH'), 'task_edges': [['E', 'G'], ['F', 'G'], ['G', 'H']], 'parallel_groups': [list('EF')]},
        },
        'parallel_execution': {
            'launch_independent_branches_concurrently': True,
            'do_not_await_a_branch_before_launching_its_siblings': True,
            'at_least_two_independent_dp_workers_for_execution_overlap': True,
            'three_workers_if_w1_requires_all_three_branches_to_execute_simultaneously': True,
            'runtime_overlap_validation': 'measure service intervals and worker identities; DAG readiness alone is insufficient',
            'slack_is_not_guaranteed_by_dag_shape': True,
        },
        'invocation_count': 'R is Agent-specific and unknown before execution',
        'kv_bar_widths': 'schematic; not token or byte measurements',
        'target_width_mm': 168,
    }
    destination.with_name('scenario-contract.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    build(parser.parse_args().output)
