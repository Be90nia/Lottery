# Research Methods

## Statistical framing

A standard draw selects five distinct front numbers from 35 and two distinct back numbers from 12. Tests must respect sampling without replacement within each pool.

## Descriptive analysis

Report observed counts alongside theoretical expectations and uncertainty. For each statistic, define the sampling unit, null hypothesis, test statistic, and analysis window before interpreting results.

## Simulation tests

For statistics whose exact null distribution is inconvenient, simulate complete legal draws under the null. Preserve the draw structure: five unique front numbers and two unique back numbers. Use a recorded random seed for reproducibility of the *analysis simulation*, not as a claim about the lottery's physical randomization.

## Multiple comparisons

Exploratory scans across many numbers, pairs, periods, devices, and ball sets create false positives. Report the number of tests, use an appropriate family-wise or false-discovery correction, and validate any candidate finding on a separately specified period.

## Change points and context

Rule changes, equipment changes, ball-set metadata, and documented incidents should be treated as separate candidate explanatory variables. Require authoritative provenance and sensitivity analyses. Correlation does not establish causation.

## Predictive evaluation

- Split strictly by time.
- Use rolling-origin or expanding-window evaluation.
- Compare every model with legal random baselines.
- Predeclare metrics and selection procedures.
- Keep a final chronological holdout untouched during model selection.
- Report uncertainty, calibration where applicable, and negative results.

## Anomaly discipline

An unusual result is a review signal, not evidence of manipulation. Check data quality, source revisions, the number of comparisons, and the null distribution before making claims. Do not infer a hidden PRNG seed for a physical draw without direct technical evidence.

## Reproducibility

Every experiment records dataset version/hash, code commit, configuration, random seed for computational simulation, runtime environment, metrics, and generated artifacts.


## Current Monte Carlo baseline implementation

`scripts/analyze_baseline.py` runs global front-zone and back-zone frequency diagnostics against independent legal draws. Each simulated draw selects 5 distinct values from 1..35 and 2 distinct values from 1..12; sampling is without replacement within each zone.

The reported statistics are:
- Pearson frequency-imbalance statistic for each zone;
- maximum absolute standardized deviation among all numbers in each zone;
- upper-tail Monte Carlo p-values using the plus-one correction;
- Monte Carlo standard errors and the simulation seed.

The maximum-deviation statistic is a global scan statistic: it accounts for looking across all numbers in a zone within that statistic. It does not correct for every other analysis a researcher might subsequently run. Treat any low p-value as a lead for preregistered follow-up, not as evidence of manipulation or future predictability.

Draw-level sums, odd-count, and adjacent-pair counts are reported descriptively only in this initial version. They are not yet assigned inferential p-values. The report includes the input file SHA-256 and dataset validation summary. The computational seed is solely for reproducibility of this Monte Carlo experiment; it is not a hypothesized lottery seed.
