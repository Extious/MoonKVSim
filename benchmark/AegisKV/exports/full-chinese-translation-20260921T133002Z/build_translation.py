from pathlib import Path
from collections import Counter
import re,json,hashlib,unicodedata

ROOT=Path(__file__).resolve().parent
PAPER=ROOT.parent.parent/'paper'
units=json.loads((ROOT/'units.json').read_text())
translations=json.loads((ROOT/'translations.json').read_text())
aux=(ROOT/'source/main.aux').read_text()
labels=dict(re.findall(r'\\newlabel\{([^}]+)\}\{\{([^}]+)\}',aux))
bibnums={k:int(n) for k,n in re.findall(r'\\bibcite\{([^}]+)\}\{\{(\d+)\}',aux)}

def group(s,i):
    assert s[i]=='{',(s[i:i+30],i)
    n=1;j=i+1
    while n:
        if s[j]=='\\': j+=2;continue
        if s[j]=='{':n+=1
        elif s[j]=='}':n-=1
        j+=1
    return s[i+1:j-1],j

def replace_macro(s,name,arity,fn):
    pat=re.compile(r'\\'+re.escape(name)+r'(?![A-Za-z])\s*')
    pos=0;out=[]
    while (m:=pat.search(s,pos)):
        out.append(s[pos:m.start()]);j=m.end();a=[]
        for _ in range(arity):
            while j<len(s) and s[j].isspace():j+=1
            if j>=len(s) or s[j]!='{':raise ValueError((name,s[m.start():m.start()+100]))
            value,j=group(s,j);a.append(value)
        out.append(fn(*a));pos=j
    out.append(s[pos:]);return ''.join(out)

def anchor(key):return key.replace(':','-').replace('@','-')

def ref_link(key,text=None):
    n=labels[key]
    return f'[{text or n}](#{anchor(key)})'

def text_format(s):
    # Formatting outside mathematics only.
    formats={'textbf':lambda x:'**'+text_format(x)+'**',
             'textit':lambda x:'*'+text_format(x)+'*',
             'emph':lambda x:'*'+text_format(x)+'*',
             'texttt':lambda x:'`'+x+'`',
             'textsc':lambda x:'`'+x+'`'}
    for name,fn in formats.items():s=replace_macro(s,name,1,fn)
    for a,b in [('\\%','%'),('\\&','&'),('\\_','_'),('\\,',' '),('\\!',''),('~',' '),('\\quad','　'),('\\qquad','　　')]:s=s.replace(a,b)
    return re.sub(r'\s+',' ',s).strip()

def inline(s):
    s=re.sub(r'\\cite\{([^}]+)\}',lambda m:'、'.join(f'[[{n}]](#ref-{n})' for n in sorted(bibnums[k] for k in m[1].split(','))),s)
    s=re.sub(r'图\s*\\ref\{([^}]+)\}\(\\subref\{([^}]+)\}\)',lambda m:ref_link(m[2],f'图 {labels[m[1]]}({labels["sub@"+m[2]]})'),s)
    for prefix,display in [('图','图 '),('算法','算法 '),('附录','附录 ')]:
        s=re.sub(prefix+r'\s*\\ref\{([^}]+)\}',lambda m:ref_link(m[1],display+labels[m[1]]),s)
    s=re.sub(r'第\s*\\ref\{([^}]+)\}\s*节',lambda m:ref_link(m[1],f'第 {labels[m[1]]} 节'),s)
    s=re.sub(r'\\ref\{([^}]+)\}',lambda m:ref_link(m[1]),s)
    s=re.sub(r'\\subref\{([^}]+)\}',lambda m:ref_link(m[1],labels['sub@'+m[1]]),s)
    bits=re.split(r'(\$(?:[^$]|\\\$)*\$)',s)
    out=[]
    for bit in bits:
        if bit.startswith('$') and bit.endswith('$'):
            bit=replace_macro(bit,'textsc',1,lambda x:r'\operatorname{'+x+'}')
            out.append(bit)
        else:
            lead=' ' if bit[:1].isspace() else ''
            trail=' ' if bit[-1:].isspace() else ''
            out.append(lead+text_format(bit)+trail)
    # Text chunks around math need no spaces in Chinese; inline token names remain legible.
    return ''.join(out)

