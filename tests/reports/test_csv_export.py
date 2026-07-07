from app.reports.csv_export import rows_to_csv


def test_rows_to_csv_includes_header_and_data():
    rows = [
        {"dish_name": "Kebab", "revenue_aed": "40.00"},
        {"dish_name": "Water", "revenue_aed": "2.00"},
    ]
    csv_text = rows_to_csv(rows)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "dish_name,revenue_aed"
    assert lines[1] == "Kebab,40.00"
    assert lines[2] == "Water,2.00"


def test_rows_to_csv_empty_list_returns_empty_string():
    assert rows_to_csv([]) == ""
