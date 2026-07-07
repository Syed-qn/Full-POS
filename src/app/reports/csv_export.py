import csv
import io


def rows_to_csv(rows: list[dict]) -> str:
    """Render a list of flat dicts as CSV text (Excel opens this natively —
    no xlsx library dependency needed for a "download as spreadsheet" feature)."""
    if not rows:
        return ""
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()
