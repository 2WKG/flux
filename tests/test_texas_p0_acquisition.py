"""Guard the Texas P0 acquisition helpers against catalog/receipt drift.

Neither test touches the network.  They assert the property that actually
breaks a rebuild: the acquisition probe and the receipt-driven fetcher must
still describe the same P0 raw-input contract the builder reads, and the
fetcher must never plan a download for an artifact with no tracked SHA-256.
"""

from __future__ import annotations

import json

import pytest

from pipelines.build import _p0_raw_inputs
from scripts.data import fetch_texas_p0_raw as fetcher
from scripts.data import texas_p0_acquisition_probe as probe


def _labels() -> set[str]:
    return {label for label, _ in _p0_raw_inputs()}


def test_probe_covers_every_p0_input_the_builder_requires():
    """A new P0 input must be classified, not silently dropped from the probe."""
    assert _labels() == set(probe.P0_INPUT_SOURCES)


def test_probe_names_only_real_catalog_datasets():
    catalog = probe.load_catalog()
    known = {entry["id"] for entry in catalog["datasets"]}
    named = {value for value in probe.P0_INPUT_SOURCES.values() if value is not None}
    assert named <= known


def test_probe_reports_missing_inputs_without_network(tmp_path):
    report = probe.build_report(raw_dir=tmp_path, network=False, timeout=1.0)
    assert report["summary"]["present_locally"] == 0
    assert report["summary"]["reproducible_end_to_end"] is False
    # Every input is described; none is quietly omitted.
    assert len(report["p0_inputs"]) == len(_labels())


def test_fetch_plan_covers_every_p0_input_the_builder_requires(tmp_path):
    """Each acceptable builder path must be a destination the fetcher writes."""
    planned = {"/".join(item.destination) for item in fetcher.PLAN}
    for label, alternatives in _p0_raw_inputs():
        accepted = {"/".join(parts) for parts in alternatives}
        assert accepted & planned, f"no fetch plan writes an accepted path for {label}"


@pytest.mark.parametrize(
    "item", fetcher.PLAN, ids=lambda item: "/".join(item.destination)
)
def test_every_planned_download_resolves_to_a_receipt_pinned_url(item):
    receipt = fetcher.load_receipt(item.receipt)
    urls, entry = fetcher.resolve(item, receipt)
    assert urls and all(url.startswith("https://") for url in urls)
    assert len(entry["sha256"]) == 64


def test_resolve_refuses_a_file_with_no_tracked_checksum(tmp_path, monkeypatch):
    receipt = {"source_url": "https://example.invalid/x.csv", "files": {"x.csv": {}}}
    item = fetcher.Item(
        receipt="unused",
        filename="x.csv",
        destination=("x.csv",),
        url_rule="source_url",
    )
    with pytest.raises(fetcher.FetchError, match="no SHA-256 recorded"):
        fetcher.resolve(item, receipt)


def test_unreadable_receipt_is_a_named_error(tmp_path, monkeypatch):
    monkeypatch.setattr(fetcher, "SOURCES_DIR", tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(fetcher.FetchError, match="unreadable source receipt"):
        fetcher.load_receipt("broken")


def test_receipt_plan_uses_only_tracked_receipts():
    for item in fetcher.PLAN:
        path = fetcher.SOURCES_DIR / f"{item.receipt}.json"
        assert path.is_file(), f"missing tracked receipt for {item.receipt}"
        json.loads(path.read_text(encoding="utf-8"))
