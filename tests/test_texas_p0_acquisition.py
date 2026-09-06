"""Guard the Texas P0 acquisition helpers against catalog/receipt drift.

Neither test touches the network.  They assert the property that actually
breaks a rebuild: the acquisition probe and the receipt-driven fetcher must
still describe the same P0 raw-input contract the builder reads, and the
fetcher must never plan a download for an artifact with no tracked SHA-256.
"""

from __future__ import annotations

import hashlib
import json

import pytest

from pipelines.build import _p0_raw_inputs
from scripts.data import fetch_texas_p0_raw as fetcher
from scripts.data import texas_p0_acquisition_probe as probe

REPOSITORY_ROOT = fetcher.REPOSITORY_ROOT


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


# --- The verification path itself, offline -----------------------------------
#
# The module docstring's central promise is that a downloaded file is verified
# against the receipt's SHA-256 and byte count "and is discarded on mismatch, so
# a changed upstream artifact fails loudly instead of silently entering a
# build".  The tests below assert that promise at its three layers: ``_verify``
# distinguishes the two states, ``fetch_item`` leaves no corrupt payload behind,
# and ``main`` exits non-zero.  None touches the network.

PAYLOAD = b"tracked payload\n"
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()


def _tracked_item() -> fetcher.Item:
    return fetcher.Item(
        receipt="tracked",
        filename="payload.csv",
        destination=("tracked", "payload.csv"),
        url_rule="source_url",
    )


def _write_receipt(sources_dir, *, sha: str = PAYLOAD_SHA, size: int = len(PAYLOAD)):
    receipt = {
        "source_url": "https://example.invalid/payload.csv",
        "provider": {"name": "example"},
        "license_access": {"license": "test", "access": "public"},
        "retrieved_at": "2026-09-06T00:00:00+00:00",
        "files": {"payload.csv": {"sha256": sha, "bytes": size}},
    }
    (sources_dir / "tracked.json").write_text(json.dumps(receipt), encoding="utf-8")


def test_verify_separates_a_matching_file_from_a_corrupt_or_short_one(tmp_path):
    path = tmp_path / "payload.csv"
    path.write_bytes(PAYLOAD)
    entry = {"sha256": PAYLOAD_SHA, "bytes": len(PAYLOAD)}

    good = fetcher._verify(path, entry)
    assert good["verified"] is True
    assert good["observed_sha256"] == PAYLOAD_SHA
    assert good["observed_bytes"] == len(PAYLOAD)

    # One byte changed, same length: only the digest can catch it.
    path.write_bytes(b"Tracked payload\n")
    corrupt = fetcher._verify(path, entry)
    assert corrupt["verified"] is False
    assert corrupt["observed_sha256"] != PAYLOAD_SHA
    assert corrupt["expected_sha256"] == PAYLOAD_SHA

    # Right digest expectation, wrong recorded byte count.
    path.write_bytes(PAYLOAD)
    short = fetcher._verify(path, {"sha256": PAYLOAD_SHA, "bytes": len(PAYLOAD) + 1})
    assert short["verified"] is False
    assert short["observed_bytes"] == len(PAYLOAD)
    assert short["expected_bytes"] == len(PAYLOAD) + 1


def test_a_sha256_mismatch_is_discarded_and_never_enters_the_raw_tree(
    tmp_path, monkeypatch
):
    """The harm's absence is asserted directly: no file lands on disk."""
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setattr(fetcher, "SOURCES_DIR", sources)
    _write_receipt(sources)
    raw = tmp_path / "raw"

    def fake_download(url, destination, timeout):
        # A real download writes the payload, then returns what it hashed.
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"upstream changed under us\n")
        return hashlib.sha256(b"upstream changed under us\n").hexdigest()

    monkeypatch.setattr(fetcher, "download", fake_download)
    result = fetcher.fetch_item(
        _tracked_item(), raw, force=False, timeout=1.0, dry_run=False
    )

    assert result["status"] == "failed"
    assert result["status"] != "downloaded"
    assert not (raw / "tracked" / "payload.csv").exists(), (
        "a file whose SHA-256 did not match the receipt was written into the raw tree"
    )
    assert not list(raw.rglob("*.csv")), list(raw.rglob("*"))
    assert [attempt["error"] for attempt in result["attempts"]] == ["sha256 mismatch"]
    assert result["attempts"][0]["expected_sha256"] == PAYLOAD_SHA


def test_a_matching_download_is_kept_and_reported_verified(tmp_path, monkeypatch):
    """The control for the test above: the same path accepts a good payload."""
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setattr(fetcher, "SOURCES_DIR", sources)
    _write_receipt(sources)
    raw = tmp_path / "raw"

    def fake_download(url, destination, timeout):
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(PAYLOAD)
        return PAYLOAD_SHA

    monkeypatch.setattr(fetcher, "download", fake_download)
    result = fetcher.fetch_item(
        _tracked_item(), raw, force=False, timeout=1.0, dry_run=False
    )

    assert result["status"] == "downloaded"
    assert result["verified"] is True
    assert (raw / "tracked" / "payload.csv").read_bytes() == PAYLOAD


