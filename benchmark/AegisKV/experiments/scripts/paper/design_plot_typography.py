"""Match the design plots to the manuscript's Libertine typography."""
from pathlib import Path
import hashlib
import subprocess

import matplotlib.pyplot as plt
from matplotlib import font_manager

# Slight headroom for the 3.34-inch plot's uniform scaling to the text column.
FONT_PT = 10.05


def configure():
    files = {}
    for weight, filename in [("regular", "LinLibertine_R.otf"),
                             ("bold", "LinLibertine_RB.otf")]:
        path = Path(subprocess.check_output(["kpsewhich", filename], text=True).strip())
        if not path.is_file():
            raise FileNotFoundError(f"Install the LaTeX libertine fonts: {filename}")
        font_manager.fontManager.addfont(str(path))
        files[weight] = path
    family = font_manager.FontProperties(fname=str(files["regular"])).get_name()
    plt.rcParams.update({
        "font.family": family, "font.size": FONT_PT,
        "axes.labelsize": FONT_PT, "axes.titlesize": FONT_PT,
        "axes.titleweight": "normal", "xtick.labelsize": FONT_PT,
        "ytick.labelsize": FONT_PT, "legend.fontsize": FONT_PT,
    })
    return {
        "family": family, "font_pt": FONT_PT,
        "regular_path": str(files["regular"]),
        "font_sha256": {w: hashlib.sha256(p.read_bytes()).hexdigest()
                        for w, p in files.items()},
        "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
