# Outcome recording: bind parsed values to source evidence

The outcome-ledger CLI accepts an exact raw response snapshot. The CLI now parses that snapshot using the strict Sporttery history parser and derives the selected front/back values from the matching draw ID. User-supplied `--front` and `--back` values are retained only as a cross-check; they must match the raw response.

The source URL must be HTTPS on the exact `webapi.sporttery.cn` host, use the documented history endpoint, and identify `gameNo=85`. HTTP status must be 200. The snapshot must contain exactly one record for the requested target draw. Missing, duplicate, malformed, or mismatched records fail closed before the append-only outcome ledger is modified.

This verifies internal consistency between the archived bytes and the ledger event. It does not cryptographically authenticate the publisher, prove the endpoint is reachable from the production runner, or independently verify the source's authority. Preserve the raw bytes and their SHA-256 with the ledger evidence.
