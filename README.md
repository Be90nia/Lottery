# Lottery Research

一个面向中国体育彩票超级大乐透的可复现数据工程与统计研究项目。

目标是建立可信的历史数据资产、可审计的数据处理流程、严谨的统计检验与透明的模型评估体系。本项目不承诺预测中奖号码，也不将随机波动解释为可利用规律。

## 原则

1. **来源可追溯**：原始数据只追加、不静默覆盖；记录来源、抓取时间、原始响应哈希和数据版本。
2. **处理可复现**：清洗、校验、特征构建和实验由版本化代码与配置驱动。
3. **时间隔离**：训练、验证、测试按开奖时间顺序切分，禁止未来信息泄漏。
4. **基线优先**：所有预测实验必须与符合开奖规则的随机基线比较。
5. **结论克制**：历史频率、冷热号、设备/球组相关性和异常检测结果不等于未来预测优势。
6. **规则版本化**：基本投注、追加投注、奖级和派奖规则按生效期配置。

## 项目状态

仓库已建立基础采集、校验、奖级审计和 Monte Carlo 随机基线。旧项目的 2,901 期数据已导入为候选集，但官方原始数据核验尚未完成，不能作为可信训练集。

## 研究范围

- 历史开奖数据采集与校验
- 数据清洗、规范化和版本管理
- 号码分布、频率、间隔、共现与序列统计
- 规则时期、摇奖设备、球组及公开事件的分层分析
- 异常检测与稳健性检验
- 时间序列回测、随机基线和模型实验
- 奖金规则与历史派奖数据核算（独立于号码预测）

## 标准工作流

`fetch -> validate -> normalize -> build-dataset -> analyze -> backtest`

## 文档

- [路线图](ROADMAP.md)
- [架构设计](docs/ARCHITECTURE.md)
- [数据规范](docs/DATA_SPEC.md)
- [研究方法](docs/RESEARCH_METHODS.md)
- [奖金规则时期](docs/PRIZE_RULE_ERAS.md)
- [初步随机基线结果](docs/BASELINE_RESULTS.md)
- [任务清单](TASKS.md)
- [测试计划](TEST_PLAN.md)

## 重要声明

超级大乐透开奖结果由正式开奖规则产生。历史数据分析不能证明下一期号码可被准确预测。任何模型都必须报告样本外结果、随机基线差异、不确定性和失败案例。请理性购彩，不要将模型输出视为投资建议。

## Run the data collector

Python 3.10+ is sufficient; the initial collector uses only the standard library.

```bash
python scripts/fetch_history.py --max-pages 2
python scripts/fetch_history.py --snapshots-dir data/raw/user-supplied --require-manifests --output data/processed/from-snapshots.jsonl
python scripts/validate_dataset.py
python scripts/validate_legacy_prizes.py
python scripts/reconcile_sources.py
python scripts/analyze_baseline.py data/candidates/legacy_draws.jsonl --simulations 999 --seed 20261118
python -m unittest discover -s tests -v
```

Remove `--max-pages 2` to request all available pages. The collector writes immutable raw page snapshots and SHA-256 manifests under `data/raw/sporttery/`, then writes normalized JSON Lines to `data/processed/draws.jsonl`. Generated datasets are intentionally ignored by Git until provenance and completeness have been reviewed.

The live endpoint has not yet passed this repository's end-to-end verification. See [source notes](docs/SOURCES.md) before treating fetched records as a trusted research dataset. If an authorized party supplies raw JSON response snapshots, they can be imported offline with `--snapshots-dir`; use `--require-manifests` to require matching per-file SHA-256 sidecars with the exact Sporttery API endpoint, timezone-aware retrieval timestamp, HTTP 200, and matching raw filename. This checks consistency of supplied metadata, not cryptographic source authenticity or uncertain field semantics.

## Legacy historical candidate data

An existing 2,901-draw dataset from the earlier `dlt-analysis` project has been imported under `data/candidates/`. It is explicitly marked **unverified candidate data**, not a trusted training dataset. Its structure and cleaning-script defects are documented in [the legacy data audit](docs/LEGACY_DATA_AUDIT.md). Do not use its promotion, prize, sales, or equipment fields as ground truth until they are reconciled with immutable official source snapshots.


Monte Carlo frequency baseline details are documented in [research methods](docs/RESEARCH_METHODS.md). The baseline uses legal draws without replacement within each number zone and reports global frequency diagnostics; it does not produce a predictive number ranking.


The preserved independent comparison snapshot is `data/candidates/pickwise_dlt.csv`. Its provenance, comparison scope, and limitations are described in [source notes](docs/SOURCES.md); it is not silently merged into the legacy candidate.

### Model regression receipts (LOT-073)

Build a deterministic paired evaluation receipt from a chronological per-target score file, comparing a candidate against both the champion and uniform baseline. The gate requires front/back Brier and log-loss confidence intervals to show improvement against both references; even a pass is human-review-only and cannot promote or serve a model. See [model regression receipt protocol](docs/MODEL_REGRESSION_RECEIPTS.md).

