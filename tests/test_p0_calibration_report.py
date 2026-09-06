from __future__ import annotations

import pytest

from scripts.generate_p0_calibration_report import (
    DEFAULT_JSON_OUT,
    DEFAULT_LEDGER,
    DEFAULT_MARKDOWN_OUT,
    ROOT,
    build_report,
    load_ledger,
    render_markdown,
    validate_ledger,
    write_report,
)


def test_checked_in_calibration_artifacts_regenerate_byte_for_byte(tmp_path):
    json_out = tmp_path / "report.json"
    markdown_out = tmp_path / "report.md"
    report = write_report(DEFAULT_LEDGER, json_out, markdown_out)

    assert json_out.read_bytes() == DEFAULT_JSON_OUT.read_bytes()
    assert markdown_out.read_bytes() == DEFAULT_MARKDOWN_OUT.read_bytes()
    assert report["evidenceStatus"] == {
        "observed": 0,
        "proxy": 0,
        "modeled": 0,
        "unavailable": 2,
    }


def test_no_evidence_cannot_be_relabelled_as_calibrated():
    ledger = load_ledger(DEFAULT_LEDGER)
    ledger["scenarios"][0]["calibration"]["status"] = "calibrated"

    with pytest.raises(ValueError, match="calibration cannot be claimed"):
        build_report(ledger, ledger_path=DEFAULT_LEDGER, repo_root=ROOT)


def test_no_evidence_cannot_emit_a_proxy_or_modeled_value():
    ledger = load_ledger(DEFAULT_LEDGER)
    result = ledger["scenarios"][1]["result"]
    result["valueClass"] = "modeled"
    result["value"] = 1.0
    result["unit"] = "MW"

    with pytest.raises(ValueError, match="no-evidence calibration result"):
        build_report(ledger, ledger_path=DEFAULT_LEDGER, repo_root=ROOT)


def test_report_explicitly_discloses_all_mapping_limits():
    report = build_report(
        load_ledger(DEFAULT_LEDGER), ledger_path=DEFAULT_LEDGER, repo_root=ROOT
    )
    rendered = render_markdown(report)

    assert (
        "No ERCOT topology, SCADA, nodal telemetry, ratings, or restricted data"
        in rendered
    )
    assert rendered.count("Synthetic-topology mapping") == 2
    assert "like-for-like" in rendered


def test_receipt_checksum_is_line_ending_independent_but_content_sensitive(tmp_path):
    ledger = load_ledger(DEFAULT_LEDGER)
    lf = (
        (ROOT / ledger["topologyContext"]["receipt"])
        .read_bytes()
        .replace(b"\r\n", b"\n")
    )
    receipt = tmp_path / ledger["topologyContext"]["receipt"]
    receipt.parent.mkdir(parents=True, exist_ok=True)

    receipt.write_bytes(lf.replace(b"\n", b"\r\n"))
    validate_ledger(ledger, repo_root=tmp_path)  # a CRLF checkout must still match

    receipt.write_bytes(lf.replace(b"\n", b"\r\n").replace(b"{", b"[", 1))
    with pytest.raises(ValueError, match="checksum changed"):
        validate_ledger(ledger, repo_root=tmp_path)

    receipt.write_bytes(
        lf.replace(b"\n", b"\r")
    )  # bare CR is content, not a line ending
    with pytest.raises(ValueError, match="checksum changed"):
        validate_ledger(ledger, repo_root=tmp_path)
