# tf-cost-diff

> See the $ impact of every Terraform change right in the PR, before you merge.

[![ci](https://github.com/moveeeax/tf-cost-diff/actions/workflows/ci.yml/badge.svg)](https://github.com/moveeeax/tf-cost-diff/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

A tiny, dependency-free GitHub Action (and CLI) that reads a `terraform plan`,
estimates the **monthly cost delta**, and posts a single sticky comment on the
pull request. Optionally fails the check when the delta crosses a threshold.

## How it works

1. Parses `terraform show -json <plan>` into create / update / destroy sets.
   Input that is not plan JSON — state output, a truncated download — is
   **rejected**, never reported as "no changes".
2. Prices cost-relevant resources with a small built-in AWS sheet (override with
   your own JSON via `--price-sheet`). A resource whose cost cannot be
   determined is reported as **unknown**, never counted as $0.
3. Renders a Markdown table and upserts one sticky PR comment.

## CLI

```bash
pip install tf-cost-diff

terraform plan -out tf.plan
terraform show -json tf.plan > plan.json

tf-cost-diff --plan plan.json --threshold 50
```

Example output:

```
### 💸 Terraform monthly cost estimate: +$97.96/mo
`2 to create · 1 to change · 1 to destroy`

| Resource             | Action    | Before | After  | Δ/mo    |
| -------------------- | --------- | -----: | -----: | ------: |
| aws_instance.web     | 🟢 create | $0.00  | $60.74 | +$60.74 |
| aws_db_instance.main | 🟡 update | $24.82 | $49.64 | +$24.82 |
| aws_ebs_volume.data  | 🟢 create | $0.00  | $16.00 | +$16.00 |
| aws_eip.old          | 🔴 delete | $3.60  | $0.00  | -$3.60  |
```

## GitHub Action

```yaml
permissions:
  pull-requests: write
steps:
  - uses: hashicorp/setup-terraform@v3
  - run: |
      terraform plan -out tf.plan
      terraform show -json tf.plan > plan.json
  - uses: moveeeax/tf-cost-diff@v0
    id: cost
    with:
      plan: plan.json       # relative to the workspace
      threshold: "100"      # optional: fail if Δ > $100/mo
      # price-sheet: prices.json   # optional override
```

### Outputs

Every figure the tool computes is readable by later steps. They are written
*before* the threshold gate is applied, so they are still available on the run
where the gate fails — use `if: always()` to read them there.

| Output | Example | Meaning |
| --- | --- | --- |
| `total-delta` | `97.96` | Monthly delta in dollars (negative when the plan saves money). |
| `created` / `updated` / `destroyed` | `2` / `1` / `1` | Cost-relevant resource counts. |
| `unpriced` | `0` | Resources excluded from the total because their cost is unknown. |
| `complete` | `true` | `false` when `unpriced > 0`, i.e. the total is a partial figure. |
| `threshold-exceeded` | `false` | Whether the delta crossed `threshold`. |
| `comment-url` | `https://github.com/...` | The sticky comment, empty if none was posted. |

```yaml
  - if: always() && steps.cost.outputs.complete == 'false'
    run: echo "::warning::${{ steps.cost.outputs.unpriced }} resources could not be priced"
```

### Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | The delta exceeded `--threshold`. |
| `2` | Bad input: not a Terraform plan, unreadable file, or an invalid price sheet. |

Posting the comment is best effort: a pull request from a fork gets a read-only
`GITHUB_TOKEN`, so the comment is skipped with a warning rather than failing the
run. The threshold gate still applies.

## Unknown costs

The built-in sheet covers a handful of resource types and a handful of instance
sizes within them. Anything outside that is treated as **unknown**, not free:

- A resource type with no price model (IAM roles, security groups) is excluded
  from the estimate silently — the comment carries a standing caveat.
- A *modelled* type the sheet cannot price for this configuration — an
  unrecognised `instance_type`, or a size that is not known until apply — is
  listed in a separate "Cost unknown" table, excluded from the total, and the
  headline is marked `(partial)`.

This matters for the threshold gate: guessing a rate for an unrecognised
`m5.24xlarge` would report ~$36/mo for a resource that really costs over
$3,000/mo, and it would sail straight through `threshold: 100`.

## Price sheet override

`--price-sheet prices.json` where the file maps a Terraform resource type to a
flat monthly price:

```json
{
  "aws_instance": 42.0,
  "aws_nat_gateway": 32.85
}
```

Values must be finite, non-negative numbers; anything else is rejected with exit
code `2` rather than silently producing a nonsense total.

## Development

```bash
pip install -e '.[dev]'
pytest
```

## License

MIT
