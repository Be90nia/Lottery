"""Fail-closed append-only reconciliation of a validated full draw snapshot."""
from __future__ import annotations
import argparse, hashlib, json, os, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .validate import validate_records, DatasetValidationError

class AppendOnlyError(ValueError):
    """Candidate history cannot safely extend the current dataset."""

def _read(path: Path) -> list[dict[str, Any]]:
    rows=[]
    with path.open(encoding="utf-8") as f:
        for n,line in enumerate(f,1):
            if not line.strip(): raise AppendOnlyError(f"{path}: blank line {n}")
            try: row=json.loads(line)
            except json.JSONDecodeError as e: raise AppendOnlyError(f"{path}: invalid JSON line {n}") from e
            if not isinstance(row,dict): raise AppendOnlyError(f"{path}: line {n} is not an object")
            rows.append(row)
    try: validate_records(rows)
    except DatasetValidationError as e: raise AppendOnlyError(f"{path}: {e}") from e
    return rows

def _semantic(r):
    return (r["draw_id"],r["draw_date"],tuple(r["front_numbers"]),tuple(r["back_numbers"]),
            tuple(r.get("front_draw_order") or ()),tuple(r.get("back_draw_order") or ()),
            r.get("source_unsort_drawresult"),r.get("source_equipment_count"))

def _hash(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

def reconcile_append_only(current_path: Path,candidate_path: Path,candidate_manifest_path: Path,
                          output_path: Path,receipt_path: Path) -> dict[str,Any]:
    protected = [current_path, candidate_path, candidate_manifest_path]
    destinations = [output_path, receipt_path]
    resolved_inputs = {p.resolve() for p in protected}
    resolved_outputs = [p.resolve() for p in destinations]
    if len(set(resolved_outputs)) != len(resolved_outputs) or any(p in resolved_inputs for p in resolved_outputs):
        raise AppendOnlyError("output and receipt paths must be distinct from each other and every input")
    current=_read(current_path); candidate=_read(candidate_path)
    try: manifest=json.loads(candidate_manifest_path.read_text(encoding="utf-8"))
    except (OSError,UnicodeDecodeError,json.JSONDecodeError) as e:
        raise AppendOnlyError(f"candidate manifest unreadable: {e}") from e
    if not isinstance(manifest,dict): raise AppendOnlyError("candidate manifest must be an object")
    if manifest.get("output_sha256") != _hash(candidate_path):
        raise AppendOnlyError("candidate manifest output_sha256 does not match candidate bytes")
    if manifest.get("trust_status") != "manifest_complete_not_officially_authenticated" or manifest.get("provenance_complete") is not True:
        raise AppendOnlyError("candidate must have complete official-source manifests; authenticity remains unverified")
    if not isinstance(manifest.get("validation"),dict) or manifest["validation"].get("records") != len(candidate):
        raise AppendOnlyError("candidate manifest validation record count is missing or inconsistent")
    old={r["draw_id"]:r for r in current}; new={r["draw_id"]:r for r in candidate}
    missing=sorted(set(old)-set(new))
    if missing: raise AppendOnlyError(f"candidate is not a full snapshot; missing existing draw IDs: {missing[:10]}")
    changed=sorted(k for k in old if _semantic(old[k]) != _semantic(new[k]))
    if changed: raise AppendOnlyError(f"historical correction or metadata conflict for draw IDs {changed[:10]}; refusing silent replacement")
    last=max(current,key=lambda r:(r["draw_date"],r["draw_id"]))
    additions=sorted((r for r in candidate if r["draw_id"] not in old),key=lambda r:(r["draw_date"],r["draw_id"]))
    boundary=(last["draw_date"],last["draw_id"])
    for r in additions:
        if (r["draw_date"],r["draw_id"]) <= boundary:
            raise AppendOnlyError(f"new draw {r['draw_id']} is not strictly after current chronology boundary")
    if additions:
        merged=current+additions
        try: validation=validate_records(merged)
        except DatasetValidationError as e: raise AppendOnlyError(f"merged dataset invalid: {e}") from e
        output_path.parent.mkdir(parents=True,exist_ok=True)
        tmp=output_path.with_name(output_path.name+".tmp")
        with tmp.open("w",encoding="utf-8",newline="\n") as f:
            f.write("".join(json.dumps(r,ensure_ascii=False,sort_keys=True)+"\n" for r in merged))
            f.flush(); os.fsync(f.fileno())
        os.replace(tmp,output_path)
        status="appended"; output_sha=_hash(output_path)
    else:
        validation=validate_records(current); status="no_new_draws"; output_sha=_hash(current_path)
    receipt={
      "schema_version":1,"status":status,"created_at":datetime.now(timezone.utc).isoformat(),
      "current_sha256":_hash(current_path),"candidate_sha256":_hash(candidate_path),
      "candidate_manifest_sha256":_hash(candidate_manifest_path),"candidate_snapshot_count":manifest.get("snapshot_count"),
      "candidate_trust_status":manifest["trust_status"],"output_sha256":output_sha,
      "previous_records":len(current),"candidate_records":len(candidate),"appended_records":len(additions),
      "appended_draw_ids":[r["draw_id"] for r in additions],"validation":validation,
      "publication":"new local artifact only; no model training or promotion"}
    receipt_path.parent.mkdir(parents=True,exist_ok=True)
    receipt_path.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return receipt

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--current",type=Path,required=True); p.add_argument("--candidate",type=Path,required=True)
    p.add_argument("--candidate-manifest",type=Path,required=True); p.add_argument("--output",type=Path,required=True)
    p.add_argument("--receipt",type=Path,required=True); a=p.parse_args()
    try:
        result=reconcile_append_only(a.current,a.candidate,a.candidate_manifest,a.output,a.receipt)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0
    except (OSError,AppendOnlyError,DatasetValidationError) as e:
        print(f"DRAW_APPEND_ONLY_FAILED: {e}",file=sys.stderr); return 1

if __name__=="__main__": raise SystemExit(main())
