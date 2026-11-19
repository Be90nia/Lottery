# Workflow syntax validation

The pull-request test workflow parses every checked-in workflow YAML file before running the Python suite. This catches syntax regressions in scheduled and manually dispatched workflows that are not themselves executed by pull-request events.

The append-only publisher also re-parses every referenced raw page and validates its sidecar against the exact candidate draw inventory before it can create an output.

The publication tests exercise exact official-page parsing from raw snapshot fixtures, not only manifest-hash comparisons.