def bib_plain(s):
    s=re.sub(r'(?<!\\)%[^\n]*','',s)
    s=re.sub(r'\\urldef\\tempurl\s*','',s)
    s=replace_macro(s,'showURL',1,lambda x:'')
    # Keep each URL exactly as in the compiled bibliography.
    s=replace_macro(s,'url',1,lambda x:' [来源]('+x+') ')
    s=replace_macro(s,'href',2,lambda u,t:' ['+bib_plain(t)+']('+u+') ')
    s=replace_macro(s,'nolinkurl',1,lambda x:x)
    for name in ['bibfield','bibinfo']:s=replace_macro(s,name,2,lambda _,v:bib_plain(v))
    for name in ['showarticletitle','shownote','showISBNx','mbox','natexlab']:
        s=replace_macro(s,name,1,bib_plain)
    s=replace_macro(s,'emph',1,lambda x:'*'+bib_plain(x)+'*')
    s=re.sub(r'\\showeprint(?:\[[^\]]*\])?\{([^}]+)\}',r'arXiv:\1',s)
    s=s.replace('\\newblock',' ').replace('\\tempurl','')
    # Common TeX accent spelling in author names and titles.
    accent={"'":'\u0301','`':'\u0300','"':'\u0308','^':'\u0302','~':'\u0303','=':'\u0304'}
    s=re.sub(r'''\\(['`"^~=])\{?([A-Za-z])\}?''',lambda m:unicodedata.normalize('NFC',m[2]+accent[m[1]]),s)
    s=s.replace('\\&','&').replace('\\_','_').replace('\\%','%').replace('~',' ')
    s=s.replace('{','').replace('}','').replace('---','—').replace('--','–')
    s=re.sub(r'\s+',' ',s).strip()
    return s

def bibliography():
    bbl=(ROOT/'source/main.bbl').read_text()
    starts=list(re.finditer(r'\\bibitem\[[\s\S]*?\]%?\s*\{([^}]+)\}',bbl))
    entries=[]
    for i,m in enumerate(starts):
        raw=bbl[m.end():starts[i+1].start() if i+1<len(starts) else bbl.index('\\end{thebibliography}')]
        rendered=bib_plain(raw)
        assert not re.search(r'\\[A-Za-z]+',rendered),(m[1],rendered)
        entries.append((bibnums[m[1]],m[1],rendered))
    assert len(entries)==len(bibnums)==41
    entries.sort()
    out=['## 参考文献','文献编号与英文论文一致；作者、题名及出版信息保留原文，以便检索。']
    for n,k,s in entries:
        out.append(f'<a id="ref-{n}"></a>\n\n**[{n}]** {s}')
    return '\n\n'.join(out),entries

algo_titles={'U085':'剩余时间与 Slack','U137':'在线三层管理','U147':'按窗口调整 Peer 配额'}
algorithm_rows={}
def algorithm(u):
    key=u['labels'][0];rows=re.findall(r'^\s*(\d+)\s*&\s*(.*?)\\\\\s*$',u['source'],re.M)
    assert rows
    out=[f'<a id="{anchor(key)}"></a>',f'**算法 {labels[key]}：{algo_titles[u["id"]]}**','| 行 | 操作 |\n| ---: | :--- |']
    for number,code in rows:
        code=code.replace('completion/failure emits a new event','完成／失败触发一个新事件')
        indent=0
        while code.startswith('\\quad') or code.startswith('\\qquad'):
            token='\\qquad' if code.startswith('\\qquad') else '\\quad'
            indent+=2 if token=='\\qquad' else 1
            code=code[len(token):].lstrip()
        rendered='&emsp;'*indent+inline(code).replace('|',r'\vert ')
        out.append(f'| {number} | {rendered} |')
    algorithm_rows[u['id']]=len(rows)
    return '\n\n'.join(out[:2])+'\n\n'+'\n'.join(out[2:])

figure_records=[]
def figure(u):
    caps=[translations[c] for c in u['captions']];out=[]
    mainkey=u['labels'][-1];n=labels[mainkey]
    out.append(f'<a id="{anchor(mainkey)}"></a>')
    if len(u['images'])>1:
        out.append(f'**图 {n}**')
        for i,(asset,key) in enumerate(zip(u['images'],u['labels'][:-1])):
            png=PAPER/'figures/preview'/(Path(asset).stem+'.png');assert png.exists(),png
            out.append(f'<a id="{anchor(key)}"></a>\n\n![图 {n}({chr(97+i)})：{inline(caps[i])}]({png})\n\n**({chr(97+i)}) {inline(caps[i])}**')
    else:
        png=PAPER/'figures/preview'/(Path(u['images'][0]).stem+'.png');assert png.exists(),png
        out.append(f'![图 {n}]({png})')
    out.append(f'**图 {n}：** {inline(caps[-1])}')
    figure_records.append(dict(number=n,labels=u['labels'],images=u['images']))
    return '\n\n'.join(out)

