"""Physical paired serving replay of the newly captured real application trace.

Public frozen materials, actual generated outputs, exact serialized histories,
physical cache tensors and timing. This is a new small pilot, not production
typicality evidence or a complete AegisKV policy experiment.
"""
from pathlib import Path
import asyncio
import hashlib
import json
import multiprocessing as mp
import os
import time
import traceback

ROOT = Path(__file__).resolve().parent
AEGIS = ROOT.parents[1]
MODEL = '/home/comp/zhanzhao/.cache/huggingface/hub/models--Qwen--Qwen3-4B-Instruct-2507/snapshots/cdbee75f17c01a7cc42f958dc650907174af0554'
ROLES = {
 'research': {'A':'Subjects and methods: extract documented candidate capabilities with source IDs.',
  'B':'Needs and criteria: define the requested Table, Kanban, Calendar, and List criteria; distinguish requirements from inferred needs.',
  'C':'Context and constraints: identify documented installation, compatibility, maintenance, and limitations.',
  'D':'Fit and comparison: compare candidates against the evidence and criteria supplied by A and B.',
  'E':'Contextual assessment: assess how constraints from C qualify capabilities from A.',
  'F':'Gaps and implications: explain unmet criteria and uncertainty using B and D.',
  'G':'Report synthesis: answer the original question using E and F, preserving citations and limitations.'},
 'review': {'A':'Behavior and interfaces: explain the documented input/output contract and nested compound-model behavior.',
  'B':'Implementation and call paths: identify the issue-relevant code path, array construction, and nesting behavior.',
  'C':'Existing tests and coverage: identify existing coverage and missing nested-model cases.',
  'D':'Root-cause analysis: reconcile A and B; cite source IDs and concrete functions.',
  'E':'Compatibility and risks: assess risks and contracts using B and C.',
  'F':'Change proposal: propose a precise change from D without claiming it has been applied or tested.',
  'G':'Regression test plan: propose test inputs and expected invariants using C and D.',
  'H':'Final review: synthesize E, F and G into an issue review; label unexecuted tests.'}}


def common_prefix(a, b):
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return i


