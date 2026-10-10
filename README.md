# DeployGuard: JEV-powered PR risk prototype

A CLI prototype that sends pull-request context to TypeSafe JEV through OpenRouter's Decisions API, displays typed risk signals, and applies a small deterministic demo policy.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Add your OPENROUTER_API_KEY to .env
```

## Run

```bash
python analyze.py sample_pr_payment.json
python analyze.py sample_pr_low.json
python analyze.py sample_pr_medium.json
python analyze.py sample_pr_critical.json
```

Save raw API response if useful:

```bash
python analyze.py sample_pr_payment.json --save payment_response.json
```

## Architecture

PR state JSON -> OpenRouter Decisions API -> `~typesafe/jev-latest` -> typed `noul`/`choice`/`score` answers -> Python policy -> recommendation.

## Important prototype limitations

- The sample PRs are illustrative fixtures, not real historical PRs.
- The policy thresholds are demo rules, not empirically validated thresholds.
- A JEV probability is the model's probability for a defined question, not a universal probability that the deployment will fail.
- This prototype does not read a real Git diff, run tests, enforce GitHub branch protection, deploy, or roll back.
- Never auto-deploy/block production solely from this prototype. Validate on labelled historical PRs and keep a human approval path.
