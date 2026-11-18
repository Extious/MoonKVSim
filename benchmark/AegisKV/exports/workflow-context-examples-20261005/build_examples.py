"""Two editable, trace-grounded Agent/context examples; no manuscript mutation."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent
AEGIS = ROOT.parents[1]
CAPTURE = AEGIS / 'experiments/workflow-motivation-20261005/runs/capture-163125'
INPUTS = AEGIS / 'experiments/workflow-motivation-20261005/inputs'
WIDTH, HEIGHT = 1536, 1330
CARD_W, CARD_H = 320, 310
FONT = 'Noto Sans CJK SC'
INK, EDGE = '#243746', '#637783'
COLORS = {'source': ('#E1EEE8', '#39756A'), 'analysis': ('#DDEBF3', '#23688D'), 'final': ('#F3E5D1', '#9B6428')}

SPEC = {
    'research': {
        'name': 'research-context-example',
        'title': '研究报告 workflow：Obsidian 插件比较',
        'question': 'Q：哪些插件可实现 Notion 式 Table / Kanban / Calendar / List 多视图？比较各自优缺点。',
        'source': '公开任务 DRB-66；三份固定版本 README；7 个 Agent，18 次实测调用',
        'roles': {'A': '候选功能', 'B': '需求与标准', 'C': '使用约束', 'D': '功能匹配', 'E': '约束评估', 'F': '不足与影响', 'G': '报告综合'},
        'positions': {'C': (24, 176), 'A': (24, 522), 'B': (24, 868), 'E': (412, 176), 'D': (412, 695), 'F': (800, 695), 'G': (1188, 522)},
        'initial': {'A': '前置：无；逐份读取三份 README', 'B': '前置：无；原问题 + Projects', 'C': '前置：无；逐份读取三份 README', 'D': '前置：A 的功能稿 + B 的标准稿', 'E': '前置：A 的功能稿 + C 的约束稿', 'F': '前置：B 的标准稿 + D 的匹配稿', 'G': '前置：E 的评估稿 + F 的不足稿'},
        'deltas': {'A': ['Projects README', 'DB Folder README', 'Dataview README', '核验并纠正功能稿'], 'B': ['Projects README', '核验并纠正标准稿'], 'C': ['Projects README', 'DB Folder README', 'Dataview README', '核验并纠正约束稿'], 'D': ['比较功能与评价标准', '核验并纠正匹配稿'], 'E': ['结合使用约束评估', '核验并纠正评估稿'], 'F': ['归纳不足与不确定性', '核验并纠正不足稿'], 'G': ['综合结论回答问题', '核验并纠正最终报告']},
        'routes': {
            ('C', 'E'): (.50, .50, []),
            ('A', 'E'): (.28, .78, [(370, 608.8), (370, 417.8)]),
            ('A', 'D'): (.72, .22, [(358, 745.2), (358, 763.2)]),
            ('B', 'D'): (.28, .78, [(386, 954.8), (386, 936.8)]),
            ('B', 'F'): (.72, .78, [(770, 1091.2), (770, 936.8)]),
            ('D', 'F'): (.50, .50, []),
            ('E', 'G'): (.50, .22, [(1142, 331), (1142, 590.2)]),
            ('F', 'G'): (.50, .78, [(1168, 850), (1168, 763.8)])},
    },
    'review': {
        'name': 'review-context-example',
        'title': '仓库问题评审 workflow：Astropy 嵌套模型错误',
        'question': 'Q：嵌套 CompoundModel 为什么使 separability_matrix 错判输入/输出依赖？提出修改和测试方案。',
        'source': '公开 issue astropy__astropy-12907；修复前源码、文档与测试；8 个 Agent，18 次实测调用',
        'roles': {'A': '行为与接口', 'B': '实现与调用路径', 'C': '测试与覆盖', 'D': '根因分析', 'E': '兼容性风险', 'F': '修改方案', 'G': '回归测试计划', 'H': '最终评审'},
        'positions': {'A': (24, 176), 'B': (24, 522), 'C': (24, 868), 'D': (412, 176), 'E': (412, 868), 'F': (800, 176), 'G': (800, 522), 'H': (1188, 522)},
        'initial': {'A': '前置：无；文档 + core.py 摘录', 'B': '前置：无；相关实现 + core.py', 'C': '前置：无；已有测试文件', 'D': '前置：A 的行为稿 + B 的实现稿', 'E': '前置：B 的实现稿 + C 的覆盖稿', 'F': '前置：D 的根因稿', 'G': '前置：C 的覆盖稿 + D 的根因稿', 'H': '前置：E 风险 + F 修改 + G 测试'},
        'deltas': {'A': ['compound-models.rst', 'core.py 相关函数摘录', '核验并纠正行为稿'], 'B': ['separable.py', 'core.py 相关函数摘录', '核验并纠正实现稿'], 'C': ['test_separable.py', '核验并纠正覆盖稿'], 'D': ['定位错误根因', '核验并纠正根因稿'], 'E': ['分析兼容性风险', '核验并纠正风险稿'], 'F': ['提出具体修改方案', '核验并纠正修改方案'], 'G': ['拟定输入与期望结果', '核验并纠正测试计划'], 'H': ['综合风险、修改、测试', '核验并纠正最终评审']},
        'routes': {
            ('A', 'D'): (.50, .50, []),
            ('B', 'D'): (.28, .78, [(370, 608.8), (370, 417.8)]),
            ('B', 'E'): (.72, .22, [(386, 745.2), (386, 936.2)]),
            ('C', 'E'): (.50, .50, []),
            ('D', 'F'): (.50, .50, []),
            ('D', 'G'): (.78, .22, [(770, 417.8), (770, 590.2)]),
            ('C', 'G'): (.72, .78, [(358, 1091.2), (358, 1188), (770, 1188), (770, 763.8)]),
            ('E', 'H'): (.50, .78, [(1142, 1023), (1142, 763.8)]),
            ('F', 'H'): (.50, .22, [(1168, 331), (1168, 590.2)]),
            ('G', 'H'): (.50, .50, [])},
    },
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vertex(root, ident, value, x, y, w, h, style, parent='1'):
    cell = ET.SubElement(root, 'mxCell', id=ident, value=value, vertex='1', parent=parent, style=style)
    ET.SubElement(cell, 'mxGeometry', x=str(x), y=str(y), width=str(w), height=str(h), **{'as': 'geometry'})


def text(root, ident, value, x, y, w, h, size=20, bold=False, parent='1', color=INK):
    style = f'text;html=0;whiteSpace=wrap;fillColor=none;strokeColor=none;fontFamily={FONT};fontSize={size};fontColor={color};align=left;verticalAlign=middle;spacing=0;fontStyle={int(bold)};'
    vertex(root, ident, value, x, y, w, h, style, parent)


def line(root, ident, x1, y1, x2, y2, color='#D8E0E4', width=1):
    cell = ET.SubElement(root, 'mxCell', id=ident, edge='1', parent='1', style=f'endArrow=none;strokeColor={color};strokeWidth={width};')
    geo = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as': 'geometry'})
    ET.SubElement(geo, 'mxPoint', x=str(x1), y=str(y1), **{'as': 'sourcePoint'})
    ET.SubElement(geo, 'mxPoint', x=str(x2), y=str(y2), **{'as': 'targetPoint'})


def build():
    ROOT.mkdir(exist_ok=True)
    source_dir = ROOT / 'sources'
    source_dir.mkdir(exist_ok=True)
    audit = {'source_capture': str(CAPTURE), 'scope': 'Two actual F0 inputs in a custom fixed Agent-task DAG; translated context summaries, actual per-call token counts.', 'figures': {}, 'checks': {}, 'historical_lessons_issue': 'One unrelated historical record fingerprint mismatch; memory append disabled.'}
    contexts = {}
    detail = ['# 两个 workflow 的实测 context 与逐轮调用', '', '图中的 Agent 字母与 capture-163125 原始 ID 一致。每个大卡片是一个 Agent；R1、R2 等是它的连续请求序号。箭头传递已完成前置 Agent 的最终文字产物，不传递该 Agent 的 KV。', '', '每次请求都保留完整的角色提示、原问题、范围、已接收的前置产物与自身此前对话。图中 Hk 表示本 Agent 前 k 轮完整 user/assistant 历史，包含当时加入的材料；没有历史压缩。输入 token 数直接读取实际请求记录。', '', 'DAG 横向位置表示依赖层次，不是时间轴。依赖已满足的 Agent 可并行调度；同一 Agent 的各轮串行，仍可能等待 GPU 队列。', '']
    for app, spec in SPEC.items():
        wf_file = CAPTURE / f'F0-{app}-workflow.json'
        wf = json.loads(wf_file.read_text())
        task = json.loads((INPUTS / f'{app}-task.json').read_text())
        expected = {(a, b) for b, ps in wf['deps'].items() for a in ps}
        assert expected == set(spec['routes'])
        mx = ET.Element('mxfile', host='app.diagrams.net', type='device')
        diagram = ET.SubElement(mx, 'diagram', id=app, name=spec['title'])
        model = ET.SubElement(diagram, 'mxGraphModel', page='1', pageWidth=str(WIDTH), pageHeight=str(HEIGHT), background='#FFFFFF')
        root = ET.SubElement(model, 'root')
        ET.SubElement(root, 'mxCell', id='0')
        ET.SubElement(root, 'mxCell', id='1', parent='0')
        vertex(root, 'canvas', '', 0, 0, WIDTH, HEIGHT, 'fillColor=#FFFFFF;strokeColor=none;')
        text(root, 'title', spec['title'], 24, 12, 1488, 44, 30, True)
        text(root, 'question', spec['question'], 24, 61, 1488, 42, 22)
        text(root, 'source', spec['source'], 24, 107, 1488, 30, 20, color=EDGE)
        text(root, 'base', '公共 context：Q + 任务范围 + 各自角色提示；只用给定证据、引用来源，每轮产物限 180 词。', 24, 139, 1488, 29, 20)
        contexts[app] = {'workflow_id': wf['workflow_id'], 'original_task': task.get('original_prompt', task.get('problem_statement')), 'deps': wf['deps'], 'agents': {}}
        detail += [f'## {spec["title"]}', '', spec['question'], '']
        for agent, (x, y) in spec['positions'].items():
            record = wf['agents'][agent]
            rows = [json.loads((CAPTURE / 'calls' / f'{i:04}.json').read_text()) for i in record['call_ids']]
            assert len(rows) == len(spec['deltas'][agent])
            category = 'source' if not record['parents'] else 'final' if agent == ('G' if app == 'research' else 'H') else 'analysis'
            fill, stroke = COLORS[category]
            vertex(root, f'agent-{agent}', '', x, y, CARD_W, CARD_H, f'rounded=1;arcSize=4;container=1;fillColor=#FFFFFF;strokeColor={stroke};strokeWidth=1.8;')
            parent = f'agent-{agent}'
            vertex(root, f'header-{agent}', '', 0, 0, CARD_W, 44, f'rounded=1;arcSize=4;fillColor={fill};strokeColor=none;', parent)
            text(root, f'name-{agent}', f'{agent}  {spec["roles"][agent]}', 13, 3, 242, 38, 22, True, parent)
            text(root, f'count-{agent}', f'{len(rows)} 轮', 255, 3, 60, 38, 20, True, parent)
            text(root, f'initial-{agent}', 'C0 = 公共 context + 前置产物', 13, 50, 298, 27, 20, parent=parent)
            text(root, f'parents-{agent}', spec['initial'][agent], 13, 80, 298, 27, 18, parent=parent)
            line(root, f'card-divider-{agent}', x + 13, y + 113, x + CARD_W - 13, y + 113)
            detail += [f'### Agent {agent}：{spec["roles"][agent]}（{len(rows)} 轮）', '', spec['initial'][agent], '', f'角色 system prompt：{rows[0]["messages"][0]["content"]}', '', '| 轮次 | 本轮新增请求摘要 | 实际输入 tokens | 已缓存前缀 tokens | 原始完整 context |', '|---|---|---:|---:|---|']
            entries = []
            for index, (row, delta) in enumerate(zip(rows, spec['deltas'][agent])):
                r = index + 1
                prefix = 'C0' if index == 0 else f'C0 + H{index}'
                at = 122 + index * 44
                text(root, f'round-{agent}-{r}', f'R{r}  {prefix} + 新请求', 13, at, 298, 22, 19, True, parent)
                # Source and requested action are concrete, while full messages stay linked.
                text(root, f'delta-{agent}-{r}', delta, 13, at + 21, 224, 22, 18, parent=parent)
                text(root, f'tokens-{agent}-{r}', f'{row["input_tokens"]:,}', 225, at + 21, 82, 22, 18, parent=parent, color=EDGE)
                call_file = CAPTURE / 'calls' / f'{row["id"]:04}.json'
                new_user = [m['content'] for m in row['messages'] if m['role'] == 'user'][-1]
                if index:
                    assert row['messages'][:-1] == rows[index - 1]['messages'] + [{'role': 'assistant', 'content': rows[index - 1]['output_text']}]
                    assert row['cached_prefix_tokens'] > 0
                assert row['tool_time_ns'] == 0
                entry = {'round': r, 'delta_summary_zh': delta, 'call_id': row['id'], 'call_path': str(call_file), 'call_sha256': sha(call_file), 'input_tokens': row['input_tokens'], 'output_tokens': row['output_tokens'], 'cached_prefix_tokens': row['cached_prefix_tokens'], 'system_prompt': row['messages'][0]['content'], 'initial_user_context': row['messages'][1]['content'], 'new_user_request': new_user, 'stop_reason': row['stop_reason']}
                entries.append(entry)
                detail.append(f'| R{r} | {delta} | {row["input_tokens"]:,} | {row["cached_prefix_tokens"]:,} | [call {row["id"]}]({call_file}) |')
            detail += ['', '核验轮要求检查原问题、角色与所有已提供证据，纠正无依据结论，返回最终稿并标记 REVIEW: PASS 或 REVIEW: UNRESOLVED。该标记是模型自检，不是外部质量认证。', '']
            contexts[app]['agents'][agent] = {'role_zh': spec['roles'][agent], 'parents': record['parents'], 'initial_context_zh': spec['initial'][agent], 'rounds': entries}
        for (a, b), (sy, ty, points) in spec['routes'].items():
            cell = ET.SubElement(root, 'mxCell', id=f'dependency-{a}-{b}', edge='1', parent='1', source=f'agent-{a}', target=f'agent-{b}', style=f'html=0;rounded=0;strokeColor={EDGE};strokeWidth=1.8;endArrow=block;endFill=1;endSize=8;jumpStyle=arc;jumpSize=9;exitX=1;exitY={sy};exitPerimeter=0;entryX=0;entryY={ty};entryPerimeter=0;')
            geo = ET.SubElement(cell, 'mxGeometry', relative='1', **{'as': 'geometry'})
            if points:
                arr = ET.SubElement(geo, 'Array', **{'as': 'points'})
                for px, py in points:
                    ET.SubElement(arr, 'mxPoint', x=str(px), y=str(py))
        line(root, 'footer-rule', 24, 1198, 1512, 1198, width=1.5)
        text(root, 'history-definition', 'Hk = 本 Agent 前 k 轮完整对话（新增材料 / 请求 + 模型回答）；右侧数字 = 本轮实际输入 token 数。', 24, 1210, 1488, 30, 21)
        text(root, 'dependency-definition', '一个大卡片 = 一个 Agent；箭头 = 等待前置 Agent 全部轮次完成，再接收其最终文字产物。', 24, 1245, 1488, 30, 21)
        text(root, 'execution-definition', 'DAG 展开方向表示依赖；就绪 Agent 可并行调度；同一 Agent 连续串行多轮；计时阶段工具调用为零。', 24, 1280, 1488, 30, 20)
        if hasattr(ET, 'indent'):
            ET.indent(mx)
        out = source_dir / f'{spec["name"]}.drawio'
        ET.ElementTree(mx).write(out, encoding='utf-8', xml_declaration=True)
        audit['figures'][app] = {'drawio': str(out), 'workflow_sha256': sha(wf_file), 'agents': len(wf['agents']), 'calls': sum(a['calls'] for a in wf['agents'].values()), 'dependency_edges': len(expected), 'per_agent_rounds': {a: v['calls'] for a, v in wf['agents'].items()}, 'min_font_source_px': 18, 'review_width_mm': 320, 'letters': 'Stable capture IDs, no serving_model display alias mapping'}
    audit['checks'] = {'all_dependency_edges_match_F0': True, 'all_round_counts_match_calls': True, 'input_tokens_from_raw_calls': True, 'all_followups_append_full_own_history': True, 'all_followups_have_cached_prefix': True, 'all_timed_tool_ns_zero': True, 'manuscript_untouched': True, 'outputs_are_self_review_only': True}
    (ROOT / 'CONTEXTS.json').write_text(json.dumps(contexts, ensure_ascii=False, indent=2) + '\n')
    (ROOT / 'CONTEXTS.md').write_text('\n'.join(detail))
    (ROOT / 'AUDIT.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({app: {'agents': a['agents'], 'calls': a['calls'], 'edges': a['dependency_edges']} for app, a in audit['figures'].items()}))


if __name__ == '__main__':
    build()