def worker(index, incoming, outgoing, out):
    try:
        import torch
        import transformers
        from transformers import AutoModelForCausalLM, AutoTokenizer, DynamicCache, LogitsProcessor, LogitsProcessorList
        class FrozenOutput(LogitsProcessor):
            def __init__(self, prefix, ids):
                self.prefix,self.ids=prefix,ids
            def __call__(self, input_ids, scores):
                token=self.ids[input_ids.shape[-1]-self.prefix]
                scores.fill_(-float('inf'));scores[:,token]=0
                return scores
        torch.set_num_threads(4)
        device = f'cuda:{index}'
        torch.cuda.set_device(index)
        tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(MODEL, local_files_only=True,
                torch_dtype=torch.bfloat16, attn_implementation='sdpa').to(device).eval()
        caches = {}
        token_states = {}
        events = []
        def before(module, args, kwargs):
            a = torch.cuda.Event(enable_timing=True); a.record()
            events.append([a, None, time.monotonic_ns()])
        def after(module, args, kwargs, result):
            b = torch.cuda.Event(enable_timing=True); b.record()
            events[-1][1] = b
        model.register_forward_pre_hook(before, with_kwargs=True)
        model.register_forward_hook(after, with_kwargs=True)
        outgoing.put({'ready':index,'torch':torch.__version__,'transformers':transformers.__version__,
            'gpu':torch.cuda.get_device_name(index),'device_total_bytes':torch.cuda.get_device_properties(index).total_memory,
            'weights_allocated_bytes':torch.cuda.memory_allocated(index)})
        while True:
            task = incoming.get()
            if task is None:
                break
            ident = task['id']
            if task['action'] == 'clear':
                caches.clear(); token_states.clear()
                torch.cuda.synchronize()
                outgoing.put({'id':ident,'cleared':True}); continue
            if task['action'] == 'release':
                caches.pop(task['agent_key'],None); token_states.pop(task['agent_key'],None)
                outgoing.put({'id':ident,'released':True}); continue
            if task['action'] == 'profile':
                ids = task['token_ids']
                x = torch.tensor([ids],device=device)
                measurements = []
                with torch.inference_mode():
                    # Warm the exact same shape, then time independent cache constructions.
                    warm = model(input_ids=x,use_cache=True,logits_to_keep=1); del warm
                    torch.cuda.synchronize()
                    for repeat in range(3):
                        torch.cuda.reset_peak_memory_stats(index)
                        a = torch.cuda.Event(enable_timing=True); b = torch.cuda.Event(enable_timing=True)
                        a.record(); result = model(input_ids=x,use_cache=True,logits_to_keep=1); b.record(); b.synchronize()
                        cache = result.past_key_values
                        sizes = [k.numel()*k.element_size()+v.numel()*v.element_size() for k,v in cache]
                        pairs = list(cache)
                        cpu = [(k.detach().to('cpu').pin_memory(),v.detach().to('cpu').pin_memory()) for k,v in pairs]
                        a2 = torch.cuda.Event(enable_timing=True); b2 = torch.cuda.Event(enable_timing=True)
                        a2.record(); restored = DynamicCache()
                        for layer,(k,v) in enumerate(cpu):
                            restored.update(k.to(device,non_blocking=True),v.to(device,non_blocking=True),layer)
                        b2.record(); b2.synchronize()
                        assert restored.get_seq_length() == len(ids)
                        assert all(torch.equal(k,rk) and torch.equal(v,rv) for (k,v),(rk,rv) in zip(pairs,restored))
                        measurements.append({'repeat':repeat,'context_tokens':len(ids),
                            'full_prefill_cuda_ms':a.elapsed_time(b),'dram_to_gpu_cuda_ms':a2.elapsed_time(b2),
                            'kv_tensor_bytes':sum(sizes),'peak_allocated_bytes':torch.cuda.max_memory_allocated(index),
                            'restored_tensor_equal':True})
                        del result,cache,restored,pairs,cpu
                outgoing.put({'id':ident,'profile':measurements}); continue
            key = task['agent_key']
            messages = task['messages']
            submitted = task['submit_ns']
            started = time.monotonic_ns()
            ids = tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True)
            assert ids == task['expected_input_token_ids'], 'Frozen-input mismatch; paired comparison is invalid.'
            assert len(ids) + 384 < 32000, 'Pilot input too long; preserve it and select another task rather than silently truncate.'
            old_ids = token_states.get(key,[])
            compatible = common_prefix(old_ids,ids)
            cache = caches.get(key)
            reuse = min(compatible,cache.get_seq_length()) if cache is not None else 0
            if cache is not None:
                cache.crop(reuse)
            events.clear()
            torch.cuda.reset_peak_memory_stats(index)
            x = torch.tensor([ids],device=device)
            torch.cuda.synchronize()
            execution_start = time.monotonic_ns()
            with torch.inference_mode():
                generated = model.generate(input_ids=x,attention_mask=torch.ones_like(x),past_key_values=cache,
                    do_sample=False,max_new_tokens=len(task['frozen_output_token_ids']),use_cache=True,return_dict_in_generate=True,
                    logits_processor=LogitsProcessorList([FrozenOutput(len(ids),task['frozen_output_token_ids'])]),
                    pad_token_id=tokenizer.eos_token_id)
            torch.cuda.synchronize()
            execution_end = time.monotonic_ns()
            accepted = generated.sequences[0].tolist()
            assert accepted[len(ids):] == task['frozen_output_token_ids'], 'Frozen-output mismatch.'
            caches[key] = generated.past_key_values
            token_states[key] = accepted
            cache_bytes = sum(k.numel()*k.element_size()+v.numel()*v.element_size() for k,v in caches[key])
            resident_bytes = sum(k.numel()*k.element_size()+v.numel()*v.element_size() for c in caches.values() for k,v in c)
            answer = tokenizer.decode(accepted[len(ids):],skip_special_tokens=True)
            row = {'id':ident,'worker':index,'agent_key':key,'round_index':task['round_index'],
                'submit_ns':submitted,'worker_start_ns':started,'execution_start_ns':execution_start,'finish_ns':execution_end,
                'input_tokens':len(ids),'output_tokens':len(accepted)-len(ids),'cached_prefix_tokens':reuse,
                'retained_history_common_prefix_tokens':compatible,'cache_tokens':caches[key].get_seq_length(),
                'kv_tensor_bytes':cache_bytes,'resident_agent_kv_bytes':resident_bytes,
                'cuda_allocated_bytes':torch.cuda.memory_allocated(index),'cuda_reserved_bytes':torch.cuda.memory_reserved(index),
                'cuda_peak_allocated_bytes':torch.cuda.max_memory_allocated(index),'tool_time_ns':0,
                'first_forward_cuda_ms':events[0][0].elapsed_time(events[0][1]),
                'all_forwards_cuda_ms':sum(a.elapsed_time(b) for a,b,_ in events),
                'execution_wall_ms':(execution_end-execution_start)/1e6,
                'output_text':answer,'output_token_ids':accepted[len(ids):],'input_token_ids':ids,
                'output_sha256':hashlib.sha256(answer.encode()).hexdigest(),
                'stop_reason':'eos' if len(accepted)-len(ids)<384 else 'token_limit'}
            if task.get('inject_after'):
                row['fault']={'kind':'between-invocation KV-loss injection; model weights remain intact',
                    'worker':index,'victim_agent_keys':list(caches),'lost_kv_tensor_bytes':resident_bytes,'injection_ns':time.monotonic_ns()}
                caches.clear()
            outgoing.put(row)
    except BaseException:
        outgoing.put({'error':traceback.format_exc(),'worker':index})


