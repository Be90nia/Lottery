"""Immutable archival and parsing of official per-draw ball-set announcements."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .ledger_lock import ledger_lock
from .validate import validate_records, DatasetValidationError

COLLECTOR_VERSION = "0.1.0"
PARSER_VERSION = "0.1.0"
OBSERVATION_SCHEMA = "lottery.ball-set-observation/v1"
ALLOWED_HOSTS = {"www.js-lottery.com", "api.js-lottery.com"}
DRAW_TITLE = re.compile(r"超级大乐透第\s*(\d{5})\s*期开奖公告")
DRAW_DATE = re.compile(r"开奖日期\s*[：:]\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
SET_LABEL = re.compile(r"本期使用第\s*(\d+)\s*套摇奖球")
ANCHOR_DRAW = re.compile(r"超级大乐透第\s*(\d{5})\s*期开奖公告")


class BallSetEvidenceError(RuntimeError):
    """Raised when an official announcement cannot be safely archived."""


@dataclass(frozen=True)
class ParsedAnnouncement:
    draw_id: str
    draw_date: str
    reported_set_index: int | None
    observation_status: str
    matched_text: str | None
    evidence_start: int | None
    evidence_end: int | None
    newer_links: tuple[tuple[str, str], ...]
    authority_footer_present: bool


class _AnnouncementHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.anchors: list[tuple[str, str]] = []
        self._anchor_href: str | None = None
        self._anchor_parts: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            self._anchor_href = dict(attrs).get("href")
            self._anchor_parts = []
        if tag.lower() in {"p", "div", "tr", "td", "th", "br", "li", "h1", "h2"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._anchor_href is not None:
            self.anchors.append((self._anchor_href, "".join(self._anchor_parts)))
            self._anchor_href = None
            self._anchor_parts = []
        if tag.lower() in {"p", "div", "tr", "td", "th", "li", "h1", "h2"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if data:
            self.text_parts.append(data)
            if self._anchor_href is not None:
                self._anchor_parts.append(data)

    @property
    def text(self) -> str:
        return re.sub(r"[ \t\r\f\v]+", " ", "".join(self.text_parts)).strip()


def _decode_html(raw: bytes, content_type: str) -> str:
    match = re.search(r"charset\s*=\s*['\"]?([A-Za-z0-9._-]+)", content_type, re.I)
    if not match:
        meta = raw[:4096].decode("ascii", errors="ignore")
        match = re.search(r"charset\s*=\s*['"]?([A-Za-z0-9._-]+)", meta, re.I)
    encoding = match.group(1) if match else "utf-8"
    try:
        return raw.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise BallSetEvidenceError(f"announcement body cannot be decoded as {encoding}") from exc


def _allowed_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise BallSetEvidenceError(f"source URL is not an approved official Jiangsu host: {url}")


def parse_announcement(raw: bytes, source_url: str, content_type: str = "text/html; charset=utf-8") -> ParsedAnnouncement:
    """Parse only literal announcement fields; never infer a missing ball-set label."""
    _allowed_url(source_url)
    html = _decode_html(raw, content_type)
    parser = _AnnouncementHTMLParser()
    parser.feed(html)
    parser.close()
    text = parser.text
    title_match = DRAW_TITLE.search(text)
    date_match = DRAW_DATE.search(text)
    if not title_match or not date_match:
        raise BallSetEvidenceError("announcement is missing an explicit draw title or draw date")
    draw_id = title_match.group(1)
    draw_date = f"{int(date_match.group(1)):04d}-{int(date_match.group(2)):02d}-{int(date_match.group(3)):02d}"
    try:
        datetime.strptime(draw_date, "%Y-%m-%d")
    except ValueError as exc:
        raise BallSetEvidenceError("announcement contains an invalid draw date") from exc

    labels = list(SET_LABEL.finditer(text))
    distinct = sorted({int(match.group(1)) for match in labels})
    if len(distinct) > 1:
        status, set_index, matched, start, end = "conflict", None, None, None, None
    elif not labels:
        status, set_index, matched, start, end = "missing_label", None, None, None, None
    elif distinct[0] not in (1, 2, 3):
        match = labels[0]
        status, set_index = "unsupported_label", None
        matched, start, end = match.group(0), match.start(), match.end()
    else:
        match = labels[0]
        status, set_index = "primary_verified", int(match.group(1))
        matched, start, end = match.group(0), match.start(), match.end()

    newer: list[tuple[str, str]] = []
    for href, anchor_text in parser.anchors:
        match = ANCHOR_DRAW.search(anchor_text)
        if not match:
            continue
        next_id = match.group(1)
        absolute = urljoin(source_url, href)
        try:
            _allowed_url(absolute)
        except BallSetEvidenceError:
            continue
        newer.append((next_id, absolute))
    newer = sorted(set(newer), key=lambda item: item[0])
    return ParsedAnnouncement(
        draw_id=draw_id, draw_date=draw_date, reported_set_index=set_index,
        observation_status=status, matched_text=matched,
        evidence_start=start, evidence_end=end, newer_links=tuple(newer),
        authority_footer_present="江苏省体育彩票管理中心" in text,
    )


class _RedirectTracker(HTTPRedirectHandler):
    def __init__(self):
        super().__init__()
        self.chain: list[dict[str, Any]] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.chain.append({"status": code, "url": newurl})
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_announcement(url: str, timeout: int = 20) -> dict[str, Any]:
    _allowed_url(url)
    tracker = _RedirectTracker()
    opener = build_opener(tracker)
    request = Request(url, headers={
        "Accept": "text/html,application/xhtml+xml",
        "User-Agent": "LotteryResearchEvidenceCollector/0.1 (+public official-source archival)",
    })
    retrieved_at = datetime.now(timezone.utc).isoformat()
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
            headers = response.headers
    except HTTPError as exc:
        _allowed_url(exc.geturl())
        return {
            "requested_url": url, "final_url": exc.geturl(), "redirect_chain": tracker.chain,
            "retrieved_at_utc": retrieved_at, "http_status": exc.code,
            "content_type": exc.headers.get("Content-Type", "") if exc.headers else "",
            "body": exc.read(), "headers": exc.headers,
        }
    except (URLError, TimeoutError, OSError) as exc:
        raise BallSetEvidenceError(f"official source request failed: {exc}") from exc
    _allowed_url(final_url)
    if status != 200:
        raise BallSetEvidenceError(f"unexpected HTTP status {status} for {url}")
    if "html" not in content_type.lower():
        raise BallSetEvidenceError(f"unexpected content type {content_type!r} for {url}")
    return {
        "requested_url": url, "final_url": final_url, "redirect_chain": tracker.chain,
        "retrieved_at_utc": retrieved_at, "http_status": status,
        "content_type": content_type, "body": body, "headers": headers,
    }


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_ledger(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []
    observations = []
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                raise BallSetEvidenceError(f"observation ledger has blank line {line_no}")
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise BallSetEvidenceError(f"observation ledger has invalid JSON at line {line_no}") from exc
            if not isinstance(item, dict) or item.get("schema_version") != OBSERVATION_SCHEMA:
                raise BallSetEvidenceError(f"observation ledger has unsupported record at line {line_no}")
            observations.append(item)
    ids = [item.get("observation_id") for item in observations]
    if len(ids) != len(set(ids)):
        raise BallSetEvidenceError("observation ledger contains duplicate observation IDs")
    return observations


def _next_draw_id(previous: str, candidate: str) -> bool:
    if not (previous.isdigit() and candidate.isdigit() and len(previous) == 5 and len(candidate) == 5):
        return False
    previous_year, previous_seq = int(previous[:2]), int(previous[2:])
    candidate_year, candidate_seq = int(candidate[:2]), int(candidate[2:])
    if candidate_year == previous_year:
        return candidate_seq == previous_seq + 1
    return candidate_year == previous_year + 1 and candidate_seq == 1


def _archive_raw_response(fetched: dict[str, Any], archive_dir: Path, authority_name: str) -> dict[str, Any]:
    body: bytes = fetched["body"]
    digest = hashlib.sha256(body).hexdigest()
    raw_dir = archive_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / f"{digest}.html"
    if not raw_path.exists():
        try:
            with raw_path.open("xb") as handle:
                handle.write(body)
                handle.flush()
                import os
                os.fsync(handle.fileno())
        except FileExistsError:
            pass
    if hashlib.sha256(raw_path.read_bytes()).hexdigest() != digest:
        raise BallSetEvidenceError(f"content-addressed raw object was modified: {raw_path}")
    manifest = {
        "schema_version": 1, "source_authority_class": "A2",
        "source_authority_name": authority_name,
        "requested_url": fetched["requested_url"], "final_url": fetched["final_url"],
        "redirect_chain": fetched["redirect_chain"], "retrieved_at_utc": fetched["retrieved_at_utc"],
        "http_status": fetched["http_status"], "content_type": fetched["content_type"],
        "body_byte_length": len(body), "body_sha256": digest,
        "etag": fetched["headers"].get("ETag") if fetched["headers"] else None,
        "last_modified": fetched["headers"].get("Last-Modified") if fetched["headers"] else None,
        "collector_version": COLLECTOR_VERSION, "parser_version": PARSER_VERSION,
        "raw_object_ref": str(raw_path.relative_to(archive_dir)),
    }
    retrieval_id = hashlib.sha256(
        (fetched["requested_url"] + fetched["retrieved_at_utc"]).encode("utf-8")
    ).hexdigest()[:16]
    manifest_path = raw_dir / f"{digest}.{retrieval_id}.manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest["manifest_object_ref"] = str(manifest_path.relative_to(archive_dir))
    return manifest


def _archive_observation(
    fetched: dict[str, Any], parsed: ParsedAnnouncement, manifest: dict[str, Any], *,
    expected_draw_id: str | None, expected_draw_date: str | None,
    ledger_path: Path, inventory: dict[str, str], inventory_sha256: str,
) -> dict[str, Any]:
    digest = manifest["body_sha256"]
    source_url = fetched["final_url"]
    if expected_draw_id is not None and parsed.draw_id != expected_draw_id:
        status = "draw_mismatch"
    elif expected_draw_date is not None and parsed.draw_date != expected_draw_date:
        status = "draw_mismatch"
    elif not parsed.authority_footer_present:
        status = "source_authority_unverified"
    elif parsed.observation_status == "primary_verified":
        if parsed.draw_id not in inventory:
            status = "official_label_pending_inventory"
        elif inventory[parsed.draw_id] != parsed.draw_date:
            status = "draw_mismatch"
        else:
            status = "primary_verified"
    else:
        status = parsed.observation_status

    ledger_before = _read_ledger(ledger_path)
    previous = [
        item for item in ledger_before
        if item.get("draw_id") == parsed.draw_id
        and item.get("source", {}).get("final_url") == source_url
    ]
    previous.sort(key=lambda item: item.get("source", {}).get("retrieved_at_utc", ""))
    supersedes = previous[-1] if previous else None
    if supersedes and supersedes.get("source", {}).get("body_sha256") == digest:
        return {"status": "duplicate_noop", "observation_id": supersedes["observation_id"],
                "draw_id": parsed.draw_id, "body_sha256": digest}

    if supersedes:
        prior_status = supersedes.get("observation_status")
        same_semantics = (
            supersedes.get("draw_date") == parsed.draw_date
            and supersedes.get("reported_set_index") == parsed.reported_set_index
            and prior_status not in ("conflict", "source_revision_requires_review", "draw_mismatch")
        )
        status = "source_revision_same_semantics" if same_semantics else "source_revision_requires_review"
    elif status == "primary_verified":
        other_labels = {
            item.get("reported_set_index") for item in ledger_before
            if item.get("draw_id") == parsed.draw_id
            and item.get("observation_status") == "primary_verified"
            and item.get("source", {}).get("authority_class") in ("A1", "A2")
        }
        if other_labels and parsed.reported_set_index not in other_labels:
            status = "conflict"

    identity = {"draw_id": parsed.draw_id, "source_url": source_url, "body_sha256": digest}
    observation_id = _canonical_hash(identity)
    conflict_group = _canonical_hash({"draw_id": parsed.draw_id}) if status in (
        "conflict", "source_revision_requires_review"
    ) else None
    observation = {
        "schema_version": OBSERVATION_SCHEMA,
        "observation_id": observation_id,
        "draw_id": parsed.draw_id,
        "draw_date": parsed.draw_date,
        "source": {**manifest, "authority_class": "A2"},
        "parser": {
            "name": "dlt-official-ball-set-announcement",
            "version": PARSER_VERSION,
            "evidence_locator": {
                "text_character_start": parsed.evidence_start,
                "text_character_end": parsed.evidence_end,
            },
            "matched_text": parsed.matched_text,
        },
        "reported_set_index": parsed.reported_set_index,
        "inventory_crosswalk_at_capture": {
            "status": "not_in_inventory" if parsed.draw_id not in inventory else (
                "matched" if inventory[parsed.draw_id] == parsed.draw_date else "date_mismatch"
            ),
            "inventory_sha256": inventory_sha256,
            "inventory_trust_status": "candidate_unverified",
        },
        "equipment_regime_id": None,
        "physical_ball_set_id": None,
        "observation_status": status,
        "conflict_group_id": conflict_group,
        "supersedes_observation_id": supersedes.get("observation_id") if supersedes else None,
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_lock(ledger_path):
        existing_ids = {item["observation_id"] for item in _read_ledger(ledger_path)}
        if observation_id not in existing_ids:
            with ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(observation, ensure_ascii=False, sort_keys=True) + "\n")
                handle.flush()
                import os
                os.fsync(handle.fileno())
    return {"status": status, "observation_id": observation_id,
            "draw_id": parsed.draw_id, "reported_set_index": parsed.reported_set_index,
            "body_sha256": digest}


def collect_ball_set_evidence(
    registry_path: Path, archive_dir: Path, ledger_path: Path, *,
    receipt_path: Path, draw_inventory_path: Path, delay_seconds: float = 0.5,
    max_forward_pages: int = 2000,
) -> dict[str, Any]:
    if delay_seconds < 0 or type(max_forward_pages) is not int or max_forward_pages < 1:
        raise ValueError("invalid delay or max_forward_pages")
    inventory_bytes = draw_inventory_path.read_bytes()
    inventory_sha256 = hashlib.sha256(inventory_bytes).hexdigest()
    inventory_rows = []
    try:
        inventory_rows = [json.loads(line) for line in inventory_bytes.decode("utf-8").splitlines() if line]
        validate_records(inventory_rows)
    except (UnicodeDecodeError, json.JSONDecodeError, DatasetValidationError) as exc:
        raise BallSetEvidenceError(f"draw inventory is invalid: {exc}") from exc
    inventory = {row["draw_id"]: row["draw_date"] for row in inventory_rows}
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        raise BallSetEvidenceError("unsupported source registry schema")
    if registry.get("authority_class") != "A2":
        raise BallSetEvidenceError("source registry must declare A2 official provincial authority")
    authority_name = registry.get("authority_name")
    if not isinstance(authority_name, str) or not authority_name:
        raise BallSetEvidenceError("source registry authority_name is required")
    seed_url = registry.get("seed_url")
    _allowed_url(seed_url)

    observations = _read_ledger(ledger_path)
    known = [item for item in observations if item.get("source", {}).get("authority_class") == "A2"]
    if known:
        latest = max(known, key=lambda item: (item["draw_id"], item["source"].get("retrieved_at_utc", "")))
        previous_id = latest["draw_id"]
        current_url = latest["source"]["requested_url"]
        expected_date = latest["draw_date"]
    else:
        previous_id = registry.get("seed_draw_id")
        current_url = seed_url
        expected_date = registry.get("seed_draw_date")
    if not isinstance(previous_id, str) or not re.fullmatch(r"\d{5}", previous_id):
        raise BallSetEvidenceError("source registry or ledger lacks a valid latest draw ID")

    fetched_pages: list[dict[str, Any]] = []
    observation_results: list[dict[str, Any]] = []
    visited: set[str] = set()
    status = "no_new_page"
    next_expected: str | None = None
    errors: list[str] = []
    fatal_statuses = {"draw_mismatch", "conflict", "source_authority_unverified", "source_revision_requires_review"}
    for page_index in range(max_forward_pages):
        if current_url in visited:
            errors.append("source announcement chain contains a URL cycle")
            status = "parse_error"
            break
        visited.add(current_url)
        try:
            fetched = fetch_announcement(current_url)
        except BallSetEvidenceError as exc:
            errors.append(str(exc))
            status = "source_unavailable"
            break
        if fetched["http_status"] == 404 and page_index > 0:
            status = "not_yet_published"
            break
        if fetched["http_status"] != 200:
            errors.append(f"official page returned HTTP {fetched['http_status']}")
            status = "source_unavailable"
            break

        # Preserve exact bytes and metadata before any decoding or parsing.
        manifest = _archive_raw_response(fetched, archive_dir, authority_name)
        try:
            parsed = parse_announcement(fetched["body"], fetched["final_url"], fetched["content_type"])
        except BallSetEvidenceError as exc:
            errors.append(str(exc))
            status = "parse_error"
            fetched_pages.append({"url": fetched["final_url"], "body_sha256": manifest["body_sha256"],
                                  "status": "parse_error"})
            break

        if parsed.draw_id != previous_id and page_index == 0:
            expected_id = previous_id
        elif page_index > 0 and not _next_draw_id(previous_id, parsed.draw_id):
            errors.append(f"draw chain gap or non-monotonic ID: {previous_id} -> {parsed.draw_id}")
            status = "draw_mismatch"
            break
        else:
            expected_id = previous_id if page_index == 0 else parsed.draw_id
        if page_index > 0 and parsed.draw_date <= fetched_pages[-1]["draw_date"]:
            errors.append("official draw dates are not strictly increasing")
            status = "draw_mismatch"
            break

        result = _archive_observation(
            fetched, parsed, manifest,
            expected_draw_id=expected_id,
            expected_draw_date=expected_date if page_index == 0 else None,
            ledger_path=ledger_path, inventory=inventory, inventory_sha256=inventory_sha256,
        )
        observation_results.append(result)
        fetched_pages.append({
            "draw_id": parsed.draw_id, "draw_date": parsed.draw_date,
            "url": fetched["final_url"], "body_sha256": manifest["body_sha256"],
            "status": result["status"],
        })
        if result["status"] in fatal_statuses:
            status = "review_required"
            errors.append(f"observation {parsed.draw_id} requires review: {result['status']}")
            break

        previous_id = parsed.draw_id
        expected_date = parsed.draw_date
        next_links = [item for item in parsed.newer_links if item[0] > previous_id]
        if not next_links:
            status = "captured" if any(item["status"] != "duplicate_noop" for item in observation_results) else "no_new_page"
            break
        next_id, next_url = min(next_links, key=lambda item: item[0])
        if not _next_draw_id(previous_id, next_id):
            errors.append(f"official announcement navigation skipped a draw: {previous_id} -> {next_id}")
            status = "draw_mismatch"
            break
        next_expected = next_id
        current_url = next_url
        if delay_seconds:
            time.sleep(delay_seconds)
    else:
        errors.append("max_forward_pages reached while newer announcement links remain")
        status = "page_limit_reached"

    receipt = {
        "schema_version": 1, "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_authority_class": "A2", "source_authority_name": authority_name,
        "collector_version": COLLECTOR_VERSION, "parser_version": PARSER_VERSION,
        "pages_observed": fetched_pages, "observation_results": observation_results,
        "latest_draw_id": previous_id, "next_expected_draw_id": next_expected,
        "archive_observation_count": len(_read_ledger(ledger_path)),
        "draw_inventory_sha256": inventory_sha256,
        "draw_inventory_rows": len(inventory_rows),
        "draw_inventory_trust_status": "candidate_unverified",
        "inventory_crosswalk": {
            "matched_draws": sum(1 for item in fetched_pages if item.get("draw_id") in inventory and inventory[item["draw_id"]] == item.get("draw_date")),
            "not_in_inventory": sum(1 for item in fetched_pages if item.get("draw_id") not in inventory),
            "date_mismatches": sum(1 for item in fetched_pages if item.get("draw_id") in inventory and inventory[item["draw_id"]] != item.get("draw_date")),
        },
        "errors": errors,
        "source_completeness_verified": False,
        "equipment_regime_adjudicated": False,
        "physical_identity_adjudicated": False,
        "model_training_or_promotion": False,
        "holdout_accessed": False,
    }
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--archive-dir", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--draw-inventory", type=Path, required=True)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--max-forward-pages", type=int, default=2000)
    args = parser.parse_args()
    try:
        receipt = collect_ball_set_evidence(
            args.registry, args.archive_dir, args.ledger,
            receipt_path=args.receipt, draw_inventory_path=args.draw_inventory,
            delay_seconds=args.delay, max_forward_pages=args.max_forward_pages,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 1 if receipt["status"] in ("source_unavailable", "parse_error", "draw_mismatch", "review_required", "page_limit_reached") else 0
    except (OSError, ValueError, BallSetEvidenceError) as exc:
        print(f"BALL_SET_EVIDENCE_FAILED: {exc}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
