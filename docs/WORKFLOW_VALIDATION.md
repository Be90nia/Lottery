# Workflow syntax validation

The pull-request test workflow parses every checked-in workflow YAML file before running the Python suite. This catches syntax regressions in scheduled and manually dispatched workflows that are not themselves executed by pull-request events.
