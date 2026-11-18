#!/usr/bin/env python3
"""Expanded evaluation: explicit analytical models and provenance-pinned traces.

No GPU benchmark is run. CSV rows are data; figure-specs.json owns presentation.
LANL replay reserves one independent FIFO recovery pool per source system. A
pool executes one four-branch recovery at a time. This restrictive model exposes
queue externalities; it is not an implementation of AegisKV's online router.
"""
from __future__ import annotations
import csv, hashlib, itertools, json, math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import numpy as np
import theory as t

ROOT=t.ROOT
OUT=ROOT/'experiments/data/eurosys27/expanded'
DOC=ROOT/'experiments/eurosys27'
TRACE=ROOT/'experiments/data/eurosys27/trace-source'
CFG=json.loads(t.CONFIG.read_text())
GROUPS=[t.Group(f'A{i}',b,d,q) for i,(b,d,q) in enumerate(zip(
    CFG['default_group_GiB'],CFG['default_remaining_s'],CFG['normal_reuse_probability']))]
POLICIES=['Storage only','LRU','AegisKV model']
SPECS={}; TABLES=defaultdict(list); SUMMARY={}; RAW=defaultdict(list)

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def spec(name,kind,xlabel,ylabel,unit='s',evidence='analytical',**kw):
    SPECS[name]=dict(kind=kind,xlabel=xlabel,ylabel=ylabel,unit=unit,evidence=evidence,**kw)
def add(name,series,x,y,category='',scenario='base',**kw):
    s=SPECS[name]
    TABLES[name].append(dict(figure=name,panel='main',series=series,x=float(x),y=float(y),
        category=category,lower='',upper='',unit=s['unit'],evidence=s['evidence'],
        scenario_id=str(scenario),source_id='expanded-v1',independent_runs=0,**kw))
def cdf(name,series,values):
    for i,v in enumerate(sorted(values)):add(name,series,v,(i+1)/len(values),scenario=i)
def loss(policy,groups=GROUPS,cfg=CFG,budget=16):
    resident=t.choose(groups,budget,cfg,policy)
    times=t.restore(groups,resident,cfg,policy=='Recompute')
    return t.loss(groups,times),times,resident

def inherited():
    # Keep previously published calculations unchanged; expand their placement.
    names={
      'workflow-outcomes':('cdf','Workflow failure penalty (s)','Scenario fraction','fraction'),
      'capacity-frontier':('line','DRAM budget (GiB)','Workflow failure penalty (s)','s'),
      'storage-bottleneck':('line','Storage read rate (GiB/s)','Workflow failure penalty (s)','s'),
      'checkpoint-lag':('line','Commit lag (s)','Workflow failure penalty (s)','s'),
      'prediction-robustness':('line','Duration perturbation (%)','Workflow failure penalty (s)','s'),
      'healthy-io':('line','Backup link utilization (%)','Mean I/O response (ms)','ms'),
      'safe-demotion':('step','Time after pressure event (s)','Bytes (GiB)','GiB'),
      'controller-scaling':('line','Live DAG segments','Decision time (ms)','ms'),
      'common-fault':('line','Branches retained in DRAM','Delay (s)','s')}
    for old,(kind,x,y,unit) in names.items():
        name='eval-'+old;spec(name,kind,x,y,unit)
        if old in ['storage-bottleneck','controller-scaling']:SPECS[name]['xlog']=True
        if old=='controller-scaling':SPECS[name]['ylog']=True
        for r in csv.DictReader((t.OUT/(old+'.csv')).open()):
            add(name,r['series'],r['x'],r['y'],scenario=r['scenario_id'])
    for panel in ['fault','reuse']:
        name='eval-ablation-'+panel
        spec(name,'barh','Mean delay (s)','',height=3.9)
        for i,r in enumerate(csv.DictReader((t.OUT/'policy-ablation.csv').open())):
            if r['panel']==panel:add(name,'Static value model',i,r['y'],r['series'],scenario=r['scenario_id'])
    for budget in [0,4,8,12,16,20,24,28,32,36,40]:
        for policy in ['LRU','Reuse only','AegisKV model','Feasible oracle']:
            d,ready,resident=loss(policy,budget=budget)
            RAW['capacity-objectives'].append(dict(budget_GiB=budget,policy=policy,
                resident_groups=';'.join(map(str,sorted(resident))),penalty_s=d,
                weighted_objective_s=t.objective(GROUPS,resident,CFG),pool_busy_s=max(ready)))

