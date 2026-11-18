#!/usr/bin/env python3
"""Compact plots from existing data; no new fitting or measurements."""
from pathlib import Path
import csv,json,hashlib,subprocess,shutil
import numpy as np
import matplotlib.pyplot as plt
from matplotlib import font_manager
ROOT=Path(__file__).resolve().parents[3];OUT=ROOT/'exports/system-design-submit-review-20260921'
font=Path(subprocess.check_output(['kpsewhich','LinLibertine_R.otf'],text=True).strip());font_manager.fontManager.addfont(str(font))
plt.rcParams.update({'font.family':font_manager.FontProperties(fname=str(font)).get_name(),'font.size':10.3,'axes.labelsize':10.3,'xtick.labelsize':10.3,'ytick.labelsize':10.3,'legend.fontsize':10.3,'pdf.fonttype':42,'axes.spines.top':False,'axes.spines.right':False})
def save(f,name):
 for ext in ['pdf','png','svg']:f.savefig(OUT/'figures'/f'{name}.{ext}',dpi=220)
 plt.close(f)

def tracker():
 corr=list(csv.DictReader((ROOT/'exports/design-figure-revision-20260920/data/tracker-correlations.csv').open()))
 raw=list(csv.DictReader((ROOT/'experiments/data/agent-gbdt-steps/primary-landmark.csv').open()))
 assert len(raw)==1443 and len({r['workflow_id'] for r in raw})==170
 f=plt.figure(figsize=(3.33465,3.30))
 ax=f.add_axes([.43,.665,.54,.285]);x=np.array([float(r['spearman_rho']) for r in corr]);lo=np.array([float(r['lower95']) for r in corr]);hi=np.array([float(r['upper95']) for r in corr])
 ax.errorbar(x,np.arange(6),xerr=[x-lo,hi-x],fmt='o',color='#23688D',ms=3.5,capsize=2,lw=.9)
 ax.axvline(0,color='#777777',ls=':',lw=.8)
 ax.set(yticks=range(6),yticklabels=['Elapsed','Input length*','Context growth*','Prior output','Prior API','Prior gap'],ylim=(5.6,-.6),xlim=(-.4,.4),xticks=[-.4,0,.4],xlabel='Spearman ρ')
 ax.tick_params(axis='y',length=0,pad=4);ax.spines['left'].set_visible(False)
 ax.xaxis.labelpad=1;f.text(.015,.985,'(a)',va='top')
 ax=f.add_axes([.16,.14,.81,.29]);stats={};source_y=np.array([float(r['actual_remaining_s']) for r in raw])
 for method,label,color,ls in [('median','Median','#68747A',':'),('gbdt_basic','GBDT','#23688D','-'),('gbdt_history','+ history','#9B6428','--')]:
  pred=np.array([float(r[method+'_s']) for r in raw]);errors=np.abs(pred-source_y)
  vals=np.sort(errors);ax.step(np.r_[0,vals],np.r_[0,np.arange(1,len(vals)+1)/len(vals)],where='post',color=color,ls=ls,lw=1.2,label=label)
  stats[method]={'mae_s':float(errors.mean()),'within50_pct':float(np.mean(errors/source_y<=.5)*100),'max_abs_error_s':float(errors.max())}
 ax.set_xscale('symlog',linthresh=1)
 ax.set(xlim=(0,max(s['max_abs_error_s'] for s in stats.values())*1.05),ylim=(0,1),xticks=[0,10,100,1000,10000],xticklabels=['0','10','100','1k','10k'],yticks=[0,.5,1],xlabel='Absolute error (s)',ylabel='Agent fraction')
 ax.xaxis.labelpad=1;ax.yaxis.labelpad=1;ax.grid(color='#E0E5E8',lw=.5)
 f.text(.015,.49,'(b)',va='top')
 ax.legend(loc='lower center',bbox_to_anchor=(.5,1.005),ncol=3,frameon=False,handlelength=.95,handletextpad=.25,columnspacing=.65,borderpad=0)
 save(f,'tracker-correlations')
 (OUT/'data/tracker-audit.json').write_text(json.dumps({'n_agents':1443,'n_workflows':170,'target':'whole-Agent remaining seconds, request 2','training':'existing workflow-disjoint OOF; no refitting or outcome filtering','stats':stats,'paired_basic_minus_median_ci_s':[-80.9,4.9],'supports':'uncertainty fallback; does not establish accurate segment Slack','raw_sha256':hashlib.sha256((ROOT/'experiments/data/agent-gbdt-steps/primary-landmark.csv').read_bytes()).hexdigest()},indent=2)+'\n')

