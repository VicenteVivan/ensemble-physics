# Data dictionary

`PROLIFIC_PID` contains anonymous participant IDs such as `P001`, local to each
experiment. Trial order is zero-based; `source_record` is the one-based array
position in the source data.

## Experiment 1

**Data collection:** April–May 2025. Collected by Vicente Vivanco.

- `data.json`: the 100 analyzed participants, in posterior order.
- `all_records.json`: 121 anonymous completed records, including 13 excluded by
  the catch criterion and eight additional eligible records outside the saved sample.
- `participants.csv`: maps source records to anonymous IDs and the analyzed sample.

| Field | Meaning |
|---|---|
| `single`, `multi` | Single-marble and ensemble blocks; dictionaries of trial records |
| Trial key | Stimulus identifier and trial index; keys beginning `catch` are catch trials |
| `mass` | Comparison mass parameter; divide by the reference value 8 for the mass ratio |
| `prediction` | `Heavier` or `Lighter` response |
| `order` | Trial order within the block |
| `reaction_time` | Recorded response time in milliseconds |
| `stimuli_order` | Order of the two blocks |
| `excluded` | Stored participant exclusion flag: fewer than five correct catches overall |
| `fit_details` | Online adaptive-procedure estimates; not the offline posterior used in the paper |

Each analyzed participant contributes 57 noncatch trials per block: 11,400
responses overall. The Bayesian fit uses log mass ratios and estimates thresholds,
widths and lapses. Width is the Gaussian SD; smaller means better discrimination.
In the model, `lapse_rate` is half the full guessing probability `lapse_rate_raw`.
Population contrasts and averages of participant parameters are distinct quantities
and are separately named in `summary.csv`.

## Experiment 2

**Data collection:** June–July 2025. Collected by Vicente Vivanco.

- `data.json`: all 122 anonymous completed records, including catch trials.
- `participants.csv`: joint-catch scores, eligibility, and inclusion in the fitted sample.
- `excluded_trials.csv`: 15 excluded S1 noncatch records, identified by participant
  and trial order. `rapid` denotes 13 records identified from submission timing;
  `unresolved_CL` denotes two records with inconsistent localization scores.

Eligibility requires both S1 responses to be correct on at least four of five
catches. This retains 82 people; the first 80 in stored order enter the fit.

| Field | Meaning |
|---|---|
| `experiment1.trials` | S1: ensemble mass discrimination and change localization |
| `experiment2.trials` | S2: highlighted-item lighter/same/heavier judgment |
| `video1`, `video2` | Stimulus paths in presentation order, relative to the experiment app |
| `comparison_type` | Pairing of normal/heavier/lighter stimulus conditions |
| `prediction` | Response about the second video relative to the first |
| `grid_choice` | S1 clicked location, stored as a JSON string with `x` and `z` coordinates |
| `perception_correct` | Stored mass-response correctness, string `0` or `1` |
| `grid_choice_correct` | Stored S1 localization correctness, string `0` or `1` |
| `highlighted_cell_changed` | S2 stored changed-item flag, string `0` or `1` |
| `is_catch` | Whether the trial is a catch |
| `order` | Trial index within its section |
| `reaction_time` | Recorded milliseconds; S1 zeros indicate unavailable timing |
| `combined_total_points` | Stored task score; not used in fitting |

After cleaning, S1 has 4,385 trials. The joint outcome order is
`[both correct, localization only, mass discrimination only, neither]`, with
counts `[1810, 198, 1386, 991]`. S2 has 4,800 trials; matrix rows are truth and
columns are responses, both ordered `[lighter, same, heavier]`:

```text
1082  105   25
 295 1724  357
  24  134 1054
```

S2 truth is derived from video order and the stored changed-item flag. The fit
jointly models both sections with shared evidence SD and lapses. Its generated
mass-discrimination response gates localization. The attention count is
`min(Poisson(rate), 8)`; the evidence threshold is one. `delta` is the conditional
log-odds boost. Percentage-point boosts multiply the reported probability
difference by 100. Intervals are 95% HDIs; fit correlations are in-sample.

`summary.json` distinguishes participant-averaged raw accuracy, pooled accuracy,
predictions without lapses, and predictions including lapses. The participant
table's `observed_*` columns are raw accuracy; `model_*` columns average
lapse-adjusted predictions over all posterior draws.
