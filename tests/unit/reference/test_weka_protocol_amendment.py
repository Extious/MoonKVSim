from pathlib import Path

AMENDMENT = (
    Path(__file__).resolve().parents[3] / "reference/weka-capture-interval-protocol-amendment.md"
)


def test_weka_capture_interval_amendment_is_fail_closed() -> None:
    text = AMENDMENT.read_text(encoding="utf-8")
    prose = text.replace("\n", " ")

    assert "TRACE-PROTOCOL-AMENDMENT-001" in text
    assert "23f152f6f0f9399a85901b89a6458def0ef16729" in text
    assert "29b6a19e751ff5230771519aab755f80a0f43a4ba9cf96b72d3a6a437ec99276" in text
    assert "0a1c37deea32f2c393ba7d8d2d9a7c5629854b874b01ace8953140ad889f6d54" in text
    assert "collection_interval.value=null" in text
    assert "formal_use_allowed=false" in text
    assert "paper_result_allowed=false" in text
    assert "MUST NOT be used" in text
    assert "does not retroactively upgrade" in prose
