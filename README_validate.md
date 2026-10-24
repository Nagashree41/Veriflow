# README — `validate.py` (VeriFlow, Person 2)

**VeriFlow — Evidence Before Alarm**
This module checks **sensor reliability before the incident detection system
makes decisions**. It turns raw readings into per-site/per-sensor data-quality
results. It does **not** classify incidents, score confidence, or decide
whether water is safe.

---

## 1. Files in this module

| File | Purpose |
|---|---|
| `validate.py` | The module: checks, reliability scoring, CSV outputs, importable API |
| `test_validate.py` | `unittest` suite (30 tests), synthetic data only, explicit expected values |
| `make_synthetic_data.py` | Generates `synthetic_readings.csv` (the team simulator was not in the project folder yet) |
| `synthetic_readings.csv` | Generated test dataset — **synthetic fixtures, not real measurements** |
| `sensor_reliability.csv` | Output 1: one score row per site × sensor |
| `validated_readings.csv` | Output 2: original rows + per-sensor reliability score/status |
| `.venv/` | Local virtual environment (pandas + numpy), created for this project |

---

## 2. Setup and commands (Windows PowerShell)

Run from the project folder:

```powershell
# one-time setup
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install pandas numpy

# if PowerShell blocks activation (execution policy), use this instead of activating:
#   Set-ExecutionPolicy -Scope Process RemoteSigned
# or call the venv interpreter directly:
#   .\.venv\Scripts\python.exe -m pip install pandas numpy

# generate the synthetic dataset (only needed once, or to regenerate it)
python make_synthetic_data.py

# run the validation -> writes sensor_reliability.csv + validated_readings.csv
python validate.py --input synthetic_readings.csv --output-dir .

# run the tests
python -m unittest -v test_validate
```

Expected test result: `Ran 30 tests ... OK`.

When Person 1's simulator CSV exists:

```powershell
python validate.py --input <their_file>.csv --output-dir results
```

The input file is **only ever read**. The module never modifies it and
refuses to write an output file onto the input path (covered by a test).

---

## 3. Input format

CSV, one row per reading, one site per `site_id`.

| Column | Required? | Meaning |
|---|---|---|
| `ph` | at least one of the 4 sensor columns must exist | pH |
| `turbidity` | ″ | turbidity (NTU) |
| `tds` | ″ | total dissolved solids |
| `chlorine` | ‵ | residual chlorine |
| `timestamp` | optional | if present, rows are sorted by it to pick the *latest* window; ISO-style strings work |
| `site_id` | optional | grouping key; if absent, the whole file is treated as one site `site_00` |
| `label` | optional | simulator ground truth; **passed through untouched, never used for scoring** |

Graceful handling: unparseable text in a sensor column (`"ERR"`, empty cell)
counts as **missing**; empty file (header only) produces header-only outputs;
a file with no sensor columns or a missing file raises a clear `ValueError` /
`FileNotFoundError`.

---

## 4. Configuration (one section, edit in `validate.py`)

All tunable numbers live together at the top of `validate.py` in `CONFIG`:

| Key | Default | Meaning |
|---|---|---|
| `window` | `24` | readings per site inspected (latest N) |
| `weights` | `missing 0.6, impossible 0.6, stuck 0.6, spike 0.3` | **provisional** penalty weights — team to retune after testing |
| `stuck_min_run` | `8` | ≥ 8 consecutive identical valid readings ⇒ stuck |
| `stuck_tolerance` | `0.0` | allowed absolute difference between "identical" values |
| `spike_robust_k` | `4.0` | jump must exceed 4 × robust std of the window |
| `unreliable_below` | `0.5` | sensor is unreliable when `R < 0.5` |
| `sensors` (=`SENSOR_BOUNDS`) | see below | per-sensor bounds and spike thresholds |

| Sensor | min | max | `spike_jump` (unit) | `spike_return` (unit) |
|---|---|---|---|---|
| `ph` | 0 | 14 (physical) | 1.0 pH | 0.5 pH |
| `turbidity` | 0 | 1000 NTU (**placeholder** measurement range) | 50 NTU | 10 NTU |
| `tds` | 0 | 5000 (**placeholder**) | 500 | 100 |
| `chlorine` | 0 | 10 mg/L (**placeholder**) | 2.0 mg/L | 0.5 mg/L |

---

## 5. The four checks and their limitations

For each site, each sensor, over the **latest 24 readings**:

1. **Missing values** — cells that are empty or unparseable.
   *Limitation:* only shows the data is absent, not *why* (comms dropout,
   power, maintenance). A gap is not proof the sensor is broken.
2. **Impossible values** — outside the configured per-sensor bounds.
   *Limitation:* depends entirely on the configured bounds (placeholders until
   confirmed against the real probe specs); a *plausible but wrong* value
   (biased, drifted) is never caught.
3. **Stuck** — the same **valid** value repeats for ≥ 8 consecutive readings.
   *Limitation:* legitimately constant / heavily quantised sensors can
   false-positive (raise `stuck_min_run` or `stuck_tolerance` for them); a
   slowly drifting frozen sensor is not caught; the 8-reading threshold is a
   hard cliff, not a graded measure.
