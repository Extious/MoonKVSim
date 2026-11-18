#!/usr/bin/env python3
"""Single-column evaluation renderer. Layout stays fixed when CSV values change.

Each table has an independent evidence label. Measured replacements require raw
provenance, an aggregation command and campaign count, not just a changed badge.
"""
import argparse,csv,hashlib,json,math,shutil,subprocess
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.ticker import FuncFormatter,MaxNLocator
from matplotlib import font_manager
from plot import ROOT,WIDTH

DEFAULT=ROOT/'experiments/data/eurosys27/expanded'
SPEC=ROOT/'experiments/eurosys27/figure-specs.json'
OUT=ROOT/'exports/evaluation-expanded-20260921/figures'
BADGES={'analytical':'Analytical model','observed trace':'Observed trace',
        'trace-driven model':'Trace-driven model','measured':'Measured'}
COLORS=['#367DA2','#CC8846','#669C8C','#8C7EA6','#9099A1','#A2676C']
STYLE={
    'Storage only':('#859099','--','v'), 'LRU':(COLORS[1],'--','s'),
    'Reuse only':(COLORS[2],':','^'), 'AegisKV model':(COLORS[0],'-','o'),
    'AegisKV':(COLORS[0],'-','o'), 'Feasible oracle':(COLORS[3],'-.','D'),
    'All DRAM':('#515C67',':','x'),
    'Join slack':('#A7B1B8','-','^'),
    'No dependencies':('#A7B1B8',':','^'),
    'No reuse value':('#C5CDD2','-.','D'),
}
HATCH=['','//','..','\\\\','--','xx']

def setup():
    # Use the manuscript's text face when TeX is installed; keep a portable
    # serif fallback for running the same plotting interface elsewhere.
    family='DejaVu Serif'
    try:
        path=Path(subprocess.check_output(['kpsewhich','LinLibertine_R.otf'],text=True).strip())
        if path.is_file():
            font_manager.fontManager.addfont(str(path))
            family=font_manager.FontProperties(fname=path).get_name()
    except (OSError,subprocess.CalledProcessError):pass
    plt.rcParams.update({'font.family':family,'font.size':10.3,
        'axes.labelsize':10.3,'axes.labelpad':2.8,'legend.fontsize':10.3,
        'xtick.labelsize':10.3,'ytick.labelsize':10.3,'pdf.fonttype':42,
        'ps.fonttype':42,'svg.fonttype':'none','axes.spines.top':False,
        'axes.spines.right':False,'axes.linewidth':.6,'lines.linewidth':1.3,
        'axes.edgecolor':'#525A61','text.color':'#252A30','axes.labelcolor':'#252A30',
        'xtick.color':'#454C52','ytick.color':'#454C52','xtick.major.size':2.5,
        'ytick.major.size':2.5,'xtick.major.pad':2.5,'ytick.major.pad':2.5,
        'hatch.linewidth':.4,'savefig.dpi':220,'axes.axisbelow':True})
    return family

