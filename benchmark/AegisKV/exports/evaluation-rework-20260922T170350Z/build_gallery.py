"""Combine the existing vector figures at native size; does not change plot data."""
from pathlib import Path
import fitz

OUT = Path(__file__).resolve().parent
ITEMS = [
    ('13', 'eval-placement-pairs', 'Historical analytical model. 36 paired configurations; 17 improve, 19 tie.'),
    ('14', 'eval-recovery-paths', 'Physical path calibration. One input stream; HBM/DRAM n=3, other paths n=1.'),
    ('15', 'eval-rental-diagnostic', 'Historical rental model. The original and repaired variants both cost more than direct.'),
    ('16', 'eval-tracker-errors', 'Observed trace prediction. All 1,443 Agents retained; whole-Agent target, not segment Slack.'),
    ('17', 'eval-sparse-demand', 'Native sparse demand. Three documents/model; identical within-model byte budget.'),
    ('18', 'eval-trace-tails', 'Historical trace-driven model. Lower mean coexists with worse p95 and p99.'),
    ('S1', 'eval-sparse-horizon', 'Supplement. Same budget; prediction advantage shrinks as the future horizon grows.'),
]
doc = fitz.open()
for i, (number, stem, caption) in enumerate(ITEMS):
    if i % 4 == 0:
        page = doc.new_page(width=612, height=792)
        page.insert_text((46, 35), 'AegisKV Evaluation - existing evidence', fontsize=15)
        page.insert_text((46, 52), 'Six manuscript figures and one supplement; no new end-to-end system runs.', fontsize=10)
    x, y = 46 + (i % 2) * 280, 78 + ((i % 4) // 2) * 345
    page.insert_text((x, y), f'Figure {number}', fontsize=11)
    with fitz.open(OUT / 'figures' / f'{stem}.pdf') as source:
        rect = source[0].rect
        page.show_pdf_page(fitz.Rect(x, y + 9, x + rect.width, y + 9 + rect.height), source, 0)
    assert page.insert_textbox(fitz.Rect(x, y + 224, x + 242, y + 285), caption, fontsize=10, lineheight=1.2) >= 0
    page.insert_text((x, y + 302), 'See source manifest for scope and statistics.', fontsize=10)
doc.save(OUT / 'evaluation-figures.pdf', deflate=True)
for i, page in enumerate(doc):
    page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5)).save(OUT / 'paper-review' / f'gallery-{i+1}.png')