def value():
 f,ax=plt.subplots(figsize=(3.33465,1.85));f.subplots_adjust(left=.16,right=.98,bottom=.28,top=.97)
 s=np.linspace(0,20,401)
 for name,slow,fast,size,col,ls in [('A',4,2,2,'#9B6428','--'),('B',18,8,1,'#23688D','-')]:
  g=(np.maximum(0,slow-s)-np.maximum(0,fast-s))/size
  ax.plot(s,g,color=col,ls=ls,lw=1.3,label=f'{name}: {size} '+('unit' if size==1 else 'units'))
 ax.scatter([0],[1],marker='s',s=20,color='#9B6428',clip_on=False,zorder=4)
 ax.scatter([6],[10],marker='o',s=20,color='#23688D',zorder=4)
 ax.annotate('A: slack 0',(0,1),xytext=(3,3.0),arrowprops={'arrowstyle':'-','color':'#9B6428','lw':.6})
 ax.annotate('B: slack 6',(6,10),xytext=(1,7),arrowprops={'arrowstyle':'-','color':'#23688D','lw':.6})
 ax.set(xlabel='Slack (s)',ylabel='WCT saved / unit (s)',xlim=(0,20),ylim=(0,12),xticks=[0,5,10,15,20],yticks=[0,5,10])
 ax.xaxis.labelpad=1;ax.yaxis.labelpad=1;ax.grid(color='#E0E5E8',lw=.5);ax.legend(loc='upper right',frameon=False,borderpad=.05,labelspacing=.1,handlelength=1)
 save(f,'retention-value')

def original_pipeline():
 archive=ROOT/'Archived/peer-hbm-paper-before-storage-20260920/figures'
 for ext in ['pdf','png']:
  src=archive/('preview' if ext=='png' else '')/f'recovery-pipeline.{ext}'
  shutil.copy2(src,OUT/'figures'/src.name)
 manifest=ROOT/'Archived/paper-overleaf-20260919/paper/figures/design-single/MANIFEST.json'
 old=json.loads(manifest.read_text());(OUT/'data/original-pipeline-manifest.json').write_text(json.dumps(old,indent=2)+'\n')
 # Audit raw means/calibration against the preserved figure parameters.
 sparse=ROOT/'experiments/native-sparse/20260915'
 rows=[r for r in csv.DictReader((sparse/'needed_fraction_models.csv').open()) if r['model']=='MiniCPM4-8B' and int(r['M'])==32768 and int(r['replay_queries'])==64]
 assert rows
 for field,mkey in [('preload_fraction_matched','h'),('effective_fraction_hot_first_matched','effective_fraction')]:
  grouped={}
  for r in rows:grouped.setdefault(int(r['layer']),[]).append(float(r[field]))
  assert len(grouped)==32
  assert abs(np.mean([np.mean(v) for v in grouped.values()])-old[mkey])<1e-10
 (OUT/'data/pipeline-provenance.json').write_text(json.dumps({'restored_from':str(archive),'manifest':str(manifest),'evidence':'homogeneous analytical schedule with measured compute and trace-derived fractions; H2D bandwidth assumed','pdf_sha256':hashlib.sha256((OUT/'figures/recovery-pipeline.pdf').read_bytes()).hexdigest(),'matches_archived_pdf':True,'new_runs':0,'limitations':['ideal preemptible transfer stream','homogeneous layer/document means','no bounded staging or foreground queues','layer-granularity miss reveal, not a per-query execution trace','32K fixed history and 64-token tail, not the latest 1M microbenchmark']},indent=2)+'\n')
 print({k:old[k] for k in ['h','effective_fraction','C_ms','D_ms','peer_layers','peer_mib','waits_ms','totals_ms']})

if __name__=='__main__':
 for d in ['data','figures']:(OUT/d).mkdir(parents=True,exist_ok=True)
 tracker();value();original_pipeline()
