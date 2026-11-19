"""Strict ingestion for the public Sporttery historical draw endpoint.

Raw response bytes are archived before parsing. The parser intentionally keeps
only fields whose meaning is clear; uncertain source fields remain in snapshots.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

API_URL = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
PARSER_VERSION = "0.1.0"
DEFAULT_PAGE_SIZE = 100


class IngestionError(RuntimeError):
    pass


@dataclass(frozen=True)
class Draw:
    draw_id: str
    draw_date: str
    front_numbers: list[int]
    back_numbers: list[int]
    source_id: str
    front_draw_order: list[int] | None = None
    back_draw_order: list[int] | None = None
    # Raw upstream metadata retained without asserting its physical meaning.
    source_unsort_drawresult: str | None = None
    source_equipment_count: Any = None


def _fetch_page(page_no: int, page_size: int, timeout: int = 20, retries: int = 3) -> tuple[bytes, int, str]:
    params = urllib.parse.urlencode({
        "gameNo": "85", "provinceId": "0", "pageSize": str(page_size),
        "isVerify": "1", "pageNo": str(page_no),
    })
    url = f"{API_URL}?{params}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
        "Referer": "https://m.lottery.gov.cn/",
    }
    last_error: Exception | None = None
    for attempt in range(retries):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read()
                return body, response.status, response.headers.get("Content-Type", "")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(1.5 * (attempt + 1))
    raise IngestionError(f"page {page_no}: request failed after {retries} attempts: {last_error}")


def _atomic_write_new(path: Path, content: bytes) -> None:
    """Atomically create a new file without replacing previous evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.unlink(missing_ok=True)


def _snapshot(raw: bytes, page_no: int, status: int, content_type: str, raw_dir: Path, url: str, run_id: str) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    raw_dir.mkdir(parents=True, exist_ok=True)
    body_path = raw_dir / f"page-{page_no:05d}-{digest[:12]}.json"
    if body_path.exists():
        if hashlib.sha256(body_path.read_bytes()).hexdigest() != digest:
            raise IngestionError(f"content-addressed snapshot collision or corruption: {body_path}")
    else:
        try:
            with body_path.open("xb") as handle:
                handle.write(raw)
                handle.flush()
        except FileExistsError:
            if hashlib.sha256(body_path.read_bytes()).hexdigest() != digest:
                raise IngestionError(f"content-addressed snapshot collision or corruption: {body_path}")

    manifest_path = raw_dir / f"page-{page_no:05d}-{digest[:12]}.manifest.json"
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IngestionError(f"existing snapshot manifest is corrupt: {manifest_path}") from exc
        if (not isinstance(existing, dict) or existing.get("sha256") != digest
                or existing.get("raw_file") != body_path.name
                or existing.get("url") != url or existing.get("http_status") != status):
            raise IngestionError(f"existing immutable snapshot manifest conflicts: {manifest_path}")
    else:
        manifest = {
            "source": "Sporttery public historical draw API",
            "url": url,
            "retrieved_at": retrieved_at,
            "http_status": status,
            "content_type": content_type,
            "sha256": digest,
            "parser_version": PARSER_VERSION,
            "run_id": run_id,
            "page_no": page_no,
            "raw_file": body_path.name,
        }
        try:
            with manifest_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                handle.flush()
        except FileExistsError:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (not isinstance(existing, dict) or existing.get("sha256") != digest
                    or existing.get("raw_file") != body_path.name
                    or existing.get("url") != url or existing.get("http_status") != status):
                raise IngestionError(f"existing immutable snapshot manifest conflicts: {manifest_path}")
    return digest