def compact_legend(fig,ax,series,height):
    """Fit a compact legend above the axes without ever covering the data."""
    if len(series)<2:return None,0
    handles,labels=ax.get_legend_handles_labels()
    for ncols in range(min(3,len(series)),0,-1):
        legend=fig.legend(handles,labels,loc='upper center',
            bbox_to_anchor=(.5,1-.20/height),frameon=False,ncol=ncols,
            borderaxespad=0,labelspacing=.12,columnspacing=.9,
            handlelength=1.9,handletextpad=.38)
        fig.canvas.draw()
        bounds=legend.get_window_extent(fig.canvas.get_renderer())
        if bounds.width/fig.dpi<=WIDTH-.13:
            return legend,bounds.height/fig.dpi
        legend.remove()
    raise ValueError('Legend needs shorter labels or a source-level re-layout')

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(data,specfile):
    manifest=json.loads((data/'manifest.json').read_text());specs=json.loads(specfile.read_text())
    if sha(specfile)!=manifest['spec_sha256']:raise ValueError('Visual specification hash mismatch')
    for source,digest in manifest['source_files'].items():
        if sha(ROOT/source)!=digest:raise ValueError('Changed source; regenerate: '+source)
    for source,digest in manifest.get('raw_tables',{}).items():
        if sha(data/'raw'/source)!=digest:raise ValueError('Changed derived event log: '+source)
    measured=any(s['evidence']=='measured' for s in specs.values())
    if measured:
        if not manifest.get('raw_sources') or not manifest.get('aggregation_command') or not manifest.get('statistical_unit'):
            raise ValueError('Measured input requires raw sources, aggregation and statistical unit')
        for r in manifest['raw_sources']:
            if sha(data/r['path'])!=r['sha256']:raise ValueError('Measured raw-source hash mismatch')
    tables={}
    for name,spec in specs.items():
        p=data/(name+'.csv')
        if sha(p)!=manifest['tables'][p.name]:raise ValueError('Table hash mismatch: '+name)
        rows=list(csv.DictReader(p.open()))
        if not rows:raise ValueError('Empty figure table: '+name)
        for r in rows:
            if r['figure']!=name or r['unit']!=spec['unit'] or r['evidence']!=spec['evidence']:
                raise ValueError('Table semantic mismatch: '+name)
            for k in ['x','y','lower','upper']:
                r[k]=float(r[k]) if r[k]!='' else None
                if r[k] is not None and not math.isfinite(r[k]):raise ValueError('Nonfinite value')
            if r['x'] is None or r['y'] is None:raise ValueError('Missing plotted value')
            if (r['lower'] is None)!=(r['upper'] is None):raise ValueError('Unpaired interval bounds')
            if r['lower'] is not None and r['lower']>r['upper']:raise ValueError('Reversed interval')
            if spec['evidence']!='measured' and (int(r['independent_runs']) or r['lower'] is not None):
                raise ValueError('Non-measured tables must not invent runs or confidence intervals')
            if spec['evidence']=='measured' and int(r['independent_runs'])<1:raise ValueError('No independent campaigns')
            if spec['evidence']=='measured' and r['source_id'] not in {src['id'] for src in manifest['raw_sources']}:
                raise ValueError('Measured row source is absent from raw provenance')
        tables[name]=rows
    return specs,tables

def short(s):
    return {'AegisKV model':'Workflow value','Feasible oracle':'Feasible oracle',
        'No dependencies':'No DAG','No reuse value':'No reuse term',
        'Static value model':'Static value model','One-minute timestamp resolution':'Recorded start groups',
        'Evenly spaced control':'Even spacing','Within-minute spread':'Within-minute',
        'Sum of local penalties':'Local penalty sum'}.get(s,s)
def tick(v,pos=None):
    if abs(v)>=1e6:return f'{v/1e6:g}M'
    if abs(v)>=1e3:return f'{v/1e3:g}k'
    return f'{v:g}'
def extents(rows,key='y'):
    out=[r[key] for r in rows]
    if key=='y':out += [r[k] for r in rows for k in ['lower','upper'] if r[k] is not None]
    return min(out),max(out)

