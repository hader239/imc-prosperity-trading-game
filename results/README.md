# Results — written-up findings

Markdown notes that distill what a notebook found. The traders in
[`../src/`](../src/) cite these by filename, so the convention is
load-bearing:

```
results/findings_<product_or_topic>.md
```

Examples of names you might use:

- `findings_tomatoes.md` — fair-value estimator comparison for TOMATOES.
- `findings_velvetfruit_extract.md` — fair-value + inventory skew
  parameters for VELVETFRUIT_EXTRACT.
- `findings_voucher_iv_smile.md` — IV smile fit for the VEV vouchers.

## What goes in a findings doc

Three sections is enough:

1. **Question** — what you were trying to figure out, in one sentence.
2. **Analysis** — the actual numbers + which notebook they came from.
   Link the notebook (`../notebooks/<file>.py`) so the trail is
   reproducible.
3. **Decision** — the parameter / strategy choice the trader will use,
   in one paragraph. Numbered if multiple knobs.

If a finding gets invalidated by later analysis, leave the original
note in place and add a dated update at the bottom — don't delete it.
The traders may still cite the old number.
