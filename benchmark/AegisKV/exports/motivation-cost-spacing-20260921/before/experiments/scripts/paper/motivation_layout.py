"""Physical alignment shared by the three current Figure 1 panels."""

HEIGHT_IN = 1.65
TOP_IN = .43
BOTTOM_IN = .38
WIDTHS_IN = {"workflow": 2.65, "workflow-gaps": 2.00, "recovery-cost": 2.21}
FONT_PT = 10.25


def axes_rect(width, left, right):
    """Matplotlib axes rectangle with fixed physical top and bottom edges."""
    return [left / width, BOTTOM_IN / HEIGHT_IN,
            (width - left - right) / width,
            (HEIGHT_IN - TOP_IN - BOTTOM_IN) / HEIGHT_IN]