def render(data,out,specfile,publish=False):
    family=setup();specs,tables=verify(data,specfile);out.mkdir(parents=True,exist_ok=True)
    review=[]
    for name,s in specs.items():
        rows=tables[name];series=list(dict.fromkeys(r['series'] for r in rows));kind=s['kind']
        bar=kind in ['barh','stackh'];vertical=kind=='barv'
        height=s.get('height',2.25)
        fig,ax=plt.subplots(figsize=(WIDTH,height))
        fig.subplots_adjust(left=.30 if bar else .18,right=.972,bottom=.42/height,top=1-.24/height)
        if bar:
            categories=list(dict.fromkeys(r['category'] for r in rows));n=len(categories)
            ax.set_yticks(np.arange(n),[short(c) for c in categories])
            positive=np.zeros(n);negative=np.zeros(n)
            for j,ser in enumerate(series):
                rs=[next(r for r in rows if r['category']==cat and r['series']==ser) for cat in categories]
                values=np.array([r['y'] for r in rs]);color=STYLE.get(ser,(COLORS[j%len(COLORS)],))[0]
                if kind=='stackh':
                    left=np.where(values>=0,positive,negative)
                    ax.barh(np.arange(n),values,left=left,height=.55,label=short(ser),color=color,
                        edgecolor='#45515A',linewidth=.4,hatch=HATCH[j%6])
                    positive+=np.maximum(values,0);negative+=np.minimum(values,0)
                else:
                    bh=.76/len(series);positions=np.arange(n)+(j-(len(series)-1)/2)*bh
                    # In one-series comparisons the category itself is the
                    # policy. Keep its color identical to the line figures.
                    colors=[STYLE.get(cat,(color,))[0] for cat in categories] if len(series)==1 else color
                    ax.barh(positions,values,height=min(.52,bh*.85),label=short(ser),color=colors,
                        edgecolor='#45515A',linewidth=.4,hatch=HATCH[j%6])
                    for pos,r in zip(positions,rs):
                        if r['lower'] is not None:ax.hlines(pos,r['lower'],r['upper'],color='black',lw=1)
            ax.set_ylim(n-.5,-.5);ax.set_xlabel(s['xlabel']);ax.grid(axis='x',color='#E3E7EA',lw=.45)
            ax.spines['left'].set_visible(False);ax.tick_params(axis='y',length=0)
            lo,hi=extents(rows)
            if kind=='stackh':lo=min(lo,min(negative));hi=max(hi,max(positive))
            span=max(hi-lo,.01);ax.set_xlim(min(0,lo)-(.06*span if lo<0 else 0),max(0,hi)+.09*span)
            ax.xaxis.set_major_locator(MaxNLocator(4));ax.xaxis.set_major_formatter(FuncFormatter(tick))
        elif vertical:
            if len(series)!=1:raise ValueError('Categorical column chart expects one series')
            xx=np.arange(len(rows));values=np.array([r['y'] for r in rows])
            ax.bar(xx,values,width=.62,color=[COLORS[0] if y>=0 else COLORS[1] for y in values],
                edgecolor='#45515A',linewidth=.35)
            for x,r in zip(xx,rows):
                if r['lower'] is not None:ax.vlines(x,r['lower'],r['upper'],color='black',lw=.8)
            ax.set_xticks(xx,[r['category'].removeprefix('System ') for r in rows],rotation=90)
            ax.set(xlabel=s['xlabel'],ylabel=s['ylabel'],xlim=(-.7,len(rows)-.3))
            lo,hi=extents(rows);span=max(hi-lo,.01)
            ax.set_ylim(min(0,lo)-(.07*span if lo<0 else 0),max(0,hi)+.1*span)
            ax.yaxis.set_major_locator(MaxNLocator(4));ax.yaxis.set_major_formatter(FuncFormatter(tick))
            ax.grid(axis='y',color='#E3E7EA',lw=.45)
        else:
            for j,ser in enumerate(series):
                rs=sorted((r for r in rows if r['series']==ser),key=lambda r:r['x'])
                xx=[r['x'] for r in rs];yy=[r['y'] for r in rs]
                if kind=='cdf':xx=[xx[0]]+xx;yy=[0]+yy
                color,ls,marker=STYLE.get(ser,(COLORS[j%6],['-','--',':','-.'][j%4],['o','s','^','D'][j%4]))
                if kind=='cdf':ls=['--','-',':','-.',(0,(4,1,1,1,1,1))][j%5]
                ax.plot(xx,yy,label=short(ser),color=color,ls=ls,
                    marker=None if kind=='step' or len(xx)>30 else marker,
                    lw=1.55 if ser=='AegisKV model' else 1.2,ms=3.1,mfc='white',mew=.8,
                    drawstyle='steps-post' if kind in ['cdf','step'] else 'default')
                for r in rs:
                    if r['lower'] is not None:ax.vlines(r['x'],r['lower'],r['upper'],color=color,lw=.8)
            ax.set(xlabel=s['xlabel'],ylabel=s['ylabel']);ax.grid(axis='y',color='#E3E7EA',lw=.45)
            lo,hi=extents(rows)
            if kind=='cdf':ax.set_ylim(0,1.035);ax.set_yticks([0,.5,1])
            elif not s.get('ylog'):
                span=max(hi-lo,.01);ax.set_ylim(min(0,lo)-(.06*span if lo<0 else 0),hi+.1*span)
                ax.yaxis.set_major_locator(MaxNLocator(4))
            if s.get('xlog'):
                if min(r['x'] for r in rows)<=0:raise ValueError('Log x requires positive values')
                ax.set_xscale('log');lo,hi=extents(rows,'x')
                powers=np.arange(math.floor(math.log10(lo)),math.ceil(math.log10(hi))+1)
                if len(powers)>5:powers=powers[::math.ceil(len(powers)/5)]
                ax.set_xticks([10.**p for p in powers if lo/1.1<=10.**p<=hi*1.1])
                ax.minorticks_off()
            else:ax.xaxis.set_major_locator(MaxNLocator(4,integer=name in ['eval-modern-trace-labels','eval-common-fault','eval-burst-interference']))
            if s.get('ylog'):
                if extents(rows)[0]<=0:raise ValueError('Log y requires positive values')
                ax.set_yscale('log');ax.minorticks_off()
            ax.xaxis.set_major_formatter(FuncFormatter(tick));ax.yaxis.set_major_formatter(FuncFormatter(tick))
        if any(r['y']<0 for r in rows):ax.axhline(0,color='#444444',lw=.65) if not bar else ax.axvline(0,color='#444444',lw=.65)
        if name=='eval-paired-benefit':ax.axvline(0,color='#444444',lw=.8,ls=':')
        # Matplotlib's locators include off-axis sentinel ticks that are not
        # drawn. Remove them before the text-bounds review, without cropping data.
        for axis,limits in [(ax.xaxis,ax.get_xlim()),(ax.yaxis,ax.get_ylim())]:
            low,high=sorted(limits)
            axis.set_ticks([v for v in axis.get_ticklocs() if low<=v<=high])
        fig.text(.972,1-.035/height,BADGES[s['evidence']],ha='right',va='top',fontsize=10.3,color='#667078')
        legend,legend_height=compact_legend(fig,ax,series,height)
        top_inches=.23+legend_height+(.06 if legend else 0)
        # Measure fixed label wording, not values, to allocate category space.
        fig.canvas.draw();renderer=fig.canvas.get_renderer()
        if bar:
            label_width=max(t.get_window_extent(renderer).width for t in ax.get_yticklabels())/fig.dpi
            left_inches=label_width+.11
        else:
            left_inches=.60
        bottom_inches=.46 if vertical else .41
        fig.subplots_adjust(left=left_inches/WIDTH,right=.972,
            bottom=bottom_inches/height,top=1-top_inches/height)
        fig.canvas.draw();renderer=fig.canvas.get_renderer();canvas=fig.bbox
        clipped=[]
        for item in fig.findobj(matplotlib.text.Text):
            if item.get_visible() and item.get_text():
                b=item.get_window_extent(renderer)
                if b.width and (b.x0<-.8 or b.y0<-.8 or b.x1>canvas.width+.8 or b.y1>canvas.height+.8):
                    clipped.append(item.get_text())
        review.append(dict(figure=name,width_in=WIDTH,height_in=height,evidence=s['evidence'],
            font_family=family,legend_columns=legend._ncols if legend else 0,
            plot_height_in=ax.get_position().height*height,out_of_canvas=clipped))
        for ext in ['pdf','svg','png']:fig.savefig(out/(name+'.'+ext),facecolor='white',dpi=210)
        if publish:
            shutil.copy2(out/(name+'.pdf'),ROOT/'paper/figures'/(name+'.pdf'))
            shutil.copy2(out/(name+'.png'),ROOT/'paper/figures/preview'/(name+'.png'))
        plt.close(fig)
    (out/'render-review.json').write_text(json.dumps(review,indent=2)+'\n')
    (out/'render-manifest.json').write_text(json.dumps(dict(
        renderer_sha256=sha(Path(__file__)),input_manifest_sha256=sha(data/'manifest.json'),
        visual_spec_sha256=sha(specfile),canvas_width_in=WIDTH,font_family=family,
        exports={p.name:sha(p) for p in out.glob('eval-*') if p.suffix in ['.pdf','.svg','.png'] and '-review' not in p.stem}),indent=2)+'\n')
    print(json.dumps({'figures':len(review),'clipping':[r for r in review if r['out_of_canvas']]},indent=2))
    if any(r['out_of_canvas'] for r in review):raise SystemExit('Fix canvas clipping before delivery')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,default=DEFAULT)
    p.add_argument('--spec',type=Path,default=SPEC);p.add_argument('--out',type=Path,default=OUT)
    p.add_argument('--publish',action='store_true');a=p.parse_args();render(a.data,a.out,a.spec,a.publish)
