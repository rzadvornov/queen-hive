"""Report renderers."""

from reports.data import Report


def render_text(report: Report) -> str:
    rows = sorted(report.rows, key=lambda r: r.revenue, reverse=True)
    total_units = 0
    total_revenue = 0.0
    for row in rows:
        total_units += row.units
        total_revenue += row.revenue
    lines = [report.title, "=" * len(report.title)]
    for row in rows:
        lines.append(f"{row.region:<12}{row.units:>8}{row.revenue:>12.2f}")
    lines.append(f"{'TOTAL':<12}{total_units:>8}{total_revenue:>12.2f}")
    return "\n".join(lines)


def render_html(report: Report) -> str:
    rows = sorted(report.rows, key=lambda r: r.revenue, reverse=True)
    total_units = sum(r.units for r in rows)
    total_revenue = 0.0
    for row in rows:
        total_revenue = total_revenue + row.revenue
    cells = "".join(f"<tr><td>{r.region}</td><td>{r.units}</td><td>{r.revenue:.2f}</td></tr>" for r in rows)
    return (f"<h1>{report.title}</h1><table>{cells}"
            f"<tr><th>TOTAL</th><th>{total_units}</th><th>{total_revenue:.2f}</th></tr></table>")


def render(report: Report, fmt: str) -> str:
    if fmt == "text":
        return render_text(report)
    if fmt == "html":
        return render_html(report)
    raise ValueError(f"unknown format: {fmt}")
