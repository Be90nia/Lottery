# Official snapshot materialization

The repository currently contains the exact collection archive at `data/incoming/dlt_official_raw.zip`.

The GitHub-connected workflow can inspect and create UTF-8 text blobs, but it cannot safely expand a binary ZIP blob server-side into 61+ raw text files. Therefore materialization is deliberately performed from the exact archive in a local checkout.

## Windows command

From the repository root:

```powershell
$archive = ".\data\incoming\dlt_official_raw.zip"
$target = ".\data\raw\sporttery\2026-11-18"

if (Test-Path $target) { throw "Refusing to overwrite existing raw snapshot" }

Expand-Archive -LiteralPath $archive -DestinationPath ".\data\incoming\_expanded"

$src = ".\data\incoming\_expanded\dlt_official_raw"
if (-not (Test-Path $src)) { throw "Unexpected archive layout" }

New-Item -ItemType Directory -Force $target | Out-Null
Get-ChildItem $src -File | ForEach-Object {
    Copy-Item $_.FullName $target
}

Remove-Item ".\data\incoming\_expanded" -Recurse -Force
```

Then run the deterministic importers:

```powershell
py -3 scripts/fetch_history.py --snapshots-dir $target --require-manifests --output ".\data\processed\draws-20261118.jsonl"

py -3 scripts/ingest_prizes.py --raw-dir $target --output ".\data\processed\prizes-20261118.jsonl" --report ".\data\processed\prizes-20261118.report.json"
```

## Acceptance checks

Before committing, verify:

- exactly 30 page JSON files;
- exactly 30 page sidecars;
- exactly one collection manifest;
- 2,949 draw records;
- 2,949 unique draw IDs;
- zero missing/empty prize lists;
- every raw page SHA-256 equals its sidecar;
- normalized outputs are generated only from the materialized raw directory.

Do not delete or modify the incoming ZIP after materialization. It is the transport-level immutable reference.

## Why this is not automated by the GitHub workflow

The archive is already present as a binary Git blob. The connected GitHub API path used for this audit is text-oriented and cannot be used to safely decode/re-encode the ZIP without risking byte changes. The local PowerShell route preserves the exact archive and makes the expansion reproducible.
