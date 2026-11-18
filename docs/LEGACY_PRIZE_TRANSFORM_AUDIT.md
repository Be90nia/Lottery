# Legacy prize transformation audit

**Status:** source-code audit only. The upstream raw response file is not
available in the legacy repository, so this document does not claim to have
reconstructed any individual raw prize row.

## Upstream transformation examined

The legacy project contains
[`scripts/clean_dlt.py`](https://github.com/rbk64513-debug/dlt-analysis/blob/main/scripts/clean_dlt.py).
For each item in `prizeLevelList`, it reads:

- `prizeLevel` as the displayed label;
- `stakeAmount` as the unit amount;
- `stakeCount` as the winner count;
- `totalPrizeamount` as the aggregate amount;
- `lotteryCondition` as the condition text.

The script also contains:

```python
if p.get("awardType") != 0:  # 仅基本奖级
    pass
```

This branch does not filter anything: `pass` continues processing the row.
The cleaner then omits `awardType`, `prizeLevelNo`,
`relatedPrizeLevelNo`, `sort`, and `singleUnitBetPrizeDescr` from its
output. Whether `awardType` is actually present in every upstream response
has not been established because `data/dlt_history_raw.json` was not checked
into that repository.

## Consequences

1. The cleaned representation cannot later distinguish source rows by the
   omitted identifiers if their displayed labels are ambiguous.
2. The no-op filter means the script does not implement the filtering its
   comment describes.
3. The transformation does not preserve each complete source prize object,
   so an apparent unit amount/count mismatch cannot be traced back to the
   exact upstream field values.
4. This is a credible lineage weakness, but it is not proof that this one bug
   caused the specific 07008, 16106, 17045, 17052, 17062, or 17063 candidate
   discrepancies. Those require the missing raw source objects.

## Required replacement

A replacement official prize ingestion path must:

- preserve the complete raw prize object without dropping unknown fields;
- retain the original draw ID and source snapshot SHA-256;
- retain `prizeLevel`, `stakeAmount`, `stakeCount`,
  `totalPrizeamount`, `lotteryCondition`, and every other source field
  verbatim when present;
- preserve `awardType`, `prizeLevelNo`, `relatedPrizeLevelNo`,
  `sort`, and `singleUnitBetPrizeDescr` when present, without guessing
  their semantics;
- classify base/additional/promotion rows only after the raw schema and
  effective rules have been verified;
- reject or quarantine duplicate/ambiguous prize-row identities rather than
  silently overwriting them;
- keep derived normalized values separate from raw source values.

The existing `data/candidates/legacy_prizes_part_*.jsonl` files remain
candidate-only. Do not repair them in place or promote them to canonical
accounting data.
