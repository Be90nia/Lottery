"""Strict ingestion for the public Sporttery historical draw endpoint.

Raw response bytes are archived before parsing. The parser intentionally keeps
only fields whose meaning is clear; uncertain source fields remain in snapshots.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
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


def _fetch_page(page_no: int, page_size: int, timeout: int = 20, retries: int = 3) -> tuple[bytes, int, str]:
    params = urllib.parse.urlencode({
        "gameNo": "85", "provinceId": "0", "pageSize": str(page_size),
        "isVerify": "1", "pageNo": str(page_no),
    })
    url = f"{API_URL}?{params}"
    headers = {
        "Accept": "application/json",
        "User-Agent": "LotteryResearchBot/0.1 (public historical data research)",
        "Referer": "https://www.sporttery.cn/",
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


def _snapshot(raw: bytes, page_no: int, status: int, content_type: str, raw_dir: Path, url: str) -> str:
    digest = hashlib.sha256(raw).hexdigest()
    retrieved_at = datetime.now(timezone.utc).isoformat()
    raw_dir.mkdir(parents=True, exist_ok=True)
    body_path = raw_dir / f"page-{page_no:05d}-{digest[:12]}.json"
    body_path.write_bytes(raw)
    manifest_path = raw_dir / f"page-{page_no:05d}-{digest[:12]}.manifest.json"
    manifest_path.write_text(json.dumps({
        "source": "Sporttery public historical draw API",
        "url": url,
        "retrieved_at": retrieved_at,
        "http_status": status,
        "content_type": content_type,
        "sha256": digest,
        "parser_version": PARSER_VERSION,
        "page_no": page_no,
        "raw_file": body_path.name,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return digest


def _parse_page(raw: bytes, page_no: int, source_id: str) -> list[Draw]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestionError(f"page {page_no}: response is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise IngestionError(f"page {page_no}: top-level JSON must be an object")
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
        rows.append(Draw(
            draw_id=draw_id,
            draw_date=draw_date,
            front_numbers=sorted(front),
            back_numbers=sorted(back),
            source_id=source_id,
        ))
    return rows


def fetch_history(
    output: Path = Path("data/processed/draws.jsonl"),
    raw_dir: Path = Path("data/raw/sporttery"),
    page_size: int = DEFAULT_PAGE_SIZE,
    max_pages: int | None = None,
    delay_seconds: float = 0.5,
) -> dict[str, Any]:
    if not 1 <= page_size <= 100:
        raise ValueError("page_size must be between 1 and 100")
    all_rows: dict[str, Draw] = {}
    page_manifests: list[dict[str, Any]] = []
    for page_no in range(1, (max_pages or 10**9) + 1):
        params = urllib.parse.urlencode({
            "gameNo": "85", "provinceId": "0", "pageSize": str(page_size),
            "isVerify": "1", "pageNo": str(page_no),
        })
        url = f"{API_URL}?{params}"
        raw, status, content_type = _fetch_page(page_no, page_size)
        if status != 200:
            raise IngestionError(f"page {page_no}: unexpected HTTP status {status}")
        digest = _snapshot(raw, page_no, status, content_type, raw_dir, url)
        rows = _parse_page(raw, page_no, digest)
        page_manifests.append({"page_no": page_no, "sha256": digest, "records": len(rows)})
        if not rows:
            break
        for row in rows:
            previous = all_rows.get(row.draw_id)
            if previous is not None:
                same_result = (
                    previous.draw_date == row.draw_date
                    and previous.front_numbers == row.front_numbers
                    and previous.back_numbers == row.back_numbers
                )
                if not same_result:
                    raise IngestionError(f"conflicting duplicate draw_id: {row.draw_id}")
                # The same draw may occur on adjacent pages. Keep the first
                # provenance reference; both page snapshots remain archived.
                continue
            all_rows[row.draw_id] = row
        if len(rows) < page_size:
            break
        if max_pages is not None and page_no >= max_pages:
            break
        if delay_seconds:
            time.sleep(delay_seconds)
    ordered = sorted(all_rows.values(), key=lambda row: (row.draw_date, row.draw_id))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text("".join(json.dumps(asdict(row), ensure_ascii=False) + "\n" for row in ordered), encoding="utf-8")
    temporary.replace(output)
    return {
        "records": len(ordered),
        "first_draw": ordered[0].draw_id if ordered else None,
        "last_draw": ordered[-1].draw_id if ordered else None,
        "output": str(output),
        "pages": page_manifests,
        "parser_version": PARSER_VERSION,
    }
