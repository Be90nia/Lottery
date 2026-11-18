#!/usr/bin/env python3
"""Reconcile official lossless prize rows against legacy candidate prize rows.

The legacy candidate does not preserve upstream prize identities, so this tool
never treats a label-only match as source-identity proof. It compares rows as
multisets and reports ambiguity explicitly.
"""
from __future__ import annotations

import argparse, json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any


def dec(v: Any):
    if v is None:
        return None
    text = str(v).strip().replace(",", "").replace("，", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except Exception as exc:
        raise ValueError(f"invalid monetary value: {v!r}") from exc


def count_value(v: Any) -> int:
    if v is None or str(v).strip() == "":
        return 0
    return int(str(v).strip().replace(",", "").replace("，", ""))


def stable_condition(v: Any):
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return v


def official_row(row: dict[str, Any]) -> dict[str, Any]:
    p = row["raw_prize"]
    return {
        "draw_id": row["draw_id"],
        "label": str(p.get("prizeLevel", "")),
        "amount": dec(p.get("stakeAmount")),
        "winner_count": count_value(p.get("stakeCount", 0)),
        "total": dec(p.get("totalPrizeamount")),
        "condition": stable_condition(p.get("lotteryCondition")),
        "source_position": row["source_position"],
        "source_identity": {
            k: p.get(k)
            for k in ("awardType", "group", "prizeLevelNo", "relatedPrizeLevelNo", "sort")
            if k in p
        },
        "source_sha256": row["source"]["snapshot_sha256"],
        "raw_prize_sha256": row["raw_prize_sha256"],
    }


def legacy_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "draw_id": row["draw_id"],
        "label": row["tier_label_original"],
        "amount": dec(row["amount_yuan_original"]),
        "winner_count": count_value(row["winner_count"]),
        "total": dec(row["total_yuan_original"]),
        "condition": stable_condition(row.get("condition_original")),
        "source_identity": None,
    }


def value_key(row: dict[str, Any]):
    return (row["label"], row["amount"], row["winner_count"], row["total"], row["condition"])


def load_jsonl(path: Path):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--official", type=Path, required=True)
    ap.add_argument("--legacy-glob", type=Path, nargs="+", required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    official = [official_row(x) for x in load_jsonl(args.official)]
    legacy = []
    for path in args.legacy_glob:
        legacy.extend(legacy_row(x) for x in load_jsonl(path))

    by_draw_off: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_draw_leg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in official:
        by_draw_off[row["draw_id"]].append(row)
    for row in legacy:
        by_draw_leg[row["draw_id"]].append(row)

    report = {
        "schema": "official-vs-legacy-prize-reconciliation/v1",
        "official_rows": len(official),
        "legacy_rows": len(legacy),
        "official_draws": len(by_draw_off),
        "legacy_draws": len(by_draw_leg),
        "overlap_draws": 0,
        "official_only_rows": 0,
        "legacy_only_rows": 0,
        "value_exact_rows": 0,
        "official_only_draws": 0,
        "legacy_only_draws": 0,
        "statuses": Counter(),
        "draw_summaries": [],
        "examples": [],
    }

    all_draws = sorted(set(by_draw_off) | set(by_draw_leg))
    for draw_id in all_draws:
        o = by_draw_off.get(draw_id, [])
        l = by_draw_leg.get(draw_id, [])
        if not o:
            report["legacy_only_draws"] += 1
            report["legacy_only_rows"] += len(l)
            continue
        if not l:
            report["official_only_draws"] += 1
            report["official_only_rows"] += len(o)
            continue
        report["overlap_draws"] += 1

        oc = Counter(value_key(x) for x in o)
        lc = Counter(value_key(x) for x in l)
        exact_values = sum((oc & lc).values())
        report["value_exact_rows"] += exact_values
        report["official_only_rows"] += sum((oc - lc).values())
        report["legacy_only_rows"] += sum((lc - oc).values())
        unmatched_off = list((oc - lc).elements())
        unmatched_leg = list((lc - oc).elements())

        # A label appearing multiple times on either side cannot be safely
        # mapped by label alone because the legacy cleaner dropped source IDs.
        olabels = Counter(x["label"] for x in o)
        llabels = Counter(x["label"] for x in l)

        if not unmatched_off and not unmatched_leg:
            status = "value_match_without_source_identity"
        elif unmatched_off and unmatched_leg:
            shared_labels = set(olabels) & set(llabels)
            status = (
                "same_label_different_values"
                if shared_labels else "source_rows_differ"
            )
        elif unmatched_off:
            status = "source_row_present_only_official"
        else:
            status = "source_row_present_only_legacy"

        report["statuses"][status] += 1
        if status != "value_match_without_source_identity" and len(report["examples"]) < 200:
            report["examples"].append({
                "draw_id": draw_id,
                "status": status,
                "official_row_count": len(o),
                "legacy_row_count": len(l),
                "unmatched_official": [
                    {"label": x[0], "amount": str(x[1]) if x[1] is not None else None,
                     "winner_count": x[2], "total": str(x[3]) if x[3] is not None else None,
                     "condition": x[4]}
                    for x in unmatched_off[:20]
                ],
                "unmatched_legacy": [
                    {"label": x[0], "amount": str(x[1]) if x[1] is not None else None,
                     "winner_count": x[2], "total": str(x[3]) if x[3] is not None else None,
                     "condition": x[4]}
                    for x in unmatched_leg[:20]
                ],
            })

        report["draw_summaries"].append({
            "draw_id": draw_id,
            "status": status,
            "official_rows": len(o),
            "legacy_rows": len(l),
            "value_exact_rows": exact_values,
            "official_unmatched_rows": sum((oc - lc).values()),
            "legacy_unmatched_rows": sum((lc - oc).values()),
        })

    report["statuses"] = dict(sorted(report["statuses"].items()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        k: report[k] for k in (
            "official_rows", "legacy_rows", "official_draws", "legacy_draws",
            "overlap_draws", "official_only_draws", "legacy_only_draws",
            "value_exact_rows", "official_only_rows", "legacy_only_rows", "statuses"
        )
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