def single_failure():
    rows=list(csv.DictReader((t.OUT/'scenario-results.csv').open()));paired=defaultdict(dict)
    for r in rows:paired[r['scenario_id']][r['policy']]=r
    key=next(k for k in rows[0] if k in ['failure_penalty_s','fault_penalty_s','penalty_s'])
    spec('eval-paired-benefit','cdf','LRU minus AegisKV penalty (s)','Scenario fraction','fraction')
    differences=[float(v['LRU'][key])-float(v['AegisKV model'][key]) for v in paired.values()]
    cdf('eval-paired-benefit','Paired scenarios',differences)
    SUMMARY['single_grid']={'n':len(differences),'better':sum(x>1e-8 for x in differences),
        'tie':sum(abs(x)<=1e-8 for x in differences),'worse':sum(x< -1e-8 for x in differences)}
    spec('eval-branch-exposure','barh','Time (s)','',height=3.8)
    for i,g in enumerate(GROUPS):
        add('eval-branch-exposure','Join slack',i,max(x.remaining for x in GROUPS)-g.remaining,g.name)
        for p in ['LRU','AegisKV model']:add('eval-branch-exposure',p,i,loss(p)[1][i],g.name)
    spec('eval-recovery-attribution','stackh','Workflow failure penalty (s)','',height=3.6)
    # Telescoping interventions, fixed placement; never sum overlapped wall times.
    order=[('Floor',{'floor_s':CFG['floor_s']}),('Reads',{
        'dram_read_GiB_s':CFG['dram_read_GiB_s'],'storage_read_GiB_s':CFG['storage_read_GiB_s']}),
        ('Network',{'shared_link_GiB_s':CFG['shared_link_GiB_s']}),
        ('H2D',{'h2d_GiB_s':CFG['h2d_GiB_s']}),('Replay',{'replay_s':CFG['replay_s']})]
    for i,p in enumerate(POLICIES):
        c=dict(CFG,floor_s=0,replay_s=0,dram_read_GiB_s=1e12,storage_read_GiB_s=1e12,
               shared_link_GiB_s=1e12,h2d_GiB_s=1e12)
        resident=loss(p)[2];previous=t.loss(GROUPS,t.restore(GROUPS,resident,c));total=0
        for label,setting in order:
            c.update(setting);value=t.loss(GROUPS,t.restore(GROUPS,resident,c))
            add('eval-recovery-attribution',label,i,value-previous,p)
            RAW['counterfactuals'].append(dict(policy=p,intervention=label,penalty_s=value,increment_s=value-previous))
            total+=value-previous;previous=value
        assert abs(total-loss(p)[0])<1e-8
    spec('eval-storage-traffic','barh','Storage read volume (GiB)','',unit='GiB',height=2.9)
    for i,p in enumerate(POLICIES):
        add('eval-storage-traffic','Restore bytes',i,sum(g.gib for j,g in enumerate(GROUPS) if j not in loss(p)[2]),p)
    spec('eval-burst-interference','line','Interrupted workflows in burst','Mean workflow penalty (s)')
    for p in POLICIES:
        d,rr,_=loss(p);service=max(rr)
        for n in [1,2,4,8,16]:add('eval-burst-interference',p,n,d+(n-1)*service/2)
    spec('eval-background-backlog','line','Time after recovery burst (s)','I/O backlog (GiB)','GiB')
    for p in POLICIES:
        volume=sum(g.gib for i,g in enumerate(GROUPS) if i not in loss(p)[2])
        # Conservation-of-work bound: normal arrivals consume 70% of one reader.
        for sec in np.linspace(0,40,81):add('eval-background-backlog',p,sec,max(0,volume-.3*CFG['storage_read_GiB_s']*sec))
    spec('eval-logical-fault-phase','line','Matched token progress (%)','Workflow failure penalty (s)')
    for p in POLICIES:
        for progress in [.2,.5,.8,.95]:
            gs=[t.Group(g.name,g.gib*progress/.8,g.remaining,g.reuse) for g in GROUPS]
            add('eval-logical-fault-phase',p,progress*100,loss(p,gs)[0])
    SUMMARY['single_base']={p:dict(penalty_s=loss(p)[0],restore_s=list(loss(p)[1]),
       dram_groups=sorted(loss(p)[2]),pool_busy_s=max(loss(p)[1])) for p in POLICIES+['Recompute']}

