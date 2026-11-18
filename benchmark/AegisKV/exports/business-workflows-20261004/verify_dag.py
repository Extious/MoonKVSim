#!/usr/bin/env python3
"""Check exported native topology and local readiness, without model runs."""
from collections import defaultdict, deque
from itertools import combinations
from pathlib import Path
import json
import xml.etree.ElementTree as ET


def reachable(edges, first, last):
    adjacency = defaultdict(set)
    for source, target in edges:
        adjacency[source].add(target)
    pending, visited = [first], set()
    while pending:
        node = pending.pop()
        if node == last:
            return True
        if node not in visited:
            visited.add(node)
            pending.extend(adjacency[node])
    return False


def acyclic(edges):
    adjacency, indegree = defaultdict(set), defaultdict(int)
    for source, target in edges:
        indegree.setdefault(source, 0)
        if target not in adjacency[source]:
            adjacency[source].add(target)
            indegree[target] += 1
    pending = deque(node for node, degree in indegree.items() if degree == 0)
    count = 0
    while pending:
        node = pending.popleft()
        count += 1
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                pending.append(target)
    return count == len(indegree)


def verify():
    root = Path(__file__).resolve().parent
    contract = json.loads((root / 'sources/scenario-contract.json').read_text())
    reports = []
    for page in ET.parse(root / 'sources/business-workflows.drawio').getroot().findall('diagram'):
        cells = page.findall('./mxGraphModel/root/mxCell')
        lookup = {cell.get('id'): cell for cell in cells}
        assert len(lookup) == len(cells), 'duplicate IDs'
        native_edges = [(cell.get('source'), cell.get('target')) for cell in cells
                        if cell.get('edge') == '1' and cell.get('source') and cell.get('target')]
        assert all(source in lookup and target in lookup for source, target in native_edges)
        assert all(cell.find('mxGeometry') is not None for cell in cells if cell.get('edge') == '1')
        assert acyclic(native_edges), 'native edge cycle'
        report = {'page': page.get('id'), 'unique_ids_and_valid_endpoints': True, 'workflows': {}}
        for workflow, definition in contract['workflows'].items():
            tasks = {f'{workflow}-{letter}': letter for letter in definition['agents']}
            actual = {(tasks[source], tasks[target]) for source, target in native_edges
                      if source in tasks and target in tasks}
            expected = {tuple(pair) for pair in definition['task_edges']}
            assert actual == expected, (workflow, actual, expected)
            assert acyclic(actual)
            for source, target in actual:
                assert not reachable(actual - {(source, target)}, source, target), 'redundant transitive edge'
            for task in tasks:
                assert not any(cell.get('parent') == task for cell in cells), 'Agent node must contain no invocation or KV detail'
            assert len(actual) == len([edge for edge in native_edges if lookup[edge[0]].get('parent') == workflow])
            for pair in combinations(definition['source_parallel_set'], 2):
                assert not reachable(actual, *pair) and not reachable(actual, *reversed(pair))
            for pair in definition['additional_incomparable_pairs']:
                assert not reachable(actual, *pair) and not reachable(actual, *reversed(pair))
            predecessors = {letter: {source for source, target in actual if target == letter}
                            for letter in definition['agents']}
            def ready(completed):
                return {letter for letter, required in predecessors.items()
                        if letter not in completed and required <= completed}
            if workflow == 'w1':
                assert {'C', 'D'} <= ready({'A', 'B'})
                assert {'E', 'F'} <= ready({'A', 'B', 'C', 'D'})
                readiness_cases = ['D ready while C unfinished', 'F ready while E unfinished']
            else:
                assert {'L', 'M'} <= ready({'H', 'I', 'J', 'K'})
                assert 'N' not in ready({'H', 'I', 'J', 'K'})
                readiness_cases = ['M ready while L unfinished', 'N waits for L as required']
            report['workflows'][workflow] = {
                'task_count': len(tasks), 'task_edges': sorted(actual),
                'task_dag_acyclic': True, 'all_edges_nonredundant': True,
                'local_join_count': sum(len(required) > 1 for required in predecessors.values()),
                'only_Agent_nodes_and_task_dependency_edges': True,
                'invocations_or_KV_cells_shown': False,
                'independent_source_set': definition['source_parallel_set'],
                'incomparable_pairs_verified': definition['additional_incomparable_pairs'],
                'local_readiness_cases': readiness_cases,
                'all_tasks_reach_final': all(reachable(actual, node, definition['final_agent']) for node in definition['agents']),
            }
            assert report['workflows'][workflow]['all_tasks_reach_final']
        reports.append(report)
    output = {'status': 'PASS', 'checks': reports,
              'limits': 'Static topology and readiness checks only; not executed Agents or performance evidence.'}
    (root / 'review/dag-checks.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n')
    print('PASS: Agent-only DAGs; 7/8 nodes, 8/10 nonredundant edges, 4/5 local joins and local readiness cases.')


if __name__ == '__main__':
    verify()
