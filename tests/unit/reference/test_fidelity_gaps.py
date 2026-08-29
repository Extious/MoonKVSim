from pathlib import Path


def test_fidelity_gap_ids_are_unique_and_contiguous() -> None:
    root = Path(__file__).resolve().parents[3]
    rows = (root / "reference" / "fidelity-gaps.md").read_text(encoding="utf-8").splitlines()
    gap_ids = [
        fields[1].strip()
        for row in rows
        if row.startswith("| GAP-")
        for fields in [row.split("|")]
    ]

    assert len(gap_ids) == len(set(gap_ids))
    assert gap_ids == [f"GAP-{index:03d}" for index in range(1, len(gap_ids) + 1)]