### Prospective forecast logging

Before an eligible future draw, the fixed marginal models can be recorded with
a pre-draw timestamp, target draw ID/time, training dataset SHA-256, full code
commit, model parameters, and a hash-chained ledger event:

```bash
python scripts/forecast_ledger.py create data/canonical/draws.jsonl \
  --target-draw-id 27XXX \
  --target-draw-at 2027-01-01T20:30:00+08:00 \
  --code-commit <40-character-commit-sha>
python scripts/forecast_ledger.py verify data/holdout/forecast-ledger.jsonl
```

The ledger is not a digital signature or proof of source authenticity. See
[the prospective holdout protocol](docs/HOLDOUT_PREREGISTRATION.md) for
eligibility, archival, and analysis rules. The prospective test has not started.


### Post-draw outcome capture and scoring

After a result is officially published and its raw response snapshot is
captured, `scripts/outcome_ledger.py` can append a separately hash-chained
outcome event linked to the pre-draw forecast event. It checks the submitted
official-domain URL, HTTP status, timestamp ordering, result number ranges,
and hashes the exact snapshot bytes. It never fetches results itself and never
modifies the forecast ledger.

```bash
python scripts/outcome_ledger.py record --forecasts data/holdout/forecast-ledger.jsonl \
  --outcomes data/holdout/outcome-ledger.jsonl --target-draw-id 27XXX \
  --published-at 2027-01-01T20:40:00+08:00 --captured-at 2027-01-01T20:41:00+08:00 \
  --source-url https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry \
  --snapshot data/raw/sporttery/official-response.json --http-status 200 \
  --front 1,2,3,4,5 --back 1,2
python scripts/outcome_ledger.py score --forecasts data/holdout/forecast-ledger.jsonl \
  --outcomes data/holdout/outcome-ledger.jsonl
```

This is instrumentation, not evidence of predictive skill. The prospective
500-draw holdout has not started; do not use interim scores to select or tune
models. Metadata checks and hashes are not digital authentication.


### Ledger writer coordination (LOT-048)

Forecast and outcome appends now use a persistent sibling `.lock` file and an
OS advisory lock. The lock covers chain verification, duplicate-target checks,
sequence/hash construction, and append+flush+fsync as one transaction. POSIX
uses `flock`; Windows uses a one-byte `msvcrt.locking` region. Both paths use
a 30-second acquisition timeout. The OS releases the lock when a process exits,
including abnormal termination; the lock file itself is intentionally retained.

Do not delete or replace a ledger's `.lock` file while writers may be active:
doing so can split contenders across different lock inodes. All writers must
cooperate with this locking protocol. Advisory-lock guarantees on network,
cloud-synced, and unusual filesystems vary; use a local filesystem for the
active ledger and independently archive ledger heads. This mechanism prevents
cooperating local processes from racing; it is not a distributed transaction
or protection against a malicious writer.

### Pair co-occurrence diagnostics

Run all 595 front-zone and 66 back-zone pair tests under the legal uniform-draw
null, with one Holm correction family across all 661 hypotheses:

```bash
python scripts/analyze_pairs.py data/candidates/legacy_draws.jsonl \
  --output pair-cooccurrence.json
```

See [pair co-occurrence methodology](docs/PAIR_COOCCURRENCE.md). These are
exploratory discrepancy diagnostics, not prediction features or evidence of
manipulation; the binomial null assumes independence across draws.

### Chronological train/validation/test splits

```bash
python scripts/split_dataset.py data/candidates/legacy_draws.jsonl \
  --output-dir data/splits/legacy-70-15-15
```

This deterministic utility keeps every draw date intact and records input/output
hashes and partition boundaries. It is for exploratory development only; it
does not replace rolling-origin evaluation or the untouched prospective
500-draw holdout. See [split methodology](docs/CHRONOLOGICAL_SPLITS.md).

### Versioned prize rules

Use the effective draw ID to select the correct historical prize ruleset:

```python
from lottery.rules import ruleset_for_draw

rules = ruleset_for_draw("26014")
tier = rules.tier_for_hits(front_hits=4, back_hits=2)
```

The registry supports the reconstructed eight-tier 2007 launch rules (07001–09120), eight-tier 2009/2013 rules (09121–14051), six-tier 2014 rules (14052–19018), nine-tier 2019 rules (19019–26013), and seven-tier 2026 rules (26014 onward). The launch-era source-quality caveat is documented; floating awards and promotion overlays are not calculated. See [versioned prize rules](docs/PRIZE_RULES.md).

### Prize row reconciliation

Audit base awards, additional bets, and promotion overlays without rewriting
the original candidate values:

```bash
python scripts/validate_legacy_prizes.py --output prize-reconciliation.json
```

See [prize reconciliation methodology](docs/PRIZE_RECONCILIATION.md). The
report is exploratory until raw official prize snapshots are independently
verified.