def read_lanl():
    path=TRACE/'lanl/failure-data.csv';raw=list(csv.DictReader(path.open()))
    stats=Counter(raw_rows=len(raw));by=defaultdict(list)
    for index,r in enumerate(raw):
        if r['purpose']!='compute':stats['non_compute']+=1;continue
        try:
            start=(datetime.strptime(r['Prob Started (mm/dd/yy hh:mm)'],'%m/%d/%Y %H:%M')-datetime(1970,1,1)).total_seconds()
            end=(datetime.strptime(r['Prob Fixed (mm/dd/yy hh:mm)'],'%m/%d/%Y %H:%M')-datetime(1970,1,1)).total_seconds()
            system=int(r['System']);node=int(r['nodenumz'])
        except (ValueError,TypeError):stats['unparseable']+=1;continue
        if end<start:stats['negative_duration']+=1;continue
        if end==start:stats['zero_duration']+=1;continue
        by[(system,node)].append((start,end,index))
    clean=[]
    for (system,node),intervals in sorted(by.items()):
        current=None
        for start,end,row in sorted(intervals):
            if current and start<=current[1]:
                stats['merged_overlapping_or_touching']+=1;current[1]=max(current[1],end);current[2].append(row)
            else:
                if current:clean.append(dict(system=system,node=node,start=current[0],end=current[1],source_rows=';'.join(map(str,current[2]))))
                current=[start,end,[row]]
        if current:clean.append(dict(system=system,node=node,start=current[0],end=current[1],source_rows=';'.join(map(str,current[2]))))
    clean.sort(key=lambda x:(x['system'],x['start'],x['node']))
    stats.update(clean_intervals=len(clean),systems=len({r['system'] for r in clean}),nodes=len(by))
    SUMMARY['lanl']=dict(stats);RAW['lanl-clean-intervals']=clean
    return clean

def trace_replay(intervals,policy,scale=1,order='original',workflows=1):
    # Start times only drive this conditional recovery-load model. End times
    # characterize outages but do not claim spare capacity or production rate.
    by=defaultdict(list)
    for r in intervals:by[r['system']].append(r)
    d,rr,_=loss(policy);service=max(rr);results=[]
    for system,records in sorted(by.items()):
        origin=records[0]['start'];starts=[(r['start']-origin)/scale for r in records]
        if order=='uniform':starts=np.linspace(starts[0],starts[-1],len(starts)).tolist()
        free=0.
        for seq,(r,start) in enumerate(zip(records,starts)):
            for w in range(workflows):
                wait=max(0,free-start);free=max(free,start)+service
                results.append(dict(system=system,node=r['node'],episode=seq,workflow=w,
                    policy=policy,clock_scale=scale,arrival_s=start,wait_s=wait,
                    intrinsic_s=d,penalty_s=wait+d,pool_busy_s=service,finish_s=free))
    return results

