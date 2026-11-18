from pathlib import Path
import re,json,hashlib,datetime
root=Path('/home/comp/zhanzhao/MoonKVSim')
base=root/'benchmark/AegisKV/experiments/evaluation-20260924'
paper=root/'benchmark/AegisKV/paper'
review=base/'reviews'; review.mkdir(exist_ok=True)

def group(s,start):
    assert s[start]=='{'
    depth=1;i=start+1
    while i<len(s) and depth:
        if s[i]=='\\': i+=2;continue
        if s[i]=='{':depth+=1
        elif s[i]=='}':depth-=1
        i+=1
    return s[start+1:i-1],i

def command_args(s,name,keep=False):
    p=re.compile(r'\\'+name+r'(?![A-Za-z])(?:\s*\[[^\]]*\])?\s*\{')
    out=[];pos=0;extracted=[]
    for m in p.finditer(s):
        if m.start()<pos:continue
        arg,end=group(s,m.end()-1)
        out.append(s[pos:m.start()]);out.append(arg if keep else ' ');extracted.append(arg);pos=end
    out.append(s[pos:]);return ''.join(out),extracted

def preprocess(s):
    return re.sub(r'(?<!\\)%[^\n]*','',s)

def prose(s):
    s=re.sub(r'\$\$.*?\$\$|(?<!\\)\$.*?(?<!\\)\$|\\\[.*?\\\]|\\\(.*?\\\)',' ',s,flags=re.S)
    for name in ('equation','align','gather','displaymath','algorithm','algorithmic','verbatim','tikzpicture'):
        s=re.sub(r'\\begin\{'+name+r'\*?\}.*?\\end\{'+name+r'\*?\}',' ',s,flags=re.S)
    for name in ('cite','citep','citet','ref','eqref','label','Description','includegraphics','input','bibliography','bibliographystyle','setlength','renewcommand'):
        s,_=command_args(s,name)
    s=re.sub(r'\\system\b',' AegisKV ',s)
    s=re.sub(r'\\[A-Za-z]+\*?(?:\[[^\]]*\])?',' ',s)
    return re.findall(r"[A-Za-z]+(?:['’-][A-Za-z]+)*|\d+(?:\.\d+)?",s)

def counts(s):
    s=preprocess(s);captions=[]
    for m in re.finditer(r'\\begin\{(?:figure|table)\*?\}.*?\\end\{(?:figure|table)\*?\}',s,flags=re.S):
        _,cs=command_args(m.group(0),'caption');captions+=cs
    s=re.sub(r'\\begin\{(?:figure|table)\*?\}.*?\\end\{(?:figure|table)\*?\}',' ',s,flags=re.S)
    return {'prose_approx_words':len(prose(s)),'caption_approx_words':sum(len(prose(c)) for c in captions)}

out={'method':'Approximate source-token count, not TeXcount: English/numeric tokens after stripping comments, citations/references, math, figure/table bodies, descriptions and LaTeX commands. Figure/table captions counted separately; headings included. Pseudocode and references excluded. Hyphenated alphabetic words count once; TeX line-break hyphenation may differ from rendered prose.', 'files':{},'evaluation_subsections':{}}
for name in ['background.tex','motivation.tex','system_design.tex','evaluation.tex']:
    s=(paper/name).read_text();out['files'][name]={**counts(s),'sha256':hashlib.sha256(s.encode()).hexdigest()}
s=(paper/'evaluation.tex').read_text()
marks=list(re.finditer(r'\\subsection\{([^}]+)\}',s))
for i,m in enumerate(marks):
    out['evaluation_subsections'][m.group(1)]=counts(s[m.start():marks[i+1].start() if i+1<len(marks) else len(s)])
out['total']={k:sum(v[k] for v in out['files'].values()) for k in ['prose_approx_words','caption_approx_words']}
(review/'MANUSCRIPT_APPROX_WORD_COUNTS.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
