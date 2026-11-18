#!/usr/bin/env python3
"""Check history and dependency contracts; these checks are not model evidence."""
from pathlib import Path
import hashlib
import json
import re

ROOT=Path(__file__).resolve().parent


def validate():
    spec=json.loads((ROOT/'application-spec.json').read_text())
    inputs=json.loads((ROOT/'example-inputs.json').read_text())
    previews=json.loads((ROOT/'REQUEST_BLUEPRINTS.json').read_text())
    graph_path=ROOT.parent.parent/'exports/business-workflows-20261004/sources/scenario-contract.json'
    graph=json.loads(graph_path.read_text())
    assert previews['preview_only'] and previews['not_executable_until_placeholders_are_filled']
    assert spec['tools_in_main_variant']==[]
    assert inputs['provenance']=='fictional_demonstration'
    original={d for d in inputs['documents']}
    checked=[]
    for wf_id,page in [('procurement','w1'),('campaign','w2')]:
        wf=spec['workflows'][wf_id]
        edges={tuple(e) for e in wf['edges']}
        assert edges=={tuple(e) for e in graph['workflows'][page]['task_edges']}
        assert set(wf['agent_ids'])==set(graph['workflows'][page]['agents'])
        assert set(wf['documents'])<=original
        for aid in wf['agent_ids']:
            agent=spec['agents'][aid]
            actual_preds={s for s,t in edges if t==aid}
            assert actual_preds==set(agent['predecessors']), (aid,'predecessor mismatch')
            req=next(a for a in previews['agents'] if a['agent']==aid)
            assert req['workflow']==wf_id and set(req['predecessors'])==actual_preds
            assert len(req['base_requests'])==len(agent['base_rounds'])>=2
            system=req['base_requests'][0]['messages'][0]
            for i,round_ in enumerate(req['base_requests']):
                messages=round_['messages']
                assert messages[0]==system and messages[-1]['role']=='user'
                assert len(messages)==2*(i+1)
                assert [m['role'] for m in messages]==['system']+['user','assistant']*i+['user']
                assert all(d in wf['documents'] for d in agent['base_rounds'][i]['documents_appended'])
                if i:
                    previous=req['base_requests'][i-1]['messages']
                    assert messages[:-2]==previous, (aid,i,'prior history changed')
                    assert messages[-2]['role']=='assistant' and '占位符' in messages[-2]['content']
                    assert not re.findall(r'前驱 [A-O] 的不可变最终产物',messages[-1]['content']), 'mid-task predecessor update'
            first=req['base_requests'][0]['messages'][1]['content']
            assert set(re.findall(r'前驱 ([A-O]) 的不可变最终产物',first))==actual_preds
            assert req['conditional_repair_request'][:-2]==req['base_requests'][-1]['messages']
            assert req['conditional_repair_request'][-1]['content']==agent['conditional_repair_prompt']
            for doc in spec['original_evidence_in_first_call'].get(aid,[]):
                assert doc in wf['documents'] and inputs['documents'][doc] in first
            checked.append({'agent':aid,'base_requests':len(req['base_requests']),
                            'fixed_system_and_append_only_history':True,
                            'predecessor_snapshot_only_in_first_request':True,
                            'original_evidence_present_when_required':True})
    files=['build_blueprints.py','application-spec.json','example-inputs.json','REQUEST_BLUEPRINTS.json','PROMPTS.md']
    report={'status':'PASS','scope':'request-template structure and declared task DAG only',
            'agents':checked,'base_request_count':sum(a['base_requests'] for a in checked),
            'llm_invocations_executed':0,
            'not_established':['actual model output quality','actual invocation counts','token-prefix compatibility','KV residency or hits','serving overlap','production representativeness'],
            'sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files}}
    (ROOT/'VALIDATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print('PASS: 15 Agent specifications, 35 request blueprints, immutable history, first-call predecessor snapshots and matching figure DAGs. No LLM calls.')


if __name__=='__main__':
    validate()
