# Initial frequency baseline results

**Status:** exploratory signal requiring source and equipment investigation. Not a prediction result.

## Dataset and reproducibility

- Dataset: `data/candidates/legacy_draws.jsonl`
- Draw count: 2,901
- Coverage: 07001 (2007-05-30) through 26083 (2026-07-25)
- Dataset SHA-256: `22cdd8aef049ee714020d3f5272b712cfef14da7fa7f276394ed8a1575901515`
- Full-period Monte Carlo simulations: 9,999
- Full-period seed: `20261118`
- Era simulations: 1,999 per era
- Era base seed: `20261118`; each era uses base seed + starting calendar year
- Routine CI uses smaller smoke-test simulation counts; the figures below come from the dedicated higher-count Actions runs.

The null independently generates each draw by sampling five distinct front numbers from 1..35 and two distinct back numbers from 1..12. Sampling is without replacement within each zone. The computational random seed is for reproducibility of these simulations only; it is not a hypothesized seed used by the real lottery.

## Full-period results

| Statistic | Front | Back |
|---|---:|---:|
| Pearson frequency imbalance | 90.217 | 10.393 |
| Upper-tail Monte Carlo p | 0.0001 | 0.4145 |
| Maximum absolute standardized deviation | 4.381 | 1.719 |
| Upper-tail Monte Carlo p | 0.0006 | 0.6677 |

The front Pearson statistic had zero exceedances in 9,999 simulations; 0.0001 is the plus-one Monte Carlo resolution floor, not a claim that the exact tail probability equals 0.0001. The front maximum-deviation statistic had five exceedances.

Applying Holm correction across the four full-period statistics gives adjusted p-values:
- Front Pearson: 0.0004
- Front maximum deviation: 0.0018
- Back Pearson: 0.829
- Back maximum deviation: 0.829

This supports a global front-zone frequency imbalance under the stated uniform independent-draw null. It does not identify a cause.

## Exploratory calendar-era analysis

The full-period signal was followed by an exploratory split into fixed five-calendar-year bins. This split was chosen after seeing the full-period result, so it is not a preregistered confirmatory test. Holm correction below covers the 16 statistics in this era report, but cannot correct for every possible post-hoc window or analysis choice.

| Calendar period | Draws | Front Pearson p | Front max-deviation p | Back Pearson p | Back max-deviation p |
|---|---:|---:|---:|---:|---:|
| 2007–2011 | 707 | 0.0005 | 0.0005 | 0.3225 | 0.0545 |
| 2012–2016 | 768 | 0.0015 | 0.0025 | 0.2425 | 0.5190 |
| 2017–2021 | 741 | 0.7220 | 0.9365 | 0.2880 | 0.6760 |
| 2022–2026 | 685 | 0.7695 | 0.7920 | 0.3875 | 0.5030 |

After Holm correction across all 16 era × statistic tests:
- 2007–2011 front Pearson and maximum-deviation tests: 0.008 each
- 2012–2016 front Pearson: 0.021
- 2012–2016 front maximum-deviation: 0.0325
- All other tests: at least 0.654

The observed concentration is therefore in the first two calendar bins; the later two bins do not show a comparable marginal frequency signal under this analysis. This is a hypothesis-generating temporal pattern, not proof that an equipment change caused it.



### Era-level descriptive extremes

| Calendar period | Highest counts | Lowest counts |
|---|---|---|
| 2007–2011 | 33: 157; 32: 147; 35: 146 | 16: 67; 15: 72; 4: 73 |
| 2012–2016 | 29: 151; 35: 137; 30: 134 | 16: 86; 4: 89; 19/24: 96 |
| 2017–2021 | 1: 123; 3: 122; 19: 121 | 24: 89; 31: 90; 13: 93 |
| 2022–2026 | 2: 113; 5: 111; 22: 110 | 24: 79; 14: 81; 33: 86 |

The 2007–2016 concentration of high counts for 29, 32, 33, and 35 and low counts for 16 and 4 is a useful lead for stratified investigation. These are post-hoc descriptive rankings, not evidence that these numbers have any future advantage.

## Descriptive front-number extremes

Across the full 2,901-draw candidate:
- Most frequent front number: 29 (497 appearances)
- Next most frequent: 33 (481), 35 (478)
- Least frequent: 16 (354), 24 (368), 15 (378)

These rankings are descriptive. They are not candidate numbers for the next draw. Selecting "hot" or "cold" numbers from this same history would be post-hoc fitting.

## Interpretation and next tests

1. The independent CSV comparison found exact agreement for all 2,901 overlapping draw dates and selected-number fields. This reduces the likelihood that the front-frequency pattern is caused by an isolated typo in the legacy file, but it does not validate all metadata or prove that either source is authoritative.
2. The calendar-era pattern makes equipment, ball-set, and process changes important candidate stratifiers. Do not infer the cause from calendar boundaries alone.
3. Obtain official evidence for equipment/ball-set assignments and exact effective dates before testing those factors.
4. Re-run the analysis using verified equipment and ball-set strata, with a predeclared hypothesis and family-wise correction.
5. Extend the canonical candidate to at least issue 26131 and reconcile official raw source responses before confirmatory analysis.
6. Keep all number-frequency findings separate from prediction. No evidence here demonstrates out-of-sample forecasting advantage.

## Reproduction commands

```bash
python scripts/reconcile_sources.py
python scripts/analyze_baseline.py data/candidates/legacy_draws.jsonl --simulations 9999 --seed 20261118
python scripts/analyze_eras.py data/candidates/legacy_draws.jsonl --simulations 1999 --seed 20261118
```

The Actions artifacts for the full-period and era runs are retained for 30 days. The analysis scripts and input hash are committed in the repository.