def traces():
    intervals=read_lanl()
    spec('eval-trace-outages','cdf','Recorded outage duration (min)','Interval fraction','fraction','observed trace',xlog=True)
    cdf('eval-trace-outages','LANL compute nodes',[(r['end']-r['start'])/60 for r in intervals])
    bursts=Counter((r['system'],r['start']) for r in intervals)
    grouped=defaultdict(list)
    for r in intervals:grouped[(r['system'],r['start'])].append(r)
    spread=[]
    for records in grouped.values():
        for i,r in enumerate(records):
            spread.append(dict(r,start=r['start']+59*i/max(1,len(records)-1)))
    spread.sort(key=lambda r:(r['system'],r['start'],r['node']))
    spec('eval-trace-bursts','cdf','Nodes with same recorded start','Start-group fraction','fraction','observed trace',xlog=True)
    cdf('eval-trace-bursts','One-minute timestamp resolution',list(bursts.values()))
    SUMMARY['lanl']['distinct_start_groups']=len(bursts)
    SUMMARY['lanl']['multi_node_start_groups']=sum(n>1 for n in bursts.values())
    SUMMARY['lanl']['maximum_start_group']=max(bursts.values())
    spec('eval-trace-penalty','cdf','Modeled workflow penalty (s)','Recovery episode fraction','fraction','trace-driven model',xlog=True)
    spec('eval-trace-queue','barh','Mean modeled delay (s)','',evidence='trace-driven model',height=3.5)
    spec('eval-trace-time-stress','line','Timestamp compression factor','Mean workflow penalty (s)',evidence='trace-driven model',xlog=True)
    spec('eval-trace-burst-control','barh','Mean workflow penalty (s)','',evidence='trace-driven model',height=3.5)
    base={}
    for i,p in enumerate(POLICIES):
        rs=trace_replay(intervals,p);base[p]=rs;RAW['trace-replay'].extend(rs)
        cdf('eval-trace-penalty',p,[r['penalty_s'] for r in rs])
        add('eval-trace-queue','Intrinsic join penalty',i,np.mean([r['intrinsic_s'] for r in rs]),p)
        add('eval-trace-queue','FIFO queue wait',i,np.mean([r['wait_s'] for r in rs]),p)
        for scale in [1,10,100,1000]:
            sr=rs if scale==1 else trace_replay(intervals,p,scale)
            add('eval-trace-time-stress',p,scale,np.mean([r['penalty_s'] for r in sr]))
        for order,label in [('original','Recorded starts'),('uniform','Evenly spaced control'),('spread','Within-minute spread')]:
            sr=rs if order=='original' else trace_replay(spread if order=='spread' else intervals,p,order=order)
            add('eval-trace-burst-control',label,i,np.mean([r['penalty_s'] for r in sr]),p)
            if order=='spread':
                RAW['trace-minute-spread'].extend(sr)
                SUMMARY.setdefault('trace_minute_spread',{})[p]={
                    'mean':float(np.mean([r['penalty_s'] for r in sr])),
                    'p95':float(np.quantile([r['penalty_s'] for r in sr],.95)),
                    'p99':float(np.quantile([r['penalty_s'] for r in sr],.99))}
    SUMMARY['trace_model']={p:{'mean_penalty_s':float(np.mean([r['penalty_s'] for r in rs])),
        'p95_penalty_s':float(np.quantile([r['penalty_s'] for r in rs],.95)),
        'p99_penalty_s':float(np.quantile([r['penalty_s'] for r in rs],.99)),
        'mean_wait_s':float(np.mean([r['wait_s'] for r in rs]))} for p,rs in base.items()}
    # Each original system contributes one point; avoid pretending nodes/runs are independent.
    spec('eval-trace-system-benefit','barh','LRU minus AegisKV mean (s)','',evidence='trace-driven model',height=6.0)
    for i,system in enumerate(sorted({r['system'] for r in intervals})):
        means={p:np.mean([r['penalty_s'] for r in rs if r['system']==system]) for p,rs in base.items()}
        add('eval-trace-system-benefit','Paired system means',i,means['LRU']-means['AegisKV model'],f'System {system}')
    # Modern training alerts are audited separately, never stitched across shifted jobs.
    jobs=[json.loads(l) for l in (TRACE/'reflex/llm_alert_trace.jsonl').open()]
    nalerts=sum(len(j['events']) for j in jobs);labels=Counter(v for j in jobs for v in j['ip_status'].values())
    counted=[];missing=0
    for j in jobs:
        bad={ip for ip,v in j['ip_status'].items() if v=='faulty'}
        present={e['ip'] for e in j['events']};missing+=len(bad-present)
        counted.append(len(bad))
    spec('eval-modern-trace-labels','cdf','Fault-labeled nodes per job','Training job fraction','fraction','observed trace')
    cdf('eval-modern-trace-labels','Reflex (98 jobs)',counted)
    SUMMARY['reflex']={'jobs':len(jobs),'alerts':nalerts,'labels':dict(labels),'faulty_nodes_without_alert':missing,
      'scope':'Job-conditioned node labels, not timestamped outage/recovery; no cross-job failure rate or calendar replay.'}

