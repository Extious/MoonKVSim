#!/usr/bin/env python3
"""Editable DAGs, analytical motivation schematics and experiment figure plans.

No measured data or synthetic performance observations are generated here.
"""
from pathlib import Path
import importlib.util
import json
import hashlib
import sys
import shutil
import os
os.environ.setdefault('MPLCONFIGDIR', str(Path(__file__).resolve().parent / 'mpl-cache'))
import fitz
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parent
AEGIS = ROOT.parents[1]
PAPER = AEGIS / 'paper'
DOC = AEGIS / 'docs/workflow-evaluation-20261005'
OLD = AEGIS / 'exports/application-workflows-lr-20261005'
COL_MM = (505.89 - 24) / 2 * 72 / 72.27 / 72 * 25.4
INK, GREEN, BLUE, ORANGE, GRAY = '#33434B', '#4D8074', '#647F9E', '#AC864B', '#DEE4E8'

def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

def write(name, value):
    DOC.mkdir(parents=True, exist_ok=True)
    (DOC / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def dag():
    mod = module(OLD / 'build_workflows.py', 'application_dags')
    mod.ROOT = ROOT
    mod.PANELS[0].update(title='(a) Evidence-based research report', slug='research-report-workflow', roles={
        'A': 'Subjects &\nmethods', 'B': 'Needs &\ncriteria', 'C': 'Context &\nconstraints',
        'D': 'Fit &\ncomparison', 'E': 'Contextual\nassessment',
        'F': 'Gaps &\nimplications', 'G': 'Report\nsynthesis'})
    mod.PANELS[1].update(title='(b) Repository issue/change review', roles={
        'A': 'Behavior &\ninterfaces', 'B': 'Implementation\n& call paths', 'C': 'Existing tests\n& coverage',
        'D': 'Root-cause\nanalysis', 'E': 'Compatibility\n& risks', 'F': 'Change\nproposal',
        'G': 'Regression\ntest plan', 'H': 'Final\nreview'})
    # Three text lines require more height, not smaller lettering.
    mod.NODE_H = 94
    # Keep topology/routes; relative edge anchors automatically follow node height.
    mod.build()
    config = (OLD / 'fontconfig.conf').read_text().replace(str(OLD.resolve()), str(ROOT.resolve()))
    (ROOT / 'fontconfig.conf').write_text(config)
    shutil.copy2(OLD / 'render_workflows.py', ROOT / 'render_workflows.py')

def typography():
    font = Path('/home/comp/zhanzhao/miniforge3/envs/latex/tinytex/texmf-dist/fonts/opentype/public/libertine/LinLibertine_R.otf')
    font_manager.fontManager.addfont(str(font))
    plt.rcParams.update({'font.family':'Linux Libertine O','font.size':10.5,
                         'axes.labelsize':10.5,'xtick.labelsize':10.5,'ytick.labelsize':10.5,
                         'text.color':INK,'axes.edgecolor':INK,'pdf.fonttype':42,
                         'axes.spines.top':False,'axes.spines.right':False})

def save(fig, name, width_mm=COL_MM):
    out = ROOT / 'schematics'; out.mkdir(exist_ok=True)
    review = ROOT / 'review'; review.mkdir(exist_ok=True)
    fig.savefig(out / f'{name}.pdf')
    fig.savefig(out / f'{name}.png', dpi=250)
    plt.close(fig)
    with fitz.open(out / f'{name}.pdf') as doc:
        assert abs(doc[0].rect.width/72*25.4-width_mm) < .02
        page = doc[0]
        page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False).save(review / f'{name}-color.png')
        page.get_pixmap(matrix=fitz.Matrix(2,2),colorspace=fitz.csGRAY,alpha=False).save(review / f'{name}-gray.png')
        sizes=[s['size'] for b in page.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
        assert min(sizes)>=9.9,(name,min(sizes))
    if name != 'experiment-figure-atlas':
        shutil.copy2(out / f'{name}.pdf', PAPER / f'figures/{name}.pdf')

def exposure():
    fig=plt.figure(figsize=(COL_MM/25.4,2.8))
    ax=fig.add_axes([.16,.30,.78,.55])
    # Author-specified normalized example: same recovery, unequal DAG slack.
    names=['C','B','A']; hidden=[4,0,3]; exposed=[0,4,1]
    ax.barh(names,hidden,color='white',edgecolor=INK,hatch='////',height=.53,label='Absorbed')
    ax.barh(names,exposed,left=hidden,color=GREEN,edgecolor=INK,height=.53,label='Exposed')
    for y,s in enumerate([5,0,3]):ax.text(4.13,y,f's = {s}u',va='center')
    ax.set(xlim=(0,5.65),xticks=[0,1,2,3,4],xlabel='Recovery delay (normalized units u)')
    fig.text(.035,.93,'Same reconstruction: R = 4u',fontsize=11)
    fig.legend(loc='lower center',bbox_to_anchor=(.52,.015),ncol=2,frameon=False,
               handlelength=1,handletextpad=.5,columnspacing=1)
    save(fig,'workflow-recovery-exposure')

def demand():
    fig=plt.figure(figsize=(COL_MM/25.4,2.75)); ax=fig.add_axes([.015,.04,.97,.90]);ax.set_xlim(0,10);ax.set_ylim(0,8.8);ax.axis('off')
    ax.text(.1,8.25,'Complete DRAM checkpoint: all layers',fontsize=11)
    for row in range(3):
        ax.text(.2,7-row*1.03,f'L{row+1}',va='center')
        for block in range(6):
            selected=(row<2 and block in ({0,3} if row==0 else {1,4}))
            ax.add_patch(Rectangle((1.1+block*1.15,6.6-row*1.03),1.03,.72,facecolor=GREEN if selected else GRAY,edgecolor=INK,lw=.6))
    ax.text(9.0,6.6,'HBM\nsubset',ha='center',va='center',color=GREEN)
    ax.text(.1,3.78,'Transfer arrival vs. layer demand',fontsize=11)
    for y,start,color,label in [(2.7,1.2,BLUE,'Hidden'),(1.35,4.6,ORANGE,'Exposed')]:
        ax.text(.2,y,label,va='center'); ax.plot([2,9],[y,y],color=GRAY,lw=1)
        ax.add_patch(Rectangle((start+1,y-.19),1.6,.38,facecolor=color,edgecolor=INK,lw=.5))
        ax.plot([5.6,5.6],[y-.4,y+.4],color=INK,lw=1)
    ax.text(5.6,.2,'Layer needs KV',ha='center');ax.text(8.8,.2,'time',ha='right')
    save(fig,'recovery-demand-placement')

def capacity():
    fig=plt.figure(figsize=(COL_MM/25.4,2.9));ax=fig.add_axes([.18,.30,.77,.53])
    for x,serving,replica,label in [(0,2,4,'Low load'),(1,5,1,'High load'),(2,3,3,'Load falls')]:
        ax.bar(x,1,color=GRAY,edgecolor=INK,width=.62)
        ax.bar(x,serving,bottom=1,color=BLUE,edgecolor=INK,width=.62)
        ax.bar(x,replica,bottom=1+serving,color='white',hatch='///',edgecolor=GREEN,width=.62)
    ax.set(xticks=[0,1,2],xticklabels=['Low\nload','High\nload','Load\nfalls'],yticks=[],ylabel='HBM allocation',ylim=(0,7.6))
    fig.text(.055,.94,'Safe replica space changes with serving',fontsize=11)
    fig.legend(handles=[Rectangle((0,0),1,1,facecolor=GRAY,label='Fixed'),Rectangle((0,0),1,1,facecolor=BLUE,label='Serving'),Rectangle((0,0),1,1,facecolor='white',hatch='///',edgecolor=GREEN,label='Replicas')],
               loc='lower center',bbox_to_anchor=(.53,.015),ncol=3,frameon=False,handlelength=.8,columnspacing=.6,handletextpad=.4)
    save(fig,'foreground-replica-capacity')

def master():
    fig=plt.figure(figsize=(COL_MM/25.4,3.3))
    ax=fig.add_axes([.13,.71,.82,.2]); names=['C','B','A'];values=[0,4,1]
    ax.barh(names,values,color=[GRAY,GREEN,GRAY],edgecolor=INK,height=.55)
    ax.axvline(2,color=ORANGE,ls='--',lw=1)
    ax.text(2.12,2.3,'lambda = 2u',color=ORANGE)
    ax.set(xlim=(0,4.6),xticks=[0,2,4],xlabel='Exposed retry delay (units u)')
    fig.text(.03,.94,'(a) B receives a complete DRAM copy',fontsize=11)
    grid=fig.add_axes([.1,.035,.88,.43]);grid.axis('off');grid.set(xlim=(-.85,7.2),ylim=(-1.25,4.3))
    fig.text(.03,.51,'(b) B: Top-K in first L layers, K=L=2',fontsize=11)
    counts=[[9,2,1,7,0,3],[1,8,0,6,2,1],[1,0,3,2,5,1],[0,2,1,4,2,3]]
    for r,row in enumerate(counts):
        y=3-r; grid.text(-.22,y+.35,f'L{r+1}',ha='right',va='center')
        hot=set(np.argsort(row)[-2:]) if r<2 else set()
        for b,c in enumerate(row):
            grid.add_patch(Rectangle((b,y),.85,.72,facecolor=GREEN if b in hot else GRAY,edgecolor=INK,lw=.5))
            grid.text(b+.425,y+.36,str(c),ha='center',va='center',color='white' if b in hot else INK)
        grid.add_patch(Rectangle((6.15,y),.85,.72,facecolor='white',edgecolor=ORANGE,hatch='///',lw=.5))
    for b in range(6):grid.text(b+.425,3.95,f'B{b}',ha='center')
    grid.text(6.575,3.95,'Tail',ha='center');grid.plot([0,7],[1.87,1.87],ls='--',color=INK,lw=.6)
    grid.text(0,-.55,'Green: HBM + DRAM; gray: DRAM',fontsize=10)
    grid.text(0,-1.05,'Hatched tail: replay after committed frontier',fontsize=10)
    save(fig,'master-selection')

SPECS=[
 ('F1','Workload and history','E0',['invocations_per_agent','prompt_tokens','common_prefix_tokens','agent_gap_ms','tool_ms','active_agents'],['calls/Agent distribution','history growth by role','real execution overlap']),
 ('F2','State and recovery cost','E1',['context_tokens','kv_bytes','metadata_bytes','recovery_ms','checkpoint_copy_ms'],['absolute restore latency vs natural context','physical bytes vs context','healthy copy cost']),
 ('F3','Workflow exposure','E2',['slack_ms','reconstruct_ms','exposed_ms','protected','prediction_kind'],['fault-landmark Slack/recovery joint distribution','same-budget selection comparison']),
 ('F4','End-to-end comparison','E3',['wct_f0_ms','wct_f1_ms','completed','arrival_rate','policy'],['paired faulted WCT and penalty','healthy WCT cost','completion/goodput']),
 ('F5','Common failure impact','E4',['fault_relative_ms','victim_class','wct_delta_ms','ttft_ms','tpot_ms'],['direct and indirect job penalties','time to return to normal envelope']),
 ('F6','HBM incremental value','E5',['hbm_bytes','required_unique_bytes','hit_unique_bytes','exposed_h2d_ms','retry_ms','selector'],['causal byte coverage vs budget','exposed wait/retry at matched budget','actual layer timeline']),
 ('F7','Component ablation','E6',['workflow_selection','hbm_selection','adaptive_quota','wct_ms','healthy_cost_ms'],['eight matched-budget configurations','interaction and healthy cost']),
 ('F8','Dynamic HBM control','E7',['time_ms','serving_bytes','safe_ceiling_bytes','quota_bytes','replica_bytes','ttft_ms','tpot_ms'],['capacity/quota/occupancy timeline','foreground latency in same window']),
 ('F9','Prediction and decisions','E8',['remaining_true_ms','remaining_pred_ms','slack_true_ms','slack_pred_ms','wct_regret_ms','controller_ms'],['held-out error CDF','error to protection regret','controller overhead']),
 ('F10','Sensitivity and limits','E9',['parameter','parameter_value','wct_ms','healthy_cost_ms','copy_lag_tokens'],['budget/bandwidth/concurrency panels','lambda/Z/K/L sweeps including zero benefit']),
 ('F11','Cost-benefit trade-off','E11',['healthy_cost_ms','failure_saving_ms','objective','population_id'],['paired H and D','hypothetical mixture break-even with uncertainty']),
]

def contracts():
    definitions={'wct_ms':'job completion - external arrival, includes dependency/tool/queue time',
        'exposed_h2d_ms':'measured union of transfer-caused compute stalls, not summed DMA durations',
        'hit_unique_bytes':'distinct required (layer, physical block, shard) bytes already resident; no repeated query counts',
        'slack_ms':'fault-time residual DAG Slack; predicted causal or retrospective oracle labeled',
        'agent_gap_ms':'next submit - previous complete, separately label tool/orchestration/dependency',
        'copy_lag_tokens':'accepted frontier N - last complete committed frontier M'}
    write('FIGURE_SPECS.json',{'status':'DESIGN_ONLY','performance_rows':0,'common_keys':['run_id','task_id','workflow_id','agent_id','invocation_id','arrival_seed','policy','model','fault_id','evidence_level','raw_manifest_sha256'],
        'figures':[{'id':i,'title':t,'experiment':e,'required_columns':c,'panels':p,'status':'AWAITING_NEW_DATA','axes':'absolute SI units; paired policies share axes; preserve zero/negative differences',
                    'aggregation':'cluster by task/source and arrival block; report task/run n; do not treat calls as independent jobs','source':'new actual application traces / physical serving measurements'} for i,t,e,c,p in SPECS],
        'metric_definitions':definitions,'no_placeholder_values':True})
    write('CAMPAIGN.json',{'status':'DESIGN_ONLY_NOT_EXECUTED','created':'2026-10-05','llm_calls':0,'physical_runs':0,
        'workflow_contract':'../workload-decision-20261004/WORKFLOW_DEPENDENCIES.json','old_results_allowed':False,
        'required_experiments':[f'E{i}' for i in range(12)],
        'gates':{'G0':'input/material/license/prompt freeze','G1':'real application capture and quality','G2':'pilot, power, disjoint split, parameter freeze','G3':'physical restore correctness/budgets','G4':'paired physical core and healthy costs','G5':'ablations/robustness/generalization','G6':'claim/statistics/figure audit'},
        'primary_models':'native sparse models accepted by quality and compatibility pilot; pinned hashes required',
        'proposed_load_fractions':[.30,.60,.85],'pilot_tasks_per_application':20,
        'formal_sample_rule':'pilot variance; paired 95%CI half-width target <=5% baseline mean WCT; no pseudo-replication',
        'pending_freeze':['eligible_task_ids','material_manifest','prompts','model_hashes','hardware','arrival_traces','fault_schedule','parameter_values'],
        'paper_result_claims_allowed':False})
    write('TRACE_FIELDS.json',{'schema_version':1,'status':'REQUIRED_CAPTURE_CONTRACT',
        'workflow':['workflow_id','task_id','application','dag','material_hashes','arrival_ns','finish_ns','quality_status','failure_reason'],
        'agent':['agent_id','predecessor_ids','predecessor_output_hashes','ready_ns','start_ns','finish_ns','system_prompt_hash','stop_reason'],
        'invocation':['invocation_id','agent_id','round_index','full_messages_artifact','input_token_ids_artifact','output_token_ids_artifact','model_hash','tokenizer_hash','chat_template_hash','prefix_token_count','prefix_hash','submit_ns','admit_ns','gpu_start_ns','first_token_ns','finish_ns','worker','tp_ranks'],
        'tool':['tool_id','invocation_id','start_ns','finish_ns','output_hash','idempotence_key'],
        'checkpoint':['agent_id','accepted_frontier','committed_frontier','tp_shard_ids','metadata_hash','pending_bytes','committed_bytes','publish_ns','evict_ns','copy_events'],
        'fault':['fault_id','domain','worker','detect_ns','injection_ns','logical_landmark','resident_victims','active_victims','queued_victims','retry_targets','target_ready_ns','resume_ns'],
        'native_selection':['invocation_id','query_position','layer','head','selected_logical_units','kernel_tile_mapping','physical_block_ids','kv_shards','required_byte_ids','reveal_ns','selection_model_hash'],
        'transfer':['source_domain','target_rank','block_ids','bytes','queued_ns','start_ns','end_ns','resident_ns','layer_need_ns'],
        'clock_contract':'monotonic timestamps per host; synchronize and record cross-host clock offset/uncertainty; CUDA events for device intervals'})

def protocol():
    mod = module(OLD / 'build_workflows.py', 'protocol_style')
    import xml.etree.ElementTree as ET
    mx=ET.Element('mxfile',host='app.diagrams.net',type='device')
    d=ET.SubElement(mx,'diagram',id='protocol',name='New trace and paired evaluation protocol')
    model=ET.SubElement(d,'mxGraphModel',page='1',pageWidth='1008',pageHeight='550',background='#FFFFFF')
    root=ET.SubElement(model,'root');ET.SubElement(root,'mxCell',id='0');ET.SubElement(root,'mxCell',id='1',parent='0')
    mod.vertex(root,'canvas','',(0,0,1008,550),'fillColor=#FFFFFF;strokeColor=none;')
    boxes={
      'input':(24,90,230,100,'Public tasks +\nfrozen materials'),
      'capture':(316,90,290,100,'Real model execution\nDAG + full Agent histories'),
      'quality':(674,45,300,95,'Application quality\nIndependent checks'),
      'trace':(674,186,300,95,'New captured trace\nTokens + gates + non-LLM time'),
      'replay':(24,355,290,100,'Dependency-gated replay\nSame arrivals / inputs / budget'),
      'healthy':(380,315,130,82,'F0\nHealthy'),
      'fault':(380,415,130,82,'F1\nWorker fault'),
      'result':(674,355,300,100,'Paired job WCT\nCost + recovery + interference')}
    for ident,(x,y,w,h,text) in boxes.items():
      fill,stroke=mod.COLORS['analysis' if ident in ['input','capture','trace'] else 'final' if ident=='result' else 'synthesis']
      mod.vertex(root,ident,text,(x,y,w,h),f'rounded=1;arcSize=9;whiteSpace=wrap;html=0;fontFamily={mod.FONT};fontSize=22;fontColor={mod.INK};fillColor={fill};strokeColor={stroke};strokeWidth=1.6;spacing=5;')
    mod.vertex(root,'title','Collect behavior, then measure serving and recovery',(24,8,960,38),f'fillColor=none;strokeColor=none;fontFamily={mod.FONT};fontSize=26;fontStyle=1;align=left;')
    edges=[('input','capture'),('capture','quality'),('capture','trace'),('trace','replay'),('replay','healthy'),('replay','fault'),('healthy','result'),('fault','result')]
    routes={
       ('input','capture'):(1,.5,0,.5,[]),
       ('capture','quality'):(1,.25,0,.5,[(640,115),(640,92.5)]),
       ('capture','trace'):(1,.75,0,.5,[(625,165),(625,233.5)]),
       ('trace','replay'):(.5,1,.5,0,[(824,299),(169,299)]),
       ('replay','healthy'):(1,.25,0,.5,[(346,380),(346,356)]),
       ('replay','fault'):(1,.75,0,.5,[(346,430),(346,456)]),
       ('healthy','result'):(1,.5,0,.25,[(600,356),(600,380)]),
       ('fault','result'):(1,.5,0,.75,[(625,456),(625,430)]),
    }
    for i,(a,b) in enumerate(edges):
      ex,ey,ix,iy,points=routes[a,b]
      c=ET.SubElement(root,'mxCell',id=f'e{i}',edge='1',parent='1',source=a,target=b,style=f'rounded=0;endArrow=block;endFill=1;strokeColor=#53636B;strokeWidth=1.7;jumpStyle=arc;exitX={ex};exitY={ey};exitPerimeter=0;entryX={ix};entryY={iy};entryPerimeter=0;')
      geo=ET.SubElement(c,'mxGeometry',relative='1',**{'as':'geometry'})
      if points:
        arr=ET.SubElement(geo,'Array',**{'as':'points'})
        for x,y in points:ET.SubElement(arr,'mxPoint',x=str(x),y=str(y))
    if hasattr(ET,'indent'):ET.indent(mx)
    ET.ElementTree(mx).write(ROOT/'sources/evaluation-protocol.drawio',encoding='utf-8',xml_declaration=True)

def atlas():
    # Publication figure design sheets: no marks pretending to be observations.
    width=168;fig=plt.figure(figsize=(width/25.4,9.6));fig.text(.025,.975,'New experiment figures: data contracts and panel design',fontsize=12)
    for n,(ident,title,exp,columns,panels) in enumerate(SPECS):
        row,col=divmod(n,2);left=.035+col*.49;top=.925-row*.147
        fig.text(left,top,f'{ident}  {title}',fontsize=11,color=GREEN)
        text='\n'.join(f'{j+1}. {p}' for j,p in enumerate(panels))
        # wrap at a conservative physical column width
        import textwrap
        text='\n'.join(textwrap.fill(line,39,subsequent_indent='   ') for line in text.splitlines())
        fig.text(left,top-.025,text,va='top',fontsize=10.2,linespacing=1.15)
    fig.text(.035,.02,'DESIGN ONLY: all measured panels await new application/serving traces.',fontsize=10.5,color=INK)
    save(fig,'experiment-figure-atlas',width)
    shutil.copy2(ROOT/'schematics/experiment-figure-atlas.pdf',ROOT/'experiment-figure-atlas.pdf')

if __name__=='__main__':
    dag();protocol();typography();contracts();exposure();demand();capacity();master();atlas()
    print('Generated two editable DAGs, four illustrative mechanisms, and eleven figure specifications.')