# Ensure every printed prose/heading/caption unit was translated, preserving all citations and cross references.
required={u['id'] for u in units if u['kind'] in ['prose','heading','caption']}
assert required==set(translations),(required-set(translations),set(translations)-required)
for u in units:
    if u['id'] not in translations:continue
    for cmd in ['cite','ref','subref']:
        pat=r'\\'+cmd+r'\{([^}]+)\}'
        assert Counter(re.findall(pat,u['source']))==Counter(re.findall(pat,translations[u['id']])),(u['id'],cmd)

out=['# AegisKV：跨 HBM、DRAM 与共享存储的工作流感知 KV 检查点',
     '> 完整中文译稿，对应 [英文论文 main.pdf]('+str(PAPER/'main.pdf')+')。章节、图、公式、算法及参考文献编号与英文稿一致；图像沿用原图，正文和图注逐段翻译。']
eqnum=0;unit_offsets={};entries=[]
for u in units:
    typ=u['kind'];id=u['id'];piece=''
    if typ=='heading':
        h=translations[id];level=u['level'];num=u['number']
        if level:piece='#'*level+' '+('附录 '+num+'　' if num=='A' else num+'　' if num else '')+h
        else:piece='**'+h+'**'
    elif typ=='prose':piece=inline(translations[id])
    elif typ=='anchor':piece=f'<a id="{anchor(u["source"])}"></a>'
    elif typ=='caption':continue
    elif typ=='figure':piece=figure(u)
    elif typ=='algorithm':piece=algorithm(u)
    elif typ in ['math','equation']:
        body=u['source'];mathlabels=re.findall(r'\\label\{([^}]+)\}',body)
        body=re.sub(r'\\label\{[^}]+\}','',body)
        body=body.replace('\\begin{equation}','').replace('\\end{equation}','').replace('\\[','').replace('\\]','').strip()
        if id=='U103':
            body=body.replace('queries selecting block ', '选择块 ').replace('queries for which block ','块 ').replace(' was visible',' 因果可见时的 Query 数')
            body=body.replace(r'\text{选择块 }b',r'\text{选择块 }b\text{ 的 Query 数}')
        if typ=='equation':
            eqnum+=1
            for k in mathlabels:assert labels[k]==str(eqnum),(k,labels[k],eqnum)
            body+=r' \tag{'+str(eqnum)+'}'
        piece='\n'.join(f'<a id="{anchor(k)}"></a>' for k in mathlabels)+'\n\n$$\n'+body+'\n$$'
    elif typ=='bibliography':piece,entries=bibliography()
    else:raise ValueError(typ)
    if piece.strip():
        unit_offsets[id]=len(out);out.append(piece.strip())
md='\n\n'.join(out)+'\n'
# Check all fragment links and image files before publishing.
anchors=re.findall(r'<a id="([^"]+)"></a>',md)
assert len(anchors)==len(set(anchors)),[a for a,c in Counter(anchors).items() if c>1]
links=re.findall(r'\]\(#([^)]*)\)',md)
assert set(links)<=set(anchors),set(links)-set(anchors)
assert not re.search(r'\\(?:cite|ref|subref|label|begin|end)\{',md)
(ROOT/'review/paper_draft.translated.md').write_text(md)
(ROOT/'review/reference-map.json').write_text(json.dumps({'labels':labels,'bibliography':bibnums,'figures':figure_records},ensure_ascii=False,indent=2)+'\n')
validation={'translated_units':len(translations),'prose_paragraphs':sum(u['kind']=='prose' for u in units),'headings':sum(u['kind']=='heading' for u in units),'captions_including_subfigures':sum(u['kind']=='caption' for u in units),'figures':len(figure_records),'images':len(re.findall(r'!\[',md)),'algorithms':algorithm_rows,'numbered_equations':eqnum,'bibliography_entries':len(entries),'anchors':len(anchors),'internal_links':len(links),'all_citation_and_reference_occurrences_match_source':True,'all_links_resolve':True}
(ROOT/'review/VALIDATION.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(validation,ensure_ascii=False,indent=2))
print('Staged Markdown:',ROOT/'review/paper_draft.translated.md')