def layer_model(overlap=True,hot=True,density=.5,compute=3.,accuracy=1.):
    """Eight synthetic layer payloads; one current + one next-layer buffer.

    Predicted demand gets one-layer lookahead; unknown demand waits for the
    previous layer. DRAM holds two equal payloads. No claim of native accuracy.
    Storage/H2D are serial, GPU strictly ordered. A wrong prefetch consumes one
    extra read, then demand is read at reveal time. Payload density is fixed
    across all policies; it never changes the attention algorithm.
    """
    layers=8;resident={0,1} if hot else {6,7};ssd=0.;h2d=0.;gpu=0.;ends=[];events=[]
    correct=set(range(round(layers*accuracy)))
    for layer in range(layers):
        release=ends[layer-2] if overlap and layer>=2 else (0 if overlap else gpu)
        demand_reveal=ends[layer-1] if layer else 0.
        io=4*density;copy=density
        if layer not in correct:
            start=max(ssd,release);ssd=start+io
            events.append(('unused',layer,start,ssd))
            release=max(release,demand_reveal)
        if layer not in resident:
            start=max(ssd,release);ssd=start+io;ready=ssd
            events.append(('ssd',layer,start,ssd))
        else:ready=release
        start=max(h2d,ready);h2d=start+copy;events.append(('h2d',layer,start,h2d))
        start=max(gpu,h2d);gpu=start+compute;ends.append(gpu);events.append(('gpu',layer,start,gpu))
    return gpu,gpu-layers*compute,events

