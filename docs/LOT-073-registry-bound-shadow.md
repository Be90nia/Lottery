# LOT-073 registry-bound prospective shadow pipeline

This slice connects the LOT-063 immutable ledger/schedule runner to the verified
LOT-060 Champion registry. It does not enable automatic promotion, cron, or
user-facing serving.

## Schedule inputs

The builder accepts two canonical UTF-8 JSON objects. Both files must be
canonicalized with the repository JCS implementation and have content IDs
computed over the object with its ID field omitted.

Target manifest:

- `schema`: `lottery.prospective-target-manifest/v1`
- `authority`: `official_verified`
- `manifest_id`: `sha256:<64 lowercase hex>`
- `targets`: explicit, unique target draw IDs with
  `expected_at_utc`, `target_cutoff_utc`, `target_draw_at_utc`, and
  `target_cutoff_timezone_source`

Canonical inventory:

- `schema`: `lottery.canonical-draw-inventory/v1`
- `authority`: `official_verified`
- `inventory_id`: `sha256:<64 lowercase hex>`
- `draw_dates`: exact five-digit draw ID to ISO date crosswalk

The content ID proves integrity only. The caller must supply a protected
`--trust-adapter` Python module exporting both
`verify_target_manifest(value)` and `verify_inventory(value)`. Each callback
must return the literal boolean `True` only after verifying source authority,
signature/receipt, completeness, and freshness. No permissive default exists.

## Registry binding and preflight

The builder takes exactly one `ChampionLifecycle.snapshot()`, which verifies
the registry journal, all referenced immutable artifacts and lifecycle receipts.
It requires a complete front/back Champion pair for every population. If a
registered challenger is present, both zones must have a retrospectively
eligible challenger; it is scheduled with lifecycle role `shadow`, never
`champion`. Front/back candidates cannot be mixed across roles.

Each record binds both artifact hashes, the full registry snapshot digest and
generation, model specification, model family, training snapshot/range/count,
canonical training last-draw date, target/cutoff and policies. The training
date must resolve through the separately authenticated canonical inventory.
A second registry snapshot is read before returning the schedule, and the
registry is rechecked immediately before register/issue/finalize operations.

## Commands

Build a content-addressed schedule (run only in a protected host that has the
verified source adapter and trusted lifecycle storage):

```sh
PYTHONPATH=src python scripts/build_prospective_schedule.py \
  --mode build \
  --lifecycle-root /secure/lottery/lifecycle \
  --target-manifest /secure/evidence/targets.json \
  --inventory /secure/evidence/draw-inventory.json \
  --trust-adapter lottery_trust_adapter \
  --code-commit "$GITHUB_SHA" \
  --schedule /secure/objects/schedule.json
```

Register all expectations before cutoff:

```sh
PYTHONPATH=src python scripts/build_prospective_schedule.py \
  --mode register \
  --lifecycle-root /secure/lottery/lifecycle \
  --schedule /secure/objects/schedule.json \
  --ledger /secure/ledger/prospective.jsonl \
  --trust-adapter lottery_trust_adapter
```

After cutoff, finalize missing slots:

```sh
PYTHONPATH=src python scripts/build_prospective_schedule.py \
  --mode finalize \
  --lifecycle-root /secure/lottery/lifecycle \
  --schedule /secure/objects/schedule.json \
  --ledger /secure/ledger/prospective.jsonl \
  --trust-adapter lottery_trust_adapter
```

Forecast issuance is exposed as `issue_registered_forecast()` and requires the same protected `schedule_verifier` callback. It rechecks the signed schedule and registry snapshot before writing.  It loads the
front and back distributions from immutable artifacts, verifies full-support
normalization, binds content hashes, checks the current registry snapshot, and
uses the ledger's actual event clock. The evaluator supports the repository's
complete-subset exponential and conditional-Poisson families. Exact scoring
uses `FrozenArtifactEvaluator.evaluate` through
`ProspectiveLedger.score_forecast`; sampled ticket hit rates are not used.

## Deliberate operational boundary

The manual GitHub workflow runs tests only. It does not contain a cron trigger,
secrets, credentials, registry mutation, or live schedule inputs. The protected
trust adapter, authenticated official calendar/inventory, protected outcome
evidence verifier, independent remote immutable storage, and tested restore
drill are deployment dependencies. Until those exist and are independently
verified, production scheduling and serving remain BLOCKED. This code does not
claim that a content hash alone authenticates an official source.

LOT-042 is not imported, opened, or modified by this pipeline. No Champion
promotion, rollback, registry write, or three-slot publication is performed.