class Executor:
    def __init__(self, queues, responses, out):
        self.queues,self.responses,self.out = queues,responses,out
        self.locks = [asyncio.Lock(),asyncio.Lock()]
        self.counter = 0
        self.rows = []
        source=ROOT/'runs/capture-163125/calls'
        self.frozen={}
        for path in source.glob('*.json'):
            r=json.loads(path.read_text())
            if r['run_id']=='F0':
                self.frozen[(r['agent_key'].split('/')[-2],r['agent_key'].split('/')[-1],r['round_index'])]=r
    async def request(self,index,action,**kwargs):
        async with self.locks[index]:
            self.counter += 1
            ident = self.counter
            if action=='generate':
                key=(kwargs['agent_key'].split('/')[-2],kwargs['agent_key'].split('/')[-1],kwargs['round_index'])
                reference=self.frozen[key]
                kwargs.update(frozen_output_token_ids=reference['output_token_ids'],expected_input_token_ids=reference['input_token_ids'])
            self.queues[index].put(dict(id=ident,action=action,**kwargs))
            row = await asyncio.to_thread(self.responses[index].get)
            if 'error' in row:
                raise RuntimeError(row['error'])
            assert row['id']==ident
            if action=='generate':
                artifact = self.out/'calls'/f'{ident:04}.json'; artifact.parent.mkdir(exist_ok=True)
                row['messages']=kwargs['messages']; row['run_id']=kwargs['run_id']; row['workflow_id']=kwargs['workflow_id']
                artifact.write_text(json.dumps(row,ensure_ascii=False,indent=2)+'\n')
                self.rows.append(row)
                print(kwargs['run_id'],kwargs['agent_key'],kwargs['round_index'],row['input_tokens'],row['output_tokens'],round(row['execution_wall_ms'],1),row['stop_reason'],flush=True)
            return row


def material_groups(task,agent):
    all_m = {x['id']:x for x in task['materials']}
    if task['application']=='research':
        chosen = list(all_m) if agent in 'AC' else ['projects']
    else:
        chosen = {'A':['compound-docs','core-excerpts'],'B':['separable','core-excerpts'],'C':['tests']}[agent]
    return [f'[{k}]\n'+(ROOT/all_m[k]['path']).read_text() for k in chosen]


