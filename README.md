# tf-cost-diff

> See the $ impact of every Terraform change right in the PR, before you merge.

[![ci](https://github.com/cybercapybara/tf-cost-diff/actions/workflows/ci.yml/badge.svg)](https://github.com/cybercapybara/tf-cost-diff/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

A tiny, dependency-free GitHub Action (and CLI) that reads a `terraform plan`,
estimates the **monthly cost delta**, and posts a single sticky comment on the
pull request. Optionally fails the check when the delta crosses a threshold.

## How it works

1. Parses `terraform show -json <plan>` into create / update / destroy sets.
2. Prices cost-relevant resources with a small built-in AWS sheet (override with
   your own JSON via `--price-sheet`).
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
  - uses: cybercapybara/tf-cost-diff@v0
    with:
      plan: plan.json
      threshold: "100"      # optional: fail if Δ > $100/mo
      # price-sheet: prices.json   # optional override
```

## Price sheet override

`--price-sheet prices.json` where the file maps a Terraform resource type to a
flat monthly price:

```json
{
  "aws_instance": 42.0,
  "aws_nat_gateway": 32.85
}
```

Anything not in the built-in sheet or your override is treated as $0 and skipped.

## Development

```bash
pip install -e . pytest
pytest
```

## License

MIT
