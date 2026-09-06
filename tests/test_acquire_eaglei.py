from datetime import UTC, datetime

from scripts.event_baseline.acquire_eaglei import _complete_csv_rows, parse_source_time


def test_complete_rows_discards_partial_boundary_records() -> None:
    payload = (
        b"partial\n"
        b"27053,Hennepin,Minnesota,5,2021-06-03 00:00:00\n"
        b"27123,Ramsey,Minnesota,7,2021-06-03 00:15:00\n"
        b"truncated"
    )
    rows = _complete_csv_rows(
        payload, ["fips_code", "county", "state", "customers_out", "run_start_time"]
    )
    assert [row["fips_code"] for row in rows] == ["27053", "27123"]
    assert rows[0]["run_start_time"] == "2021-06-03 00:00:00"


def test_source_time_is_naive_text_for_documented_utc_value() -> None:
    value = parse_source_time("2021-06-03 00:00:00")
    assert value == datetime(2021, 6, 3, tzinfo=UTC)


def test_complete_rows_keeps_native_total_customers_when_present() -> None:
    payload = b"partial\n27049,Goodhue,Minnesota,9,2024-05-21 18:00:00,1234\ntruncated"
    rows = _complete_csv_rows(
        payload,
        ["fips_code", "county", "state", "customers_out", "run_start_time", "total_customers"],
    )
    assert rows == [
        {
            "fips_code": "27049",
            "county": "Goodhue",
            "state": "Minnesota",
            "customers_out": "9",
            "run_start_time": "2024-05-21 18:00:00",
            "total_customers": "1234",
        }
    ]
