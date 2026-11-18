import hashlib,json,pathlib,re,statistics,fitz
b=pathlib.Path('benchmark/AegisKV').resolve();root=b.parents[1];out=b/'exports/motivation-measured-exposure-20260921'
data=json.loads((b/'experiments/data/motivation-compact-cc/recovery-costs-measured.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,digest in data['source_sha256'].items():assert sha(root/name)==digest,name
preserved=json.loads((out/'sources/preserved-figure1-sha256.json').read_text());assert all(sha(root/k)==v for k,v in preserved.items())
chapter=(b/'paper/background_and_motivation.tex').read_text();md=(b/'paper/paper_draft.md').read_text();chapter_md=md[md.index('## 2. Background and Motivation'):md.index('## 3. AegisKV Design')]
assert not any(x in chapter for x in ['static estimates','Qwen3-14B','64-token tail','@@'])
assert not any(x in chapter_md for x in ['静态重建成本','@@'])
for c in data['workflow_costs']:
 assert statistics.median(c['trials_s'])==c['recompute_s']
 assert abs(c['absorbed_s']+c['wct_increase_s']-c['recompute_s'])<1e-9
 assert f"{c['recompute_s']:.1f}" in chapter and f"{c['wct_increase_s']:.1f}" in chapter
ledger=json.loads((b/'experiments/data/reuse-physical-qwen25-1m/blsc/budget.json').read_text());jobs=[j for j in ledger['jobs'] if j.get('job_id') in data['job_ids']]
assert len(jobs)==2 and all(j['terminal'] for j in jobs)
run_seconds=sum(j['actual_gpu_seconds'] for j in jobs);assert run_seconds==1816
log=(out/'review/build.log').read_text();assert 'Output written on ' in log or 'Nothing to do' in log
assert not re.search(r'(?:LaTeX Error|Undefined control sequence|undefined references|undefined citations)',log)
scoped_log=log.split('(./background_and_motivation.tex',1)[1].split('(./system_design.tex',1)[0] if '(./background_and_motivation.tex' in log else ''
assert 'Overfull' not in scoped_log
unrelated_overfull=sorted(set(re.findall(r'Overfull[^\n]+',log)))
font=json.loads((out/'review/figure2-fonts.json').read_text());assert not font['findings'];assert font['sha256']==sha(b/'paper/figures/recovery-exposure.pdf')
pdf=fitz.open(b/'paper/main.pdf');current_sources=[b/'paper'/n for n in ['main.tex','abstract.tex','background_and_motivation.tex','system_design.tex','references.bib']]
source_hashes={str(p.relative_to(root)):sha(p) for p in current_sources}
stale=[str(p) for p in current_sources if p.stat().st_mtime>(b/'paper/main.pdf').stat().st_mtime]
actual_chart_fonts=[s['size'] for p in pdf for bl in p.get_text('dict')['blocks'] if 'lines' in bl for ln in bl['lines'] for s in ln['spans'] if s['text']=='Measured Prefill time (s)']
assert len(actual_chart_fonts)==1 and actual_chart_fonts[0]>=10
raw_snapshots={}
for j in jobs:
 jid=j['job_id'];p=b/f'experiments/data/reuse-physical-qwen25-1m/blsc/results/{jid}'
 m=json.loads((p/'metadata.json').read_text());assert m['sharedfs'] is None and 'SharedFS_no_overlap' not in m['paths'];assert not list(p.glob('storage-rank*'))
 raw_snapshots[jid]={'terminal_state':j['last_slurm_state'],'gpu_seconds':j['actual_gpu_seconds'],'contexts':m['contexts'],'host':m['host'],'shared_storage_kv_created':False}
review={'scientific_checks':{'physical_prefill_not_physical_wct':True,'configuration_fields_matched_to_figure1c':len(data['configuration']),'repeats_per_point':3,'warmups_per_point':1,'error_bars':'min/max within the completed allocation, not CI or across-allocation variation','interrupted_point_excluded_as_whole_and_preserved':True,'timing_snapshot_prefix_hash_verified':True,'figure1_original_assets_unchanged':True,'old_static_data_preserved':True,'single_branch_join_arithmetic_verified':True},'physical_runs':raw_snapshots,'this_revision_gpu_seconds':run_seconds,'this_revision_gpu_hours':run_seconds/3600,'cumulative_gpu_seconds':20043,'registered_cap_gpu_seconds':20700,'font_review':font,'actual_chart_font_pt_in_manuscript':actual_chart_fonts[0],'paper_page_count':len(pdf),'stale_manuscript_sources':stale,'source_sha256':source_hashes,'main_pdf_sha256':sha(b/'paper/main.pdf'),'figure2_png_sha256':sha(b/'paper/figures/preview/recovery-exposure.png'),'scope':'Motivation and appended measurement protocol; preserves concurrent Introduction/Design/Evaluation edits.','outside_scope_build_messages':unrelated_overfull,'visual_review':{'viewed':'Figure2 native, 96-dpi single-column color and gray; actual manuscript pages 2, 3, 21, 22','findings_fixed':'Legend moved left to clear Slack header; caption shortened without dropping evidence type.','remaining_in_scope':'None identified; no claim of full-paper review.'}}
(out/'review/AUDIT.json').write_text(json.dumps(review,indent=2)+'\n')
print(json.dumps({'passed':not stale,'source_changed_after_pdf':stale,'gpu_hours_this_revision':run_seconds/3600,'paper_pages':len(pdf),'main_pdf_sha256':review['main_pdf_sha256'],'actual_chart_font_pt':actual_chart_fonts[0],'outside_scope_overfull':unrelated_overfull},indent=2))
