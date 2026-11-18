"""Publish this reviewed AegisKV document through the authenticated official CLI.

No tokens are read or logged. Receipts prevent accidental duplicate page creation.
Only the new page and its temporary marker blocks are modified.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import argparse, hashlib, json, subprocess, time

OUT = Path(__file__).resolve().parent
ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").is_file())
PARENT = '3ed97268-72d9-8042-b289-e8a66a732158'
OLD_PAGE = '3d897268-72d9-8070-ba70-ce1bd7da4e38'
API = OUT / 'api'
API.mkdir(exist_ok=True)


def save(name, value):
    (API / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def load(name):
    return json.loads((API / name).read_text())


def cli(args, *, data=None, file=None):
    if file is not None:
        with open(file, 'rb') as f:
            p = subprocess.run(['ntn', *args], stdin=f, capture_output=True, timeout=150)
    else:
        p = subprocess.run(['ntn', *args], input=data, capture_output=True, timeout=150)
    if p.returncode:
        raise RuntimeError(p.stderr.decode(errors='replace'))
    return json.loads(p.stdout)


def api(path, method='GET', body=None):
    args = ['api', path, '-X', method]
    payload = None
    if body is not None:
        args += ['-d', '@-']
        payload = json.dumps(body, ensure_ascii=False).encode()
    return cli(args, data=payload)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def upload_one(name, path, mime, filename=None):
    receipt = f'upload-{name}.json'
    if (API / receipt).exists():
        value = load(receipt)
    else:
        value = cli(['files', 'create', '--filename', filename or path.name,
                     '--content-type', mime, '--json'], file=path)
        save(receipt, value)
    if value.get('status') != 'uploaded':
        raise RuntimeError(f'Upload not complete: {name}, {value.get("status")}')
    return name, {'id': value['id'], 'filename': value.get('filename'),
                  'sha256': sha(path), 'local_path': str(path.relative_to(ROOT))}


def upload():
    manifest = json.loads((OUT/'source-manifest.json').read_text())
    for path, digest in manifest['source_files'].items():
        assert sha(ROOT/path) == digest, f'Source changed during review: {path}'
    jobs = [(x['name'], OUT/x['asset'], 'image/png', None) for x in manifest['figures']]
    jobs += [('cover', OUT/'assets/cover.png', 'image/png', 'AegisKV-cover.png'),
             ('paper', ROOT/'benchmark/AegisKV/paper/main.pdf', 'application/pdf',
              'AegisKV-current-manuscript.pdf')]
    mapping = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(upload_one,*job) for job in jobs]):
            name, info = f.result()
            mapping[name] = info
            print('Uploaded:',name,flush=True)
    save('uploads.json',mapping)


def create():
    if (API/'created-page.json').exists():
        print('Existing publication receipt:',load('created-page.json')['id'])
        return
    save('original-notebook-before.json',api(f'v1/pages/{OLD_PAGE}'))
    save('parent-before.json',api(f'v1/pages/{PARENT}'))
    response = cli(['pages','create','--parent',f'page:{PARENT}','--json'],
                   file=OUT/'page.md')
    save('created-page-raw.json',response)
    page = response.get('page',response)
    if 'id' not in page:
        raise RuntimeError('Inspect created-page-raw.json before retrying; page may exist.')
    save('created-page.json',page)
    print('Created:',page['id'],page.get('url'),flush=True)


def rich(text, *, bold=False, color=None):
    r = {'type':'text','text':{'content':text}}
    if bold or color:
        r['annotations'] = {}
        if bold:r['annotations']['bold']=True
        if color:r['annotations']['color']=color
    return [r]


def block(kind, content):
    return {'object':'block','type':kind,kind:content}


def para(text):return block('paragraph',{'rich_text':rich(text)})


def image_block(name, caption):
    up=load('uploads.json')
    return block('image',{'type':'file_upload','file_upload':{'id':up[name]['id']},
                          'caption':rich(caption)})


def pair(left,right):
    return block('column_list',{'children':[
        block('column',{'width_ratio':0.5,'children':[left]}),
        block('column',{'width_ratio':0.5,'children':[right]})]})


def replacements():
    up=load('uploads.json')
    return {
        'NOTION_CALLOUT':[block('callout',{
            'icon':{'type':'emoji','emoji':'💡'},'color':'blue_background',
            'rich_text':rich('核心思想：DRAM 保证完整恢复覆盖，HBM 只为暴露的恢复等待加速；保护优先级服从工作流，而复制容量服从前台服务。',bold=True)})],
        'NOTION_TOC':[block('toggle',{'rich_text':rich('目录 · 点击展开',bold=True),
            'children':[block('table_of_contents',{'color':'default'})]})],
        'NOTION_FIG_SERVING':[image_block('serving_model',
            '图 1｜Agent 调用与 KV 状态的服务映射。字母表示 Agent，数字表示调用序号；并行分支的最新调用使用各自的历史前缀与新 KV。TP rank 保存相同 token 位置的不同分片。架构示意，非执行测量。')],
        'NOTION_FIG_AGENT':[pair(
            image_block('agent_value_a','图 2(a)｜分支时长与 Slack。A2 决定 join，A1 提前 91.2 s 完成。保留 trace 时间，并假设所有分支汇合。'),
            image_block('agent_value_b','图 2(b)｜相近重建代价的不同 WCT 影响。斜线为被 Slack 吸收的时间，实色为新增 WCT。重建为三次测量的中位数及范围，WCT 是单分支条件计算。'))],
        'NOTION_FIG_KV':[image_block('kv_value',
            '图 3｜历史 KV 访问集中度。32,704-token 前缀的最后 512 个 queries，64-token 历史块按 query 跨 head 去重，平均 32 层和三个 PG19 文档；带状范围为文档 min–max。回顾性统计，不代表未来命中或恢复性能。')],
        'NOTION_FIG_OVERVIEW':[image_block('system-overview',
            '图 4｜AegisKV 四组件架构。Application / Controller / Engine 三层；每台主机部署一个 TP=2 worker，每个 rank 的 HBM 同时容纳执行状态与副本。蓝色路径传输 KV，虚线路径传递控制信息；DRAM 归属具体 peer 主机。')],
        'NOTION_FIG_SELECTION':[image_block('master-selection',
            '图 5｜两级选择。(a) 暴露延迟超过 λ=17 s 的 A2/A4 获得完整 Peer DRAM 检查点。(b) K=2、L=2 的示例：所有已检查点块在 DRAM，前两层各两个热块另有 HBM 副本；尾部在恢复时重建。下方面板的访问计数为构造示例。')],
        'NOTION_FIG_PIPELINE':[image_block('recovery-pipeline',
            '图 6｜层序恢复与 miss 召回。八层构造示意：(a) 全部 KV 先载入，(b) Top-K 按层载入，(c) 前四层 Top-K 已在 HBM。橙色为开始该层后才能识别的 miss 传输；灰色为尾部重建。仅解释相对调度，不对应某个模型的实测延迟。')],
        'NOTION_FIG_DEPTH':[image_block('depth-bandwidth',
            '图 7｜HBM 深度与有效带宽的关系。32 层同质模型的解析示意，带宽归一化到 B*；上图给出消除等待所需的 L，下图给出无 HBM 时的等待（层重建时间单位）。不是模型部署参数的实测最优值。')],
        'NOTION_FIG_EVAL':[pair(
            image_block('eval-online-wct','图 8(a)｜八个 24,576-token workflow 的完成时间。wf04 发生故障，之后 AegisKV 比 Restart 少 1,585.4 ms；DRAM-only 与 AegisKV 相差至多 0.217 ms，故不单独画线。当前稿件的在线回放结果。'),
            image_block('eval-retry-length','图 8(b)｜wf04 的 retry latency 随 prompt 长度变化。NOSA-8B / 文档 10146，故障位置为调用进度 65%；包括排队与恢复服务，不是纯 GPU 重建时间。'))],
        'NOTION_FIG_NATIVE':[image_block('eval-native-topk',
            '图 9｜不同 K 下的原生 selector 覆盖诊断。Current、Recency 与未来需求 Oracle 比较 distinct future-query block coverage；点平均三个文档，须线为文档范围。不是 attention mass、物理带宽节省或 WCT 加速。')],
        'NOTION_ATTACHMENTS':[block('file',{'type':'file_upload','file_upload':{'id':up['paper']['id']},
            'name':'AegisKV-current-manuscript.pdf',
            'caption':rich('英文原稿｜当前本地 paper/main.pdf 快照，11 页；保持原文及原图。中文页面另行整理，并在适用处补充实施与证据边界。')})],
        'NOTION_PROVENANCE':[block('toggle',{
            'rich_text':rich('图像来源与版本说明',bold=True),
            'children':[
                para('整理时间：2026-10-02。内容依据 benchmark/AegisKV/paper/ 实际引入的当前章节，而非 Archived/ 的旧设计。'),
                para('当前机制：λ/Slack Agent 选择；完整 Peer DRAM 检查点；前 L 层 Top-K 的附加 HBM 副本；动态 quota。没有恢复旧版租金、credit 或共享存储层。'),
                para('图 1–7 来源：paper/figures/{serving_model,agent_value_a,agent_value_b,kv_value,system-overview,master-selection,recovery-pipeline,depth-bandwidth}.pdf。'),
                para('图 8–9 来源：paper/figures/{eval-online-wct,eval-retry-length,eval-native-topk}.pdf。评估数值转述当前 evaluation.tex，本次未重新运行实验或独立重算全部原始记录。'),
                para('页面附件是原始英文 PDF，不是新生成的第二份论文版本。该页面的中文文字、图注与所有 Notion 文本块均可直接编辑。')
            ]})]
    }


def children(block_id):
    result=[]; cursor=None
    while True:
        args=['api',f'v1/blocks/{block_id}/children','page_size==100']
        if cursor:args += [f'start_cursor=={cursor}']
        r=cli(args);result.extend(r['results'])
        if not r.get('has_more'):break
        cursor=r['next_cursor']
    return result


def plain(block):
    return ''.join(x.get('plain_text',x.get('text',{}).get('content',''))
                   for x in block.get(block['type'],{}).get('rich_text',[]))


def populate():
    page=load('created-page.json'); pid=page['id']; up=load('uploads.json')
    save('page-styling.json',api(f'v1/pages/{pid}','PATCH',{
        'icon':{'type':'emoji','emoji':'📄'},
        'cover':{'type':'file_upload','file_upload':{'id':up['cover']['id']}}}))
    blocks=children(pid)
    for marker,new_blocks in replacements().items():
        receipt='insert-'+marker+'.json'
        found=[b for b in blocks if b['type']=='paragraph' and plain(b)==marker]
        if not found:
            assert (API/receipt).exists(),f'Missing marker: {marker}'
            continue
        assert len(found)==1
        anchor=found[0]['id']
        if not (API/receipt).exists():
            r=api(f'v1/blocks/{pid}/children','PATCH',{
                'children':new_blocks,
                'position':{'type':'after_block','after_block':{'id':anchor}}})
            save(receipt,r)
        # Only delete the exact temporary marker on the newly created page.
        save('removed-'+marker+'.json',api(f'v1/blocks/{anchor}','DELETE'))
        print('Placed:',marker,flush=True)
        time.sleep(0.4)


def verify():
    page=load('created-page.json'); pid=page['id']
    tree=[]
    def visit(parent):
        out=children(parent)
        for b in out:
            tree.append(b)
            if b.get('has_children'):visit(b['id'])
    visit(pid)
    save('verified-blocks.json',tree)
    counts=Counter(b['type'] for b in tree)
    assert counts['image']==11,counts
    assert counts['column_list']==2,counts
    assert counts['file']==1,counts
    assert counts['table_of_contents']==1,counts
    assert counts['equation']==5,counts
    assert counts['table']==2,counts
    text='\n'.join(plain(b) for b in tree)
    assert 'NOTION_' not in text
    for b in tree:
        if b['type'] in ['image','file']:
            media=b[b['type']]
            assert media.get('type')=='file' and media.get('file',{}).get('url'),b['id']
            assert media.get('caption'),b['id']
    actual=api(f'v1/pages/{pid}')
    assert actual['parent'].get('page_id')==PARENT
    assert actual.get('cover') and actual.get('icon')
    old=api(f'v1/pages/{OLD_PAGE}')
    before=load('original-notebook-before.json')
    assert old['last_edited_time']==before['last_edited_time'],'Original notebook changed'
    m=json.loads((OUT/'source-manifest.json').read_text())
    for p,h in m['source_files'].items():assert sha(ROOT/p)==h,p
    markdown=cli(['pages','get',pid,'--json'])
    save('final-markdown.json',markdown)
    result={'page_id':pid,'url':actual['url'],'parent_id':PARENT,
            'block_counts':dict(counts),'original_notebook_unchanged':True,
            'local_paper_sources_unchanged':True,
            'checks':['All 11 image blocks attached with captions','Two paired figure rows',
                      'Native TOC, tables and 5 equations','Cover and original PDF attached',
                      'No placeholder markers; original notebook preserved'],
            'limitations':['Notion browser layout not screenshot-verified; API tree verified.',
                'Original PDF attachment structurally inspected with pypdf; not revised.',
                'Figure lesson database contains one fingerprint mismatch; no memory writes.',
                'Evaluation is reported from current manuscript; no new experiment or full raw-data re-audit.']}
    (OUT/'review/publication-checks.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['upload','create','populate','verify'])
    globals()[parser.parse_args().action]()