def _parse_page(raw: bytes, page_no: int, source_id: str) -> list[Draw]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionError(f"page {page_no}: response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise IngestionError(f"page {page_no}: top-level JSON must be an object")
    if payload.get("success") is False:
        raise IngestionError(f"page {page_no}: source reported failure: {payload.get('errorMessage') or payload.get('errorMsg') or 'unknown error'}")
    error_code = payload.get("errorCode")
    if error_code is not None and str(error_code) not in ("0", "00"):
        raise IngestionError(f"page {page_no}: source errorCode={error_code!r}")
    value = payload.get("value")
    if not isinstance(value, dict) or not isinstance(value.get("list"), list):
        raise IngestionError(f"page {page_no}: missing expected value.list array")
    rows: list[Draw] = []
    for index, item in enumerate(value["list"]):
        if not isinstance(item, dict):
            raise IngestionError(f"page {page_no} row {index}: record must be an object")
        draw_id = str(item.get("lotteryDrawNum", "")).strip()
        draw_date = str(item.get("lotteryDrawTime", "")).strip()
        result = str(item.get("lotteryDrawResult", "")).strip()
        parts = result.split()
        if not draw_id or not draw_date or len(parts) != 7:
            raise IngestionError(f"page {page_no} row {index}: missing id/date or result does not contain 7 numbers")
        try:
            numbers = [int(part) for part in parts]
            datetime.strptime(draw_date, "%Y-%m-%d")
        except ValueError as exc:
            raise IngestionError(f"page {page_no} row {index}: invalid date or non-integer number") from exc
        front, back = numbers[:5], numbers[5:]
        if len(set(front)) != 5 or any(n < 1 or n > 35 for n in front):
            raise IngestionError(f"draw {draw_id}: front numbers must be 5 distinct values in 1..35")
        if len(set(back)) != 2 or any(n < 1 or n > 12 for n in back):
            raise IngestionError(f"draw {draw_id}: back numbers must be 2 distinct values in 1..12")
        raw_order_value = item.get("lotteryUnsortDrawresult")
        if raw_order_value is not None and not isinstance(raw_order_value, str):
            raise IngestionError(f"draw {draw_id}: lotteryUnsortDrawresult must be a string or null")
        raw_order = (raw_order_value or "").strip()
        front_order = None
        back_order = None
        if raw_order:
            order_parts = raw_order.split()
            if len(order_parts) != 7:
                raise IngestionError(f"draw {draw_id}: draw order must contain exactly 7 numbers")
            try:
                order = [int(part) for part in order_parts]
            except ValueError as exc:
                raise IngestionError(f"draw {draw_id}: draw order contains a non-integer") from exc
            if (len(set(order[:5])) != 5 or set(order[:5]) != set(front)
                    or len(set(order[5:])) != 2 or set(order[5:]) != set(back)):
                raise IngestionError(f"draw {draw_id}: draw order does not match selected numbers by zone")
            front_order, back_order = order[:5], order[5:]
        rows.append(Draw(
            draw_id=draw_id,
            draw_date=draw_date,
            front_numbers=sorted(front),
            back_numbers=sorted(back),
            source_id=source_id,
            front_draw_order=front_order,
            back_draw_order=back_order,
            source_unsort_drawresult=raw_order_value,
            source_equipment_count=item.get("lotteryEquipmentCount"),
        ))
    return rows


def _add_draw(rows: dict[str, Draw], row: Draw) -> None:
    previous = rows.get(row.draw_id)
    if previous is not None:
        same_result = (
            previous.draw_date == row.draw_date
            and previous.front_numbers == row.front_numbers
            and previous.back_numbers == row.back_numbers
            and previous.front_draw_order == row.front_draw_order
            and previous.back_draw_order == row.back_draw_order
            and previous.source_unsort_drawresult == row.source_unsort_drawresult
            and previous.source_equipment_count == row.source_equipment_count
        )
        if not same_result:
            raise IngestionError(f"conflicting duplicate draw_id: {row.draw_id}")
        # Same draw on adjacent pages: keep the first provenance reference.
        return
    rows[row.draw_id] = row



def ingest_snapshot_directory(
    snapshots_dir: Path,
    output: Path = Path("data/processed/draws.jsonl"),
    require_manifests: bool = False,
) -> dict[str, Any]:
    """Rebuild normalized draws from immutable JSON response snapshots offline."""
    if not snapshots_dir.is_dir():
        raise IngestionError(f"snapshot directory does not exist: {snapshots_dir}")
    snapshot_paths = sorted(
        path for path in snapshots_dir.glob("*.json")
        if not path.name.endswith(".manifest.json")
    )
    if not snapshot_paths:
        raise IngestionError(f"no JSON response snapshots found in {snapshots_dir}")

    all_rows: dict[str, Draw] = {}
    snapshot_reports: list[dict[str, Any]] = []
    provenance_complete = True
    for path in snapshot_paths:
        raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        sidecar_path = path.with_name(path.stem + ".manifest.json")
        sidecar: dict[str, Any] | None = None
        if sidecar_path.exists():
            try:
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise IngestionError(f"{sidecar_path}: invalid JSON manifest") from exc
            if not isinstance(sidecar, dict):
                raise IngestionError(f"{sidecar_path}: manifest must be a JSON object")
            if sidecar.get("sha256") != digest:
                raise IngestionError(f"{sidecar_path}: SHA-256 does not match snapshot bytes")
            if sidecar.get("raw_file") not in (None, path.name):
                raise IngestionError(f"{sidecar_path}: raw_file does not match snapshot filename")
            if sidecar.get("http_status") not in (None, 200):
                raise IngestionError(f"{sidecar_path}: snapshot HTTP status is not 200")
        else:
            provenance_complete = False
            if require_manifests:
                raise IngestionError(f"{path}: required sidecar manifest is missing")

        rows = _parse_page(raw, len(snapshot_reports) + 1, f"sha256:{digest}")
        for row in rows:
            _add_draw(all_rows, row)
        source_url = sidecar.get("url") if isinstance(sidecar, dict) else None
        parsed_url = urllib.parse.urlsplit(source_url) if isinstance(source_url, str) else None
        query = urllib.parse.parse_qs(parsed_url.query) if parsed_url is not None else {}
        retrieved_at = sidecar.get("retrieved_at") if isinstance(sidecar, dict) else None
        timestamp_valid = False
        if isinstance(retrieved_at, str):
            try:
                timestamp = datetime.fromisoformat(retrieved_at.replace("Z", "+00:00"))
                timestamp_valid = timestamp.tzinfo is not None and timestamp.utcoffset() is not None
            except ValueError:
                timestamp_valid = False
        required_provenance = (
            isinstance(sidecar, dict)
            and sidecar.get("source") == "Sporttery public historical draw API"
            and parsed_url is not None
            and parsed_url.scheme == "https"
            and parsed_url.hostname == "webapi.sporttery.cn"
            and parsed_url.path == "/gateway/lottery/getHistoryPageListV1.qry"
            and query.get("gameNo") == ["85"]
            and query.get("provinceId") == ["0"]
            and query.get("isVerify") == ["1"]
            and query.get("pageNo") == [str(sidecar.get("page_no"))]
            and len(query.get("pageSize", [])) == 1
            and query["pageSize"][0].isdigit()
            and 1 <= int(query["pageSize"][0]) <= 100
            and timestamp_valid
            and sidecar.get("http_status") == 200
            and sidecar.get("sha256") == digest
            and sidecar.get("raw_file") == path.name
            and type(sidecar.get("page_no")) is int and sidecar["page_no"] >= 1
            and isinstance(sidecar.get("run_id"), str) and len(sidecar["run_id"]) == 32
            and all(char in "0123456789abcdef" for char in sidecar["run_id"])
        )
        if not required_provenance:
            provenance_complete = False
            if require_manifests:
                raise IngestionError(
                    f"{sidecar_path}: manifest lacks complete official-source provenance"
                )
        snapshot_reports.append({
            "page_no": sidecar.get("page_no") if isinstance(sidecar, dict) else None,
            "run_id": sidecar.get("run_id") if isinstance(sidecar, dict) else None,
            "raw_file": path.name,
            "sha256": digest,
            "bytes": len(raw),
            "records": len(rows),
            "sidecar_manifest": sidecar_path.name if sidecar is not None else None,
            "provenance_complete": bool(required_provenance),
        })

    if provenance_complete:
        page_numbers = [item["page_no"] for item in snapshot_reports]
        run_ids = {item["run_id"] for item in snapshot_reports}
        if page_numbers != list(range(1, len(snapshot_reports) + 1)) or len(run_ids) != 1:
            raise IngestionError("snapshot directory must contain one contiguous page sequence from one fetch run")

    ordered = sorted(all_rows.values(), key=lambda row: (row.draw_date, row.draw_id))
    from .validate import validate_records
    validation = validate_records([asdict(row) for row in ordered])

    output_manifest_path = output.with_suffix(output.suffix + ".manifest.json")
    if output.exists() or output_manifest_path.exists():
        raise IngestionError("output or output manifest already exists; refusing to overwrite prior evidence")

    manifest = {
        "source": "offline import of immutable JSON response snapshots",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "parser_version": PARSER_VERSION,
        "snapshot_count": len(snapshot_reports),
        "snapshot_sha256": [item["sha256"] for item in snapshot_reports],
        "snapshots": snapshot_reports,
        "provenance_complete": provenance_complete,
        # The current endpoint parser does not verify authoritative total-page/record metadata.
        # Therefore this import is never append-eligible until that contract is implemented.
        "source_completeness_verified": False,
        "completeness_evidence": None,
        "validation": validation,
        "output_file": output.name,
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "trust_status": "candidate_unverified" if not provenance_complete else "manifest_complete_not_officially_authenticated",
    }
    output_bytes = "".join(
        json.dumps(asdict(row), ensure_ascii=False) + "\n" for row in ordered
    ).encode("utf-8")
    manifest["output_sha256"] = hashlib.sha256(output_bytes).hexdigest()
    _atomic_write_new(output, output_bytes)
    _atomic_write_new(
        output_manifest_path,
        (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )
    return manifest

def fetch_history(
    output: Path = Path("data/processed/draws.jsonl"),
    raw_dir: Path = Path("data/raw/sporttery"),
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    delay_seconds: float = 0.5,
) -> dict[str, Any]:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if delay_seconds < 0:
        raise ValueError("delay_seconds must not be negative")
    if output.exists():
        raise IngestionError("output already exists; refusing to overwrite prior evidence")
    run_id = uuid.uuid4().hex
    run_raw_dir = raw_dir / run_id
    all_rows: dict[str, Draw] = {}
    page_manifests: list[dict[str, Any]] = []
    pagination_end_reason: str | None = None
    for page_no in range(1, (max_pages or 10**9) + 1):
        params = urllib.parse.urlencode({
            "gameNo": "85", "provinceId": "0", "pageSize": str(page_size),
            "isVerify": "1", "pageNo": str(page_no),
        })
        url = f"{API_URL}?{params}"
        raw, status, content_type = _fetch_page(page_no, page_size)
        if status != 200:
            raise IngestionError(f"page {page_no}: unexpected HTTP status {status}")
        digest = _snapshot(raw, page_no, status, content_type, run_raw_dir, url, run_id)
        rows = _parse_page(raw, page_no, digest)
        page_manifests.append({"page_no": page_no, "sha256": digest, "records": len(rows), "run_id": run_id})
        if not rows:
            if page_no == 1:
                raise IngestionError("page 1: source returned no draws; refusing to publish an empty dataset")
            pagination_end_reason = "empty_page"
            break
        for row in rows:
            _add_draw(all_rows, row)
        if len(rows) < page_size:
            pagination_end_reason = "short_page"
            break
        if max_pages is not None and page_no >= max_pages:
            raise IngestionError(
                f"pagination limit reached at page {page_no} while page was full; "
                "refusing to publish a potentially truncated dataset"
            )
        if delay_seconds:
            time.sleep(delay_seconds)
    ordered = sorted(all_rows.values(), key=lambda row: (row.draw_date, row.draw_id))
    output_bytes = "".join(
        json.dumps(asdict(row), ensure_ascii=False) + "\n" for row in ordered
    ).encode("utf-8")
    _atomic_write_new(output, output_bytes)
    return {
        "records": len(ordered),
        "first_draw": ordered[0].draw_id if ordered else None,
        "last_draw": ordered[-1].draw_id if ordered else None,
        "output": str(output),
        "raw_dir": str(run_raw_dir),
        "pages": page_manifests,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "pagination_end_reason": pagination_end_reason,
        "source_completeness_verified": False,
        "trust_status": "manifest_complete_not_officially_authenticated",
    }
