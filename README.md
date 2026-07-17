# tf-cost-diff

> See the $ impact of every Terraform change right in the PR, before you merge.

**Status:** 🚧 In development

## Overview

GitHub Action that comments an estimated monthly cost delta from a terraform plan onto the pull request.

## Features

- Parse `terraform show -json plan` output into resource create/update/delete sets
- Estimate monthly cost delta using a pluggable pricing source (static AWS price sheet by default)
- Post/update a single sticky PR comment with a per-resource cost table and total Δ$/mo
- Fail the check (optional) when the delta exceeds a configurable threshold
- Ship as a composite GitHub Action with `action.yml` and a Docker entrypoint

## Stack

Python 3.11, GitHub Actions (composite + Docker), Terraform JSON plan, AWS pricing data.

## Usage

```bash
terraform plan -out tf.plan
terraform show -json tf.plan > plan.json
python -m tf_cost_diff --plan plan.json --threshold 50
```

## License

MIT
