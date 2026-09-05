#!/usr/bin/env bash
# D01 (2WKG-38) — obtain one synthetic Texas case: ACTIVSg2000.
#
# Idempotent: skips the download if the archive is already present with the
# expected sha256, and never overwrites an existing extracted file.
#
# Provider : Texas A&M University, Electric Grid Test Case Repository
# Page     : https://electricgrids.engr.tamu.edu/electric-grid-test-cases/activsg2000/
# Licence  : "free for commercial or non-commercial use"; contains no CEII.
# Citation : Birchfield et al., "Grid Structural Characteristics as Validation
#            Criteria for Synthetic Networks", IEEE TPWRS, 2017.
#            doi:10.1109/TPWRS.2016.2616385
#
# NOTE ON VERSIONS: this fetches the CURRENT version, whose ACTIVSg2000.aux
# carries coordinates keyed to the same bus ids as case_ACTIVSg2000.m. The
# older "Texas2000_June2016" bundle is a DIFFERENT case (2,007 buses, 49,776 MW)
# sharing only 98 of 2,000 bus numbers — do not use it for coordinates.

set -euo pipefail

RAW="${RAW:-data/raw}"
DEST="$RAW/activsg2000_current"
ZIP="$DEST/ACTIVSg2000_current.zip"
URL='https://drive.usercontent.google.com/download?id=1tC-ofbw1EE46hoZeSfiBAWnSAhG0SmVu&export=download&confirm=t'
EXPECT_SHA="817a6dc579c43fd5a4214852aebc8e60105c843dbd466ff1d1deabdc65f24f21"

mkdir -p "$DEST"

if [ -f "$ZIP" ]; then
  echo "archive already present: $ZIP ($(stat -c %s "$ZIP") bytes) — skipping download"
else
  echo "downloading ACTIVSg2000 (current version, ~125 MB) …"
  curl -sSL --retry 3 --retry-delay 2 -o "$ZIP.part" "$URL"
  mv "$ZIP.part" "$ZIP"
fi

GOT_SHA="$(sha256sum "$ZIP" | cut -d' ' -f1)"
echo "sha256: $GOT_SHA"
if [ "$GOT_SHA" != "$EXPECT_SHA" ]; then
  echo "ERROR: sha256 mismatch — provider content changed. Expected $EXPECT_SHA" >&2
  exit 1
fi

# Extract only what the demo needs. Uses python3 zipfile rather than `unzip`,
# which is not installed on every machine; never clobbers an existing file.
python3 - "$ZIP" "$DEST" <<'PY'
import pathlib, shutil, sys, zipfile
zip_path, dest = sys.argv[1], pathlib.Path(sys.argv[2])
with zipfile.ZipFile(zip_path) as z:
    for name in ("ACTIVSg2000.aux", "case_ACTIVSg2000.m"):
        out = dest / name
        if out.exists():
            print(f"exists, not clobbering: {out}")
            continue
        with z.open(name) as src, out.open("wb") as fh:
            shutil.copyfileobj(src, fh)
        print(f"extracted {out} ({out.stat().st_size:,} bytes)")
PY

python3 scripts/data/record_source.py >/dev/null
echo "manifest written: data/sources/activsg2000.json"
