"""Keep the original Motivation figure types/style; use only newly measured inputs.
No calculated WCT penalties or old experiment results are read.
"""
from pathlib import Path
import csv,hashlib,json,os,shutil
os.environ.setdefault('MPLCONFIGDIR','/tmp/aegiskv-original-types-mpl')
import fitz,numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle,Patch
ROOT=Path(__file__).resolve().parent;AEGIS=ROOT.parents[1]
RUNS=AEGIS/'experiments/workflow-motivation-20261005/runs'
ISOLATED=RUNS/'isolated-163136';NATIVE=RUNS/'native-models-163137'
WIDTH=(505.89-24)/2/72.27
INK,BLUE,TEAL,RED,PALE,MINT,EDGE,AMBER='#243746','#23688D','#39756A','#AC4251','#DDEBF3','#E1EEE8','#70808A','#9B6428'
SOURCES=set();RESULTS={}
font_manager.fontManager.addfont('/home/comp/zhanzhao/miniforge3/envs/latex/tinytex/texmf-dist/fonts/opentype/public/libertine/LinLibertine_R.otf')
plt.rcParams.update({'font.family':'Linux Libertine O','font.size':10.25,'axes.labelsize':10.25,
 'xtick.labelsize':10.25,'ytick.labelsize':10.25,'legend.fontsize':10.25,'pdf.fonttype':42,
 'svg.fonttype':'none','text.color':INK,'axes.labelcolor':INK,'axes.edgecolor':INK,
 'xtick.color':INK,'ytick.color':INK,'axes.linewidth':.7,'hatch.linewidth':.6})
for d in ['data','figures','review']:(ROOT/d).mkdir(exist_ok=True)
def read(p):
 SOURCES.add(p);return json.loads(p.read_text())
