"""
Excel export — Jobs sheet (Power BI-ready table) + Dashboard sheet (KPI
cells + charts), ported from the old single-user tool's excel_writer.py.

Deliberately generates the workbook FRESH from a full list of ScoredJob
every time (never opens an existing .xlsx and mutates it in place). This
is not just a style choice: the old tool hit a real bug where
ws.delete_rows() in a loop silently corrupted the sheet (stale blank rows,
stale Excel Table ref) — generating fresh from the source-of-truth data on
every export sidesteps that whole class of bug by construction, since
there is never an in-place edit to get wrong. In M2+, the "source of truth"
becomes a DB query instead of a JSONL file; this function's shape doesn't
change.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from packages.core.models import ScoredJob

STATUS_CHOICES = ["Saved", "Applied", "Interview", "Offer", "Rejected"]

COLUMNS = [
    "Date_Seen", "Job_ID", "Title", "Company", "Location", "Salary",
    "Status", "Apply_URL", "Description_Preview", "Score",
    "Requires_Fluent_English", "Search_Query", "Reason", "Link_Status",
]
COL_WIDTHS = {
    "Date_Seen": 14, "Job_ID": 18, "Title": 38, "Company": 26, "Location": 20,
    "Salary": 18, "Status": 14, "Apply_URL": 38, "Description_Preview": 50,
    "Score": 9, "Requires_Fluent_English": 12, "Search_Query": 18,
    "Reason": 36, "Link_Status": 12,
}

C_HEADER_BG, C_HEADER_FG = "1F3864", "FFFFFF"
C_ALT_ROW, C_ACCENT = "EAF0FB", "2E75B6"
C_GREEN, C_YELLOW = "70AD47", "FFD966"


def _thin_border() -> Border:
    side = Side(style="thin", color="BFBFBF")
    return Border(left=side, right=side, top=side, bottom=side)


def _header_style(cell) -> None:
    cell.fill = PatternFill("solid", fgColor=C_HEADER_BG)
    cell.font = Font(bold=True, color=C_HEADER_FG, size=11)
    cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_jobs_sheet(wb: Workbook, scored_jobs: list[ScoredJob]) -> None:
    ws = wb.create_sheet("Jobs", 0)
    for i, col in enumerate(COLUMNS, start=1):
        cell = ws.cell(row=1, column=i, value=col)
        _header_style(cell)
        ws.column_dimensions[get_column_letter(i)].width = COL_WIDTHS.get(col, 20)
    ws.row_dimensions[1].height = 28
    ws.freeze_panes = "A2"

    for i, sj in enumerate(scored_jobs):
        row_num = i + 2
        job, result = sj.job, sj.result
        desc = job.description
        preview = (desc[:300] + "...") if len(desc) > 300 else desc
        is_alt = row_num % 2 == 0
        fill = PatternFill("solid", fgColor=C_ALT_ROW) if is_alt else None

        values = [
            sj.date_seen.isoformat(), job.job_id, job.title, job.company,
            job.location, job.salary or "Not specified", sj.status, job.url,
            preview, result.score, result.requires_fluent_english,
            job.search_query, result.reason, result.link_status,
        ]
        for col_idx, value in enumerate(values, start=1):
            cell = ws.cell(row=row_num, column=col_idx, value=value)
            cell.border = _thin_border()
            cell.alignment = Alignment(vertical="center", wrap_text=(col_idx in (3, 9, 13)))
            if fill:
                cell.fill = fill
            if col_idx == 8 and value and str(value).startswith("http"):
                cell.hyperlink = value
                cell.font = Font(color="0563C1", underline="single")

    if ws.max_row >= 2:
        last_col = get_column_letter(len(COLUMNS))
        table = Table(displayName="JobsTable", ref=f"A1:{last_col}{ws.max_row}")
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium9", showFirstColumn=False, showLastColumn=False,
            showRowStripes=True, showColumnStripes=False,
        )
        ws.add_table(table)

        dv = DataValidation(type="list", formula1=f'"{",".join(STATUS_CHOICES)}"', showDropDown=False)
        ws.add_data_validation(dv)
        dv.add(f"G2:G{ws.max_row}")


def _build_dashboard(wb: Workbook, scored_jobs: list[ScoredJob]) -> None:
    ws = wb.create_sheet("Dashboard")
    ws.merge_cells("A1:H1")
    ws["A1"].value = "JobFighter — Dashboard"
    ws["A1"].font = Font(bold=True, size=16, color=C_HEADER_FG)
    ws["A1"].fill = PatternFill("solid", fgColor=C_HEADER_BG)
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 34

    ws.merge_cells("A2:H2")
    ws["A2"].value = f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    ws["A2"].font = Font(italic=True, size=10, color="666666")
    ws["A2"].alignment = Alignment(horizontal="center")

    if not scored_jobs:
        ws["A4"].value = "No jobs yet. Run the pipeline to populate."
        return

    total = len(scored_jobs)
    score_1 = sum(1 for sj in scored_jobs if sj.result.score == 1.0)
    score_half = sum(1 for sj in scored_jobs if sj.result.score == 0.5)

    kpis = [("Total Jobs", total, C_ACCENT), ("Score 1.0 (Fluent required)", score_1, C_GREEN),
            ("Score 0.5 (English desc.)", score_half, C_YELLOW)]
    for (label, value, color), col in zip(kpis, [1, 4, 7]):
        ws.merge_cells(start_row=4, start_column=col, end_row=4, end_column=col + 1)
        ws.merge_cells(start_row=5, start_column=col, end_row=5, end_column=col + 1)
        lbl = ws.cell(row=4, column=col, value=label)
        lbl.font = Font(bold=True, size=10, color="FFFFFF")
        lbl.fill = PatternFill("solid", fgColor=color)
        lbl.alignment = Alignment(horizontal="center")
        val = ws.cell(row=5, column=col, value=value)
        val.font = Font(bold=True, size=22, color=color)
        val.alignment = Alignment(horizontal="center")

    by_company: dict[str, int] = {}
    for sj in scored_jobs:
        by_company[sj.job.company] = by_company.get(sj.job.company, 0) + 1
    top = sorted(by_company.items(), key=lambda x: -x[1])[:10]

    ws.cell(row=8, column=1, value="Top Companies").font = Font(bold=True, color=C_HEADER_FG)
    ws.cell(row=8, column=1).fill = PatternFill("solid", fgColor=C_ACCENT)
    ws.cell(row=8, column=2, value="Jobs").font = Font(bold=True, color=C_HEADER_FG)
    ws.cell(row=8, column=2).fill = PatternFill("solid", fgColor=C_ACCENT)
    for i, (comp, cnt) in enumerate(top):
        ws.cell(row=9 + i, column=1, value=comp)
        ws.cell(row=9 + i, column=2, value=cnt)

    if top:
        chart = BarChart()
        chart.type = "bar"
        chart.title = "Top Hiring Companies"
        chart.style = 10
        data_ref = Reference(ws, min_col=2, min_row=8, max_row=8 + len(top) - 1)
        cats_ref = Reference(ws, min_col=1, min_row=9, max_row=8 + len(top))
        chart.add_data(data_ref, titles_from_data=True)
        chart.set_categories(cats_ref)
        chart.series[0].graphicalProperties.solidFill = C_ACCENT
        ws.add_chart(chart, "D8")

    if score_1 or score_half:
        pie = PieChart()
        pie.title = "Score Breakdown"
        pie.style = 10
        ws["A20"] = "Score"
        ws["B20"] = "Count"
        ws["A21"] = "1.0 (Fluent required)"
        ws["B21"] = score_1
        ws["A22"] = "0.5 (English description)"
        ws["B22"] = score_half
        data_ref = Reference(ws, min_col=2, min_row=20, max_row=22)
        cats_ref = Reference(ws, min_col=1, min_row=21, max_row=22)
        pie.add_data(data_ref, titles_from_data=True)
        pie.set_categories(cats_ref)
        ws.add_chart(pie, "D20")

    for col, width in [(1, 26), (2, 10)]:
        ws.column_dimensions[get_column_letter(col)].width = width


def write_excel(scored_jobs: list[ScoredJob], output_path: str | Path) -> Path:
    """Generate the full workbook fresh from scored_jobs and save it."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    wb = Workbook()
    wb.remove(wb.active)
    _write_jobs_sheet(wb, scored_jobs)
    _build_dashboard(wb, scored_jobs)
    wb.save(output_path)
    return output_path