4. **Spike** — a reading jumps ≥ `max(spike_jump, 4 × robust std)` away from
   the window median baseline, coming from near the baseline and returning
   within `spike_return` at the **next** reading.
   *Limitation:* a jump at the very end of the window is not yet confirmable;
   a sustained shift to a new level is intentionally **not** a spike (that may
   be a real water event for Person 3 to judge); a real contamination pulse
   can also look like a spike — a spike is a property of the *signal shape*,
   never proof of a fault.

**No double-counting:** every reading belongs to at most one category —
missing values are never also "impossible", and stuck/spike detection only
looks at present, in-bounds readings, so a run of `pH = 20` counts as
*impossible* only, never also *stuck* or *spike* (tested).

---

## 6. Reliability score

Per sensor, with `n` = readings actually in the (possibly shorter) window:

```
penalty_missing    = 0.6 * (missing_count    / n)
penalty_impossible = 0.6 * (impossible_count / n)
penalty_stuck      = 0.6 * 1 if stuck else 0        # boolean flag
penalty_spike      = 0.3 * (spike_count      / n)

penalty     = min(1, sum of the four)          # each capped by its weight
R           = 1 - min(1, penalty)              # always within [0, 1]
unreliable  = True  <=>  R < 0.5               # strict, on the reported R
```

Reported `penalty` and `reliability` are rounded to 6 decimals.
Worked examples (window 24): 6 missing → R = 0.85; all missing → R = 0.4;
4 × pH 20 → R = 0.9; stuck → R = 0.4; one spike → R = 0.9875; 8 stuck +
8 missing + 8 impossible → R = 0.0. All verified by tests.

---

## 7. Output files

### `sensor_reliability.csv`

Exactly: `site_id, sensor, missing_count, impossible_count, stuck, spike_count,
penalty, reliability, unreliable` — one row per site × sensor (e.g. 8 sites →
32 rows).

### `validated_readings.csv`

All original columns and row order preserved, plus per sensor appended:
`ph_reliability`, `ph_status`, `turbidity_reliability`, `turbidity_status`,
`tds_reliability`, `tds_status`, `chlorine_reliability`, `chlorine_status`.
`*_status` is `investigate` exactly when that sensor's R < 0.5, else `reliable`.

> **Retrospective window (please quote this honestly):** each site's score is
> computed from that site's **latest 24 readings** and then attached to every
> row of that site in `validated_readings.csv`. This is a **retrospective
> window evaluation**, **not** a fully real-time rolling per-timestep
> evaluation, and no future readings beyond the latest row are used.

---

## 8. Integration with Person 3

```python
from validate import inspect_sensor, validate_csv

# one sensor, latest 24 of the values you pass (chronological order, oldest first)
result = inspect_sensor(latest_ph_values, "ph")
# {'sensor': 'ph', 'missing_count': 0, 'impossible_count': 0, 'stuck': False,
#  'spike_count': 0, 'penalty': 0.0, 'reliability': 1.0, 'unreliable': False,
#  'window_used': 24}

# or validate a whole CSV (writes both files, returns both dataframes)
reliability_df, validated_df = validate_csv("sensor_readings.csv", output_dir="results")
```

Interpretation contract (agreed scope):

- Low reliability ⇒ **flag the sensor for investigation only.**
  It must never, by itself, make the system declare water unsafe.
- A **reliable** sensor with an abnormal reading does not automatically prove
  contamination — that judgement is Person 3's classifier, using this module's
  data-quality results as one input among others.
- This module supplies **data-quality results only** — no incident class, no
  confidence score.

---

## 9. Running the tests

```powershell
python -m unittest -v test_validate
```

Covers: normal readings; missing values; impossible pH = 20; ≥ 8 consecutive
identical readings (and the 7-reading boundary); spike with return to
baseline (and without return); empty input; insufficient history; every score
in [0, 1]; `unreliable == (R < 0.5)` including the exact R = 0.5 boundary;
exact output columns; grouping by site and sensor; window selection by
timestamp; input file left untouched. Synthetic data only.

---

## 10. Assumptions to confirm with Person 1 / Person 3

1. **Window**: 24 readings ≈ last 2 hours at 5-minute cadence — confirm that
   is the intended look-back (Person 1).
2. **CSV shape**: one row per reading, one `site_id` per site, timestamps
   sortable/ISO and rows per site not duplicated (Person 1).
3. **Bounds**: turbidity ≤ 1000 NTU, TDS ≤ 5000, chlorine ≤ 10 mg/L are
   placeholders — replace with the actual probe specs; pH 0–14 is physical
   (Person 1 / hardware).
4. **Weights** `0.6 / 0.6 / 0.6 / 0.3` and threshold `R < 0.5` are
   provisional — the whole team retunes them after testing (all of us).
5. **Stuck rule**: exactly-repeating values, run ≥ 8, exact match tolerance 0 —
   confirm the real sensors' rounding won't false-positive (Person 1).
6. **Site-level broadcast**: one score per site (latest window) is attached to
   all of that site's rows; Person 3 must present it as retrospective, not as
   a real-time per-reading score (Person 3).
7. **`label` column** is ignored here — it is ground truth for later
   evaluation, not for scoring (Person 1/3).
8. **Integration contract** in section 8 — Person 3 confirms how reliability
   will and will not feed the incident decision.

## 11. Honesty note

`synthetic_readings.csv` contains **made-up fixture numbers** generated to
exercise the code. Passing tests prove the *code behaves as specified*; they
say **nothing** about real water quality or field safety. No output of this
module should ever be presented as a real-world safety claim.