def rental_stream(rental=True,hysteresis=.2,renew=True):
    """Isolated, equal-byte tier with additive values and deterministic drift.

    Every accepted migration pays the same cost; all policies revalue the full
    replacement. This tests a screening heuristic, not the nonadditive DAG
    controller. Credit-renewal opportunities occur at the same revisit events.
    """
    resident=set(range(8));rho=0.;keys={i:2.+(i%3)*.2 for i in resident}
    migrations=0;revalues=0;miss=0.;movement=0.;history=[]
    for step in range(512):
        values={i:1.5+.8*math.sin(step/18+i*.63)+.35*(i//8==(step//64)%3) for i in range(24)}
        candidate=(step*7)%24
        if candidate in resident:
            if renew:keys[candidate]=rho+values[candidate]
        else:
            if rental:
                victim=min(resident,key=lambda i:(keys[i],i));trial=max(rho,keys[victim])
                allowed=rho+values[candidate]>trial+1e-12
            else:
                victim=min(resident,key=lambda i:(values[i],i));trial=rho;allowed=True
            if allowed:
                revalues+=1;gain=values[candidate]-values[victim]
                if gain>hysteresis+.1:
                    resident.remove(victim);resident.add(candidate);keys.pop(victim)
                    rho=trial;keys[candidate]=rho+values[candidate];migrations+=1;movement+=.1
        # Exogenous next-use request is identical across policies.
        request=(step*11+step//64)%24
        if request not in resident:miss+=values[request]
        history.append(dict(step=step,miss=miss,migrations=migrations,revalues=revalues,movement=movement,rent=rho))
    return history

def ablations_and_costs():
    spec('eval-layer-factorial','line','Selected KV fraction (%)','Recovery completion (ms)','ms')
    for hot,overlap,label in [(False,False,'Late, serial'),(True,False,'Early, serial'),(False,True,'Late, pipeline'),(True,True,'Early, pipeline')]:
        for d in [.125,.25,.5,.75,1]:add('eval-layer-factorial',label,d*100,layer_model(overlap,hot,d)[0])
    spec('eval-sparse-misses','line','Correct prefetches (%)','Recovery completion (ms)','ms')
    for hot,label in [(False,'Late-layer DRAM'),(True,'Early-layer DRAM')]:
        for a in np.linspace(0,1,9):add('eval-sparse-misses',label,a*100,layer_model(True,hot,1,accuracy=a)[0])
    spec('eval-layer-exposure','barh','Completion time (ms)','',unit='ms',height=3.6)
    for i,(hot,overlap,label) in enumerate([(False,False,'Late, serial'),(True,False,'Early, serial'),(False,True,'Late, pipeline'),(True,True,'Early, pipeline')]):
        total,wait,ev=layer_model(overlap,hot,1)
        add('eval-layer-exposure','Required compute',i,total-wait,label)
        add('eval-layer-exposure','Exposed I/O wait',i,wait,label)
        RAW['layer-events'].extend(dict(case=label,resource=e[0],layer=e[1],start_ms=e[2],end_ms=e[3]) for e in ev)
    SPECS['eval-layer-exposure']['kind']='stackh'
    spec('eval-rental-churn','line','Admission opportunities','Accepted migrations','count')
    spec('eval-rental-revaluation','barh','Count over 512 opportunities','',unit='count',height=3.6)
    spec('eval-rental-cost','barh','Modeled cumulative cost','',unit='cost units',height=3.6)
    cases=[('Direct value',False,.2,True),('Trial rent',True,.2,True),('No hysteresis',True,0,True),('No renewal',True,.2,False)]
    SUMMARY['rental']={}
    for i,(label,rental,h,renew) in enumerate(cases):
        history=rental_stream(rental,h,renew)
        for v in history[::8]+history[-1:]:add('eval-rental-churn',label,v['step'],v['migrations'])
        end=history[-1];SUMMARY['rental'][label]=end
        add('eval-rental-revaluation','Joint revaluations',i,end['revalues'],label)
        add('eval-rental-cost','Next-use miss cost',i,end['miss'],label)
        add('eval-rental-cost','Migration cost',i,end['movement'],label)
        RAW['rental-events'].extend(dict(policy=label,**row) for row in history)
    SPECS['eval-rental-cost']['kind']='stackh'
    spec('eval-rate-break-even','line','Fault probability per horizon','Net expected saving (s)')
    delta=loss('LRU')[0]-loss('AegisKV model')[0]
    for overhead in [.01,.05,.2]:
        for p in np.linspace(0,.2,41):add('eval-rate-break-even',f'Healthy cost {overhead:g} s',p,p*delta-overhead)
    SUMMARY['layer']={label:layer_model(overlap,hot,1)[0] for hot,overlap,label in [
        (False,False,'late_serial'),(True,False,'early_serial'),(False,True,'late_pipeline'),(True,True,'early_pipeline')]}

def write_csv(p,rows):
    with p.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def main():
    OUT.mkdir(parents=True,exist_ok=True);(OUT/'raw').mkdir(exist_ok=True)
    inherited();single_failure();traces();ablations_and_costs()
    for name,rows in TABLES.items():write_csv(OUT/(name+'.csv'),rows)
    for name,rows in RAW.items():write_csv(OUT/'raw'/(name+'.csv'),rows)
    (DOC/'figure-specs.json').write_text(json.dumps(SPECS,indent=2)+'\n')
    (OUT/'summary.json').write_text(json.dumps(SUMMARY,indent=2)+'\n')
    source_files=[Path(__file__),t.CONFIG,Path(t.__file__),t.OUT/'manifest.json',
       TRACE/'lanl/failure-data.csv',TRACE/'lanl/SOURCE.json',TRACE/'reflex/llm_alert_trace.jsonl',TRACE/'reflex/SOURCE.json']
    source_files+=list(t.OUT.glob('*.csv'))
    manifest={'version':'expanded-v1','physical_runs':0,'evidence':'per-table',
      'source_files':{str(p.relative_to(ROOT)):sha(p) for p in source_files},
      'tables':{p.name:sha(p) for p in OUT.glob('*.csv')},
      'raw_tables':{p.name:sha(p) for p in (OUT/'raw').glob('*.csv')},
      'spec_sha256':sha(DOC/'figure-specs.json'),
      'trace_scope':'Historical compute-node outages; conditional FIFO spare-pool model, fixed one workflow/outage. Node repair times not used as GPU service/repair measurements. Reflex labels are a separate observation only.',
      'uncertainty':'Deterministic scenarios and finite trace descriptions: no fabricated physical repeats or CIs.'}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'figures':len(SPECS),'summary':SUMMARY},indent=2))

if __name__=='__main__':main()
