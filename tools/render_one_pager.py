"""Render ONE_PAGER.md -> ONE_PAGER.pdf (reproducible, no external CLI).

Uses fpdf2 with a Unicode monospace font (Courier New on macOS, DejaVu Sans Mono
on Linux) so the ASCII architecture diagram, the ≥/→ symbols, and the results
table all render faithfully.

    python tools/render_one_pager.py            # writes ONE_PAGER.pdf next to the .md
"""
from __future__ import annotations

import sys
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ONE_PAGER.md"
OUT = ROOT / "ONE_PAGER.pdf"

# A Unicode monospace TTF that includes box-drawing glyphs, per-platform.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New.ttf",          # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",         # Debian/Ubuntu
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",                  # Fedora
]
FONT_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
]


def _first_existing(paths: list[str]) -> str | None:
    return next((p for p in paths if Path(p).exists()), None)


def _strip_inline(text: str) -> str:
    return text.replace("**", "")


def main() -> int:
    regular = _first_existing(FONT_CANDIDATES)
    bold = _first_existing(FONT_BOLD_CANDIDATES)
    if not regular:
        print("No Unicode monospace font found; install DejaVu Sans Mono and retry.")
        return 1

    pdf = FPDF(format="A4", unit="mm")
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.add_font("mono", "", regular)
    pdf.add_font("mono", "B", bold or regular)

    epw = pdf.epw  # effective page width (mm)
    in_code = False

    def cell(h: float, text: str) -> None:
        # Always return the cursor to the left margin on the next line, else fpdf2
        # leaves x at the right edge and the following block overflows the page.
        pdf.multi_cell(epw, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    for raw in SRC.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")

        if line.strip().startswith("```"):
            in_code = not in_code
            pdf.ln(1)
            continue

        if in_code:
            # Preformatted: monospace, small enough that the 80-col diagram fits.
            pdf.set_font("mono", "", 6.2)
            cell(3.1, line if line else " ")
            continue

        if not line.strip():
            pdf.ln(2.2)
            continue

        if line.startswith("# "):
            pdf.set_font("mono", "B", 15)
            cell(7.5, _strip_inline(line[2:]))
            pdf.ln(0.5)
        elif line.startswith("## "):
            pdf.set_font("mono", "B", 11)
            pdf.ln(1)
            cell(5.5, _strip_inline(line[3:]))
        elif line.lstrip().startswith(("- ", "* ")):
            pdf.set_font("mono", "", 8.5)
            cell(4.2, "  • " + _strip_inline(line.lstrip()[2:]))
        elif line.startswith("|"):
            # Markdown table row: render monospace so columns line up.
            pdf.set_font("mono", "", 7.5)
            cell(3.8, line)
        else:
            pdf.set_font("mono", "", 8.5)
            cell(4.4, _strip_inline(line))

    pdf.output(str(OUT))
    print(f"Wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