def test_main_exits_1_when_a_present_file_does_not_match_its_receipt(
    tmp_path, monkeypatch, capsys
):
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setattr(fetcher, "SOURCES_DIR", sources)
    monkeypatch.setattr(fetcher, "PLAN", (_tracked_item(),))
    _write_receipt(sources)
    raw = tmp_path / "raw"
    (raw / "tracked").mkdir(parents=True)
    (raw / "tracked" / "payload.csv").write_bytes(b"corrupted\n")

    assert fetcher.main(["--raw-dir", str(raw)]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["all_verified"] is False
    assert report["summary"]["present_but_unverified"] == ["payload.csv"]


def test_main_exits_0_when_every_file_matches_its_receipt(
    tmp_path, monkeypatch, capsys
):
    """Control: the exit code is a function of the outcome, not a constant."""
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setattr(fetcher, "SOURCES_DIR", sources)
    monkeypatch.setattr(fetcher, "PLAN", (_tracked_item(),))
    _write_receipt(sources)
    raw = tmp_path / "raw"
    (raw / "tracked").mkdir(parents=True)
    (raw / "tracked" / "payload.csv").write_bytes(PAYLOAD)

    assert fetcher.main(["--raw-dir", str(raw)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["all_verified"] is True


# --- Binding to the 2WKG-199 receipt inventory --------------------------------


def _inventory_shas() -> dict[str, set[str]]:
    inventory = json.loads(
        (fetcher.SOURCES_DIR / "texas-p0-inventory.json").read_text(encoding="utf-8")
    )
    shas: dict[str, set[str]] = {}
    for record in inventory["records"]:
        for artifact in record.get("artifacts", []):
            immutable_id = artifact.get("immutable_id")
            if isinstance(immutable_id, str) and immutable_id.startswith("sha256:"):
                shas.setdefault(artifact["logical_name"], set()).add(
                    immutable_id.split(":", 1)[1]
                )
    return shas


def _plan_shas() -> dict[str, str]:
    shas: dict[str, str] = {}
    for item in fetcher.PLAN:
        receipt = fetcher.load_receipt(item.receipt)
        for name in filter(None, (item.filename, item.extract_member)):
            entry = receipt.get("files", {}).get(name)
            if isinstance(entry, dict) and entry.get("sha256"):
                shas[name] = entry["sha256"]
    return shas


def test_plan_shas_match_the_texas_p0_inventory():
    """This rebuild reproduces 2WKG-199's P0 inventory, by construction.

    ``data/sources/texas-p0-inventory.json`` is the P0 provenance record #199
    established; this fetcher re-derives its expectations from the per-publisher
    receipts.  Without this test the two agree only by coincidence and an edit
    to either side drifts them with every gate green.
    """
    inventory, plan = _inventory_shas(), _plan_shas()
    shared = sorted(set(inventory) & set(plan))
    assert len(shared) >= 18, (
        f"only {len(shared)} artifacts overlap the #199 inventory; the binding "
        "between this rebuild and the P0 provenance record has been broken"
    )
    disagree = [
        (name, plan[name], sorted(inventory[name]))
        for name in shared
        if plan[name] not in inventory[name]
    ]
    assert disagree == [], disagree


# --- Portability of the emitted receipts -------------------------------------


def test_emitted_paths_are_posix_not_host_specific(tmp_path, monkeypatch, capsys):
    """A committed receipt must be diffable and readable on any host."""
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setattr(fetcher, "SOURCES_DIR", sources)
    monkeypatch.setattr(fetcher, "PLAN", (_tracked_item(),))
    _write_receipt(sources)

    assert fetcher.main(["--raw-dir", "run-artifacts/x", "--dry-run"]) == 0
    rendered = capsys.readouterr().out
    assert "\\" not in rendered, rendered
    report = json.loads(rendered)
    assert report["raw_dir"] == "run-artifacts/x"
    assert report["artifacts"][0]["destination"] == (
        "run-artifacts/x/tracked/payload.csv"
    )


def test_committed_receipts_carry_no_windows_paths():
    receipts = sorted(
        (REPOSITORY_ROOT / "docs" / "data" / "acceptance_receipts").glob(
            "2wkg-416-*.json"
        )
    )
    assert receipts, "the 2WKG-416 acceptance receipts are missing"
    offenders = {
        path.name: path.read_text(encoding="utf-8").count("\\\\")
        for path in receipts
        if "\\\\" in path.read_text(encoding="utf-8")
    }
    assert offenders == {}, offenders
