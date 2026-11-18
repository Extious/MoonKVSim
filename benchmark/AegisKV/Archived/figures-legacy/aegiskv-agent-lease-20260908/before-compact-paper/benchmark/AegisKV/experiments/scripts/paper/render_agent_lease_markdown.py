"""Render the paper catalogue for a browser check of image loading and paired rows."""
import hashlib
import json
import re
from pathlib import Path
from mdit_py_plugins.dollarmath import dollarmath_plugin

from markdown_it import MarkdownIt

ROOT=Path(__file__).resolve().parents[5]
DIRECTORY=ROOT/"benchmark/AegisKV/experiments"
OUT=ROOT/"output/pdf/aegiskv-agent-lease-20260908"
source=DIRECTORY/"Paper_Draft.md"
body=MarkdownIt("commonmark",{"html":True}).enable("table").use(dollarmath_plugin).render(source.read_text())
body=re.sub(r"<table>[\s\S]*?</table>",lambda m:m[0].replace("<table>",'<table class="figpair">' if "<img" in m[0] else '<table class="metrics">',1),body)
style="""
body{margin:0;background:#edf0f3;color:#18212b;font:16px/1.65 'Noto Sans CJK SC',sans-serif}
main{box-sizing:border-box;width:1056px;max-width:100%;margin:0 auto;background:white;padding:24px}
h1{font-size:28px;line-height:1.3}h2{font-size:24px;margin-top:44px;border-bottom:1px solid #d6dbe2;padding-bottom:6px}
h3{font-size:19px;margin-top:30px}p{margin:14px 0}a{color:#0069a7;text-decoration:none}
img{display:block;max-width:100%;height:auto}figure.paper-figure{margin:24px 0}figure.paper-figure p:last-child{font-size:14px;line-height:1.55}figure.paper-figure img{margin:0 auto}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.55;margin:18px 0}
th,td{border:1px solid #dce1e6;padding:9px;vertical-align:top;text-align:left;overflow-wrap:anywhere}
th{background:#f5f7f9}.figpair{table-layout:fixed}.figpair th,.figpair td{width:50%;padding:8px}
.figpair td img{width:480px;max-width:100%;margin:auto}.figpair td{font-size:14px}
code{font-family:monospace;font-size:.91em;overflow-wrap:anywhere}pre{white-space:pre-wrap;background:#f5f7f9;padding:12px}
.math.block{margin:22px 0;text-align:center}.katex{font-size:1.08em}.katex-display{overflow:auto hidden}
"""
katex=ROOT/"tmp/figure-browser/node_modules/katex/dist"
assert (katex/"katex.min.js").exists(),"Install katex@0.16.22 under tmp/figure-browser for the optional browser preview"
math_render="""<script>
document.querySelectorAll('.math').forEach(el=>katex.render(el.textContent,el,{displayMode:el.classList.contains('block'),throwOnError:true,strict:'error'}));
document.documentElement.dataset.mathReady='true';
</script>"""
page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'+f'<base href="{DIRECTORY.as_uri()}/"><title>AegisKV paper draft</title><link rel="stylesheet" href="{(katex/"katex.min.css").as_uri()}"><style>{style}</style><main>{body}</main><script src="{(katex/"katex.min.js").as_uri()}"></script>'+math_render+'</html>'
target=OUT/"paper-story.html";target.write_text(page)
print(json.dumps(dict(source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),html_sha256=hashlib.sha256(target.read_bytes()).hexdigest())))