async def run_workflow(executor,task,deps,run_id,fault,offset):
    app=task['application']; workflow_id=task['task_id']
    original=task.get('original_prompt',task.get('problem_statement'))
    origin=time.monotonic_ns(); tasks={}; records={}
    order=list(deps)
    async def agent(letter):
        parents=deps[letter]
        predecessor_outputs={p:await tasks[p] for p in parents}
        ready=time.monotonic_ns(); key=f'{run_id}/{app}/{letter}'; index=(order.index(letter)+offset)%2
        messages=[{'role':'system','content':f'You are Agent {letter}. {ROLES[app][letter]} Use only supplied evidence. Cite [source IDs] or predecessor evidence IDs. Do not invent tests, tool execution, or missing facts. Each response should be a compact work artifact of at most 180 words.'},
                  {'role':'user','content':f'Original task:\n{original}\nScope:\n{task["scope"]}\nCompleted predecessor artifacts:\n'+json.dumps(predecessor_outputs,ensure_ascii=False)}]
        local_round=0; outputs=[]
        groups=material_groups(task,letter) if not parents else ['Use the completed predecessor artifacts above to produce your assigned analysis.']
        for group in groups:
            messages.append({'role':'user','content':f'New evidence for your task:\n{group}\nRead this material and update your cumulative work artifact. Preserve uncertainty and references.'})
            row=await executor.request(index,'generate',messages=messages,agent_key=key,round_index=local_round,
                submit_ns=time.monotonic_ns(),run_id=run_id,workflow_id=workflow_id,
                inject_after=bool(fault and app=='research' and letter=='A' and local_round==0))
            outputs.append(row);messages.append({'role':'assistant','content':row['output_text']});local_round+=1
        messages.append({'role':'user','content':'Check the cumulative artifact against the original question, your role, and all supplied sources. Correct unsupported claims and inconsistencies. Return your final corrected artifact and end with REVIEW: PASS or REVIEW: UNRESOLVED. Keep within 180 words. This is a separate verification invocation, not a request to wait for another Agent.'})
        row=await executor.request(index,'generate',messages=messages,agent_key=key,round_index=local_round,
            submit_ns=time.monotonic_ns(),run_id=run_id,workflow_id=workflow_id)
        outputs.append(row)
        finish=time.monotonic_ns()
        records[letter]={'agent':letter,'parents':parents,'worker':index,'ready_ns':ready,'finish_ns':finish,
            'calls':len(outputs),'call_ids':[x['id'] for x in outputs],'final_output_sha256':row['output_sha256'],
            'quality':'UNRESOLVED' if 'REVIEW: UNRESOLVED' in row['output_text'] or any(x['stop_reason']=='token_limit' for x in outputs) else 'SELF_REVIEW_ONLY'}
        await executor.request(index,'release',agent_key=key)
        return row['output_text']
    for letter in order:
        tasks[letter]=asyncio.create_task(agent(letter))
    final=await asyncio.gather(*tasks.values())
    completed=max(x['finish_ns'] for x in records.values())
    result={'run_id':run_id,'workflow_id':workflow_id,'application':app,'arrival_ns':origin,'finish_ns':completed,
            'wct_ms':(completed-origin)/1e6,'faulted':fault,'agents':records,'deps':deps,
            'evidence_level':'new physical application execution; self review only; bounded pilot'}
    (executor.out/f'{run_id}-{app}-workflow.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


async def execute(executor):
    design=json.loads((AEGIS/'docs/workload-decision-20261004/WORKFLOW_DEPENDENCIES.json').read_text())['dependencies']
    task_inputs=[json.loads((ROOT/'inputs'/f'{x}-task.json').read_text()) for x in ['research','review']]
    workflow_rows=[]
    plan=[('WARMUP',False)]
    for trial in range(3):
        policies=['F0','F1'] if trial%2==0 else ['F1','F0']
        plan.extend((f'P{trial}_{policy}',policy=='F1') for policy in policies)
    for run_id,fault in plan:
        for i in range(2):await executor.request(i,'clear')
        rows=await asyncio.gather(*(run_workflow(executor,t,design[t['application']],run_id,fault,offset) for offset,t in enumerate(task_inputs)))
        workflow_rows.extend(rows)
    matches=[]
    for r in executor.rows:
        key=(r['agent_key'].split('/')[-2],r['agent_key'].split('/')[-1],r['round_index'])
        reference=executor.frozen[key]
        matches.append({'run_id':r['run_id'],'key':key,'input_equal':r['input_token_ids']==reference['input_token_ids'],
                        'output_equal':r['output_token_ids']==reference['output_token_ids']})
    (executor.out/'pair-token-audit.json').write_text(json.dumps(matches,indent=2)+'\n')
    summary={'status':'PHYSICAL_FROZEN_TRACE_REPLAY_COMPLETE_PENDING_FIGURE_REVIEW','workflows':workflow_rows,
        'source_trace':'runs/capture-163125','model_path':MODEL,'calls':len(executor.rows),'paired_repetitions':3,
        'output_equal_all':all(x['output_equal'] for x in matches),'input_equal_all':all(x['input_equal'] for x in matches),
        'scope':'Two public task inputs and custom DAGs, new real application outputs frozen for matched GPU serving replay. Exact input/output tokens and task dependencies preserved. Three counterbalanced F0/F1 pairs plus excluded warmup. KV-loss between calls with intact weights, not hard process failure. No complete AegisKV policy comparison.',
        'profile_scope':'Profile measured separately in the source capture allocation; this run only measures paired serving replay.',
        'formal_claims_allowed':False}
    (executor.out/'SUMMARY.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(summary['status'],summary['calls'],summary['output_equal_all'],flush=True)


def main():
    out=ROOT/'runs'/f'capture-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=True)
    ctx=mp.get_context('spawn');incoming=[ctx.Queue(),ctx.Queue()];outgoing=[ctx.Queue(),ctx.Queue()]
    processes=[ctx.Process(target=worker,args=(i,incoming[i],outgoing[i],out)) for i in range(2)]
    for p in processes:p.start()
    try:
        env=[q.get() for q in outgoing]
        if any('error' in x for x in env):raise RuntimeError(str(env))
        (out/'ENVIRONMENT.json').write_text(json.dumps({'workers':env,'slurm_job_id':os.environ['SLURM_JOB_ID']},indent=2)+'\n')
        asyncio.run(execute(Executor(incoming,outgoing,out)))
    finally:
        for q in incoming:q.put(None)
        for p in processes:p.join(timeout=30)
        for p in processes:
            if p.is_alive():p.terminate();p.join(timeout=10)


if __name__=='__main__':
    main()
