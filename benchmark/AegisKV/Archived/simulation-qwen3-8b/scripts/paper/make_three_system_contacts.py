"""PDF-rendered review sheets; these thumbnails are not publication figures."""

import argparse
import json
import textwrap
from pathlib import Path

import pymupdf
from matplotlib.font_manager import findfont
from PIL import Image, ImageDraw, ImageFont
from three_system_data import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--figures", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reviewed", type=Path)
    args = parser.parse_args()
    reviewed = {} if args.reviewed is None or not args.reviewed.exists() else json.loads(
        args.reviewed.read_text()).get("reviewed_png_sha256", {})
    names = sorted({r["name"] for p in args.figures.glob("*-figure-manifest.json")
                    for r in json.loads(p.read_text())})
    names = [name for name in names if reviewed.get(name) != sha(args.figures / (name + ".png"))]
    args.output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.truetype(findfont("DejaVu Sans"), 12)
    pages = []
    for start in range(0, len(names), 9):
        sheet = Image.new("RGB", (1560, 945), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        records = []
        for i, name in enumerate(names[start:start + 9]):
            path = args.figures / (name + ".pdf")
            with pymupdf.open(path) as doc:
                page = doc[0]
                scale = min(500 / page.rect.width, 260 / page.rect.height)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                raster = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            x, y = i % 3 * 520, i // 3 * 315
            draw.text((x + 8, y + 3), textwrap.fill(name, width=65), fill="black", font=font)
            sheet.paste(raster, (x + (520 - raster.width) // 2, y + 42))
            records.append({"name": name, "pdf_sha256": sha(path),
                            "png_sha256": sha(path.with_suffix(".png"))})
        file = args.output / f"contact-{start // 9 + 1:02d}.png"
        sheet.save(file)
        pages.append({"path": str(file.resolve()), "figures": records})
    (args.output / "CONTACTS.json").write_text(json.dumps(pages, indent=2) + "\n")
    print(json.dumps({"pages": len(pages), "figures": len(names), "directory": str(args.output)}))


if __name__ == "__main__":
    main()
