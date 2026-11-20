"use strict";

const assert = require("node:assert/strict");
const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");

const fixturePath = path.join(__dirname, "fixtures", "jcs-golden-v1.json");
const fixture = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

function canonicalize(value) {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new TypeError("non-finite number");
    return JSON.stringify(value);
  }
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) {
    return "[" + value.map(canonicalize).join(",") + "]";
  }
  if (typeof value === "object") {
    const keys = Object.keys(value).sort();
    return "{" + keys.map((key) =>
      JSON.stringify(key) + ":" + canonicalize(value[key])
    ).join(",") + "}";
  }
  throw new TypeError("unsupported JSON value");
}

const canonical = canonicalize(fixture.input);
assert.equal(canonical, fixture.canonical_utf8);
const digest = crypto.createHash("sha256").update(canonical, "utf8").digest("hex");
assert.equal(digest, fixture.sha256);
for (const vector of fixture.binary64_vectors) {
  const number = Buffer.from(vector.hex, "hex").readDoubleBE(0);
  assert.equal(canonicalize(number), vector.expected, "RFC 8785 vector " + vector.hex);
}
for (const hex of fixture.invalid_binary64_vectors) {
  const number = Buffer.from(hex, "hex").readDoubleBE(0);
  assert.throws(() => canonicalize(number), "invalid binary64 vector " + hex);
}
process.stdout.write(
  "JCS cross-language golden fixture and RFC 8785 Appendix B vectors passed: "
  + digest + "\n"
);