def table(name,rows):
 with (ROOT/'data'/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def save(fig,name):
 for ext in ['pdf','svg']:fig.savefig(ROOT/f'figures/{name}.{ext}',facecolor='white')
 plt.close(fig)
 with fitz.open(ROOT/f'figures/{name}.pdf') as d:
  p=d[0];spans=[s for b in p.get_text('dict')['blocks'] if 'lines' in b for l in b['lines'] for s in l['spans'] if s['text'].strip()]
  assert min(s['size'] for s in spans)>=10
  assert all(p.rect.contains(fitz.Rect(s['bbox'])) for s in spans),[(s['text'],s['bbox']) for s in spans if not p.rect.contains(fitz.Rect(s['bbox']))]
  for mode,cs in [('color',fitz.csRGB),('gray',fitz.csGRAY)]:
   p.get_pixmap(matrix=fitz.Matrix(3,3),colorspace=cs).save(ROOT/f'review/{name}-{mode}.png')
  p.get_pixmap(matrix=fitz.Matrix(3,3)).save(ROOT/f'figures/{name}.png')
  RESULTS[name]={'width_mm':p.rect.width*25.4/72,'height_mm':p.rect.height*25.4/72,'min_font_pt':min(s['size'] for s in spans)}
 for suffix in ['pdf']:
  shutil.copy2(ROOT/f'figures/{name}.{suffix}',AEGIS/f'paper/figures/{name}.{suffix}')
 shutil.copy2(ROOT/f'figures/{name}.png',AEGIS/f'paper/figures/preview/{name}.png')
def agent_timeline():
 w=read(ISOLATED/'A_P0_F0-research-workflow.json');deps=w['deps'];agents=w['agents'];origin=w['arrival_ns']
 starts={k:(a['ready_ns']-origin)/1e9 for k,a in agents.items()}
 ends={k:(a['finish_ns']-origin)/1e9 for k,a in agents.items()}
 duration={k:ends[k]-starts[k] for k in agents};deadline=max(ends.values())
 latest={};children={k:[x for x,p in deps.items() if k in p] for k in deps}
 for k in reversed(list(deps)):
  latest[k]=min((latest[x]-duration[x] for x in children[k]),default=deadline)
 slack={k:max(0,latest[k]-ends[k]) for k in deps}
 fig=plt.figure(figsize=(WIDTH*.88,2.36));ax=fig.add_axes([.10,.31,.82,.63])
 rows=[]
 for i,k in enumerate(deps):
  critical=slack[k]<.01
  ax.add_patch(Rectangle((starts[k],i-.29),duration[k],.58,fc='#F7E6E9' if critical else PALE,ec=RED if critical else BLUE,lw=1.35 if critical else .8))
  if slack[k]>.01:ax.plot([ends[k],latest[k]],[i,i],color=EDGE,lw=.85,ls=(0,(3,2)))
  rows.append(dict(agent=k,ready_s=starts[k],complete_s=ends[k],task_interval_s=duration[k],latest_finish_s=latest[k],derived_slack_s=slack[k],parents=','.join(deps[k]),calls=agents[k]['calls']))
 ax.set_xlim(0,60);ax.set_ylim(6.6,-.6);ax.set_yticks(range(7),list(deps));ax.set_xticks([0,20,40,60]);ax.set_xlabel('Workflow time (s)',labelpad=2)
 ax.spines[['top','right','left']].set_visible(False);ax.tick_params(axis='y',length=0,pad=3);ax.tick_params(axis='x',length=2,pad=2)
 ax.grid(axis='x',lw=.5,color='#E1E5E8');ax.set_axisbelow(True)
 for label,k in zip(ax.get_yticklabels(),deps):
  if slack[k]<.01:label.set_fontweight('bold')
 fig.legend(handles=[Patch(fc='#F7E6E9',ec=RED,lw=1.35,label='Critical path'),Line2D([],[],color=EDGE,ls=(0,(3,2)),label='Slack')],loc='lower center',bbox_to_anchor=(.53,.005),ncol=2,frameon=False,handlelength=1.1,columnspacing=.9,handletextpad=.4)
 table('agent-task-timeline.csv',rows);save(fig,'agent_value_a')
 RESULTS['timeline_scope']='First predeclared healthy isolated replay; bars are measured readiness-to-completion. Dashed tolerance is derived from observed durations on the explicit task DAG, not independently fault-measured slack.'
def agent_cost():
 if not (ISOLATED/'SUMMARY.json').exists():return
 summary=read(ISOLATED/'SUMMARY.json');assert summary['input_equal_all'] and summary['output_equal_all']
 calls={}
 for p in (ISOLATED/'calls').glob('*.json'):
  r=read(p);calls[(r['run_id'],r['agent_key'].split('/')[-1],r['round_index'])]=r
 rows=[];metrics=[]
 for victim in ['A','B','C','G']:
  values=[]
  for trial in range(3):
   r0=f'{victim}_P{trial}_F0';r1=f'{victim}_P{trial}_F1'
   a=next(w for w in summary['workflows'] if w['run_id']==r0);b=next(w for w in summary['workflows'] if w['run_id']==r1)
   c0=calls[(r0,victim,1)];c1=calls[(r1,victim,1)];before=calls[(r1,victim,0)]
   assert before['fault']['victim_agent_keys']==[before['agent_key']]
   assert c0['input_token_ids']==c1['input_token_ids'] and c0['output_token_ids']==c1['output_token_ids']
   assert c0['cached_prefix_tokens']>0 and c1['cached_prefix_tokens']==0
   row=dict(agent=victim,trial=trial,healthy_wct_s=a['wct_ms']/1000,loss_wct_s=b['wct_ms']/1000,
     delta_wct_s=(b['wct_ms']-a['wct_ms'])/1000,normal_prefill_s=c0['first_forward_cuda_ms']/1000,
     reconstruction_prefill_s=c1['first_forward_cuda_ms']/1000,
     extra_prefill_s=(c1['first_forward_cuda_ms']-c0['first_forward_cuda_ms'])/1000,
     lost_cache_tokens=before['cache_tokens'],lost_kv_bytes=before['kv_tensor_bytes'],replayed_input_tokens=c1['input_tokens'])
   rows.append(row);values.append(row)
  metrics.append(dict(agent=victim,normal=np.mean([v['normal_prefill_s'] for v in values]),
    extra=np.mean([v['extra_prefill_s'] for v in values]),full=np.mean([v['reconstruction_prefill_s'] for v in values]),
    low=min(v['reconstruction_prefill_s'] for v in values),high=max(v['reconstruction_prefill_s'] for v in values),
    wct=np.mean([v['delta_wct_s'] for v in values]),wct_low=min(v['delta_wct_s'] for v in values),wct_high=max(v['delta_wct_s'] for v in values)))
 fig=plt.figure(figsize=(WIDTH*.88,1.88));ax=fig.add_axes([.125,.20,.61,.60]);stat=fig.add_axes([.79,.20,.18,.60],sharey=ax)
 y=np.arange(4);base=np.array([r['normal'] for r in metrics]);extra=np.array([r['extra'] for r in metrics]);full=base+extra
 assert np.all(extra>=0),'Retain anomalous measurements; never clip negative differences into stacked bars.'
 ax.barh(y,base,height=.62,fc=MINT,ec=TEAL,hatch='///',lw=.55,label='New input')
 ax.barh(y,extra,left=base,height=.62,fc=RED,ec=RED,lw=.55,label='Rebuild')
 lo=np.array([r['low'] for r in metrics]);hi=np.array([r['high'] for r in metrics])
 ax.errorbar(full,y,xerr=[full-lo,hi-full],fmt='none',ecolor=INK,elinewidth=.7,capsize=2,capthick=.6)
 for i,r in enumerate(metrics):
  ax.text(hi[i]+.009,i,f'{full[i]:.3f}',va='center',ha='left')
  stat.text(.5,i,f'{r["wct"]:+.2f}',va='center',ha='center',color=RED)
 ax.set_xlim(0,max(.30,max(hi)*1.43));ax.set_ylim(3.55,-.55);ax.set_yticks(y,['A','B','C','G']);ax.set_xticks([0,.1,.2]);ax.set_xlabel('Recovery prefill (s)',labelpad=2)
 ax.spines[['top','right','left']].set_visible(False);ax.tick_params(axis='y',length=0,pad=3);ax.tick_params(axis='x',length=2,pad=2);ax.grid(axis='x',lw=.5,color='#E1E5E8');ax.set_axisbelow(True)
 stat.set_xlim(0,1);stat.set_axis_off();stat.text(.5,1.08,'ΔW (s)',transform=stat.transAxes,ha='center',va='bottom')
 fig.legend(*ax.get_legend_handles_labels(),loc='upper center',bbox_to_anchor=(.44,.98),ncol=2,frameon=False,handlelength=1.15,handletextpad=.4,columnspacing=1)
 table('isolated-agent-kv-loss.csv',rows);save(fig,'agent_value_b');RESULTS['isolated_cost']=metrics
 RESULTS['cost_encoding']='Same original horizontal stacked-bar layout, colors/hatching and right WCT column. Stack is physical normal-prefix-compatible prefill plus extra reconstruction prefill; WCT is independently measured, signed and never calculated from slack. Three pairs per victim; all raw values retained.'
def native_curves():
 names=['NOSA-8B','NSA-8B','MiniCPM4.1-8B']
 if not all((NATIVE/n/'SUMMARY.json').exists() for n in names):return
 fractions=np.linspace(0,1,101);fig=plt.figure(figsize=(WIDTH,2.28));ax=fig.add_axes([.18,.18,.76,.60]);data=[];counts=[]
 for name,color,marker,ls in zip(names,[BLUE,AMBER,TEAL],['o','s','^'],['-','--','-.']):
  summary=read(NATIVE/name/'SUMMARY.json');series=[]
  for request in summary['requests']:
   B=request['history_tokens']//64;heat=[]
   for layer in request['layers']:
    p=NATIVE/name/layer['trace_file'];SOURCES.add(p)
    with np.load(p) as z:arr=z['selected_blocks'][:,request['history_tokens']:]
    assert arr.shape[1]==512
    h=np.zeros(B,dtype=np.int64)
    for q in range(512):
     unique=np.unique(arr[:,q,:]);unique=unique[(unique>=0)&(unique<B)];h[unique]+=1
    heat.append(h)
   heat=np.array(heat);tot=heat.sum(axis=1);assert (tot>0).all()
   ordered=np.sort(heat,axis=1)[:,::-1];cumulative=np.pad(ordered.cumsum(axis=1),((0,0),(1,0)))
   k=np.floor(fractions*B+1e-9).astype(int)
   coverage=(cumulative[:,k]/tot[:,None]).mean(axis=0);series.append(coverage)
   for index,fraction in enumerate(fractions):data.append(dict(model=name,source_call_id=request['source_call_id'],round=request['round_index'],input_tokens=request['input_tokens'],historical_blocks=B,nominal_budget_percent=fraction*100,actual_budget_blocks=int(k[index]),access_share_percent=coverage[index]*100))
  series=np.asarray(series);x=fractions*100;mean=series.mean(axis=0)*100;low=series.min(axis=0)*100;high=series.max(axis=0)*100
  ax.fill_between(x,low,high,color=color,alpha=.13,lw=0);ax.plot(x,mean,color=color,ls=ls,lw=1.15,marker=marker,markevery=[10,20,40,60,80],ms=3.2,mfc='white',mew=.8,label=name)
  counts.append(dict(model=name,top20_mean_percent=float(mean[20]),top20_min_percent=float(low[20]),top20_max_percent=float(high[20]),requests=len(series),query_window=512))
 ax.plot([0,100],[0,100],color=EDGE,ls=':',lw=.85,label='Uniform')
 ax.set_xlim(0,100);ax.set_ylim(0,103);ax.set_xticks([0,20,40,60,80,100]);ax.set_yticks([0,25,50,75,100]);ax.set_xlabel('Hot historical blocks (%)',labelpad=2);ax.set_ylabel('Access share (%)',labelpad=2)
 ax.tick_params(length=2,pad=2);ax.spines[['top','right']].set_visible(False);ax.grid(axis='y',lw=.5,color='#E1E5E8');ax.set_axisbelow(True)
 handles,labels=ax.get_legend_handles_labels();order=[0,2,1,3]
 fig.legend([handles[i] for i in order],[labels[i] for i in order],loc='upper center',bbox_to_anchor=(.56,.98),ncol=2,frameon=False,handlelength=1.45,handletextpad=.35,columnspacing=.7,labelspacing=.25,borderaxespad=0)
 table('native-original-metric-curves.csv',data);save(fig,'kv_value');RESULTS['native_concentration']=counts
 RESULTS['native_scope']='Native last-512-query full-prefill selections on three complete successive review-A histories; query-block counts deduplicate all heads, layers normalized then averaged, bands are history range. Retrospective per-layer ranking; no runtime hit, prediction accuracy or recovery-latency inference.'
if (ISOLATED/'A_P0_F0-research-workflow.json').exists():agent_timeline()
agent_cost();native_curves()
RESULTS['sources']={str(p.relative_to(AEGIS)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(SOURCES)}
(ROOT/'ORIGINAL_TYPE_MEASUREMENTS.json').write_text(json.dumps(RESULTS,indent=2)+'\n')
print(json.dumps({k:v for k,v in RESULTS.items() if k!='sources'},indent=2))
