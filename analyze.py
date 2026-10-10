import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = "https://openrouter.ai/api/alpha/decisions"
MODEL = "~typesafe/jev-latest"

QUESTIONS = {
    "regression_risk": {
        "type": "noul",
        "instructions": "Is this pull request likely to introduce a production regression?",
        "criteria": {
            "true": "The change has meaningful potential to alter production behavior incorrectly.",
            "false": "The change is unlikely to introduce a production regression."
        }
    },
    "security_change": {
        "type": "noul",
        "instructions": "Does this pull request modify security-sensitive behavior?",
        "criteria": {
            "true": "The change affects authentication, authorization, credentials, access control, or other security-sensitive behavior.",
            "false": "The change does not materially affect security-sensitive behavior."
        }
    },
    "insufficient_testing": {
        "type": "noul",
        "instructions": "Is the testing evidence insufficient for the behavior changed by this pull request?",
        "criteria": {
            "true": "Testing does not adequately cover the changed behavior.",
            "false": "Testing provides adequate evidence for the changed behavior."
        }
    },
    "customer_impact": {
        "type": "noul",
        "instructions": "Could a failure in this change cause significant customer impact?",
        "criteria": {
            "true": "A failure could materially affect customers or an important production workflow.",
            "false": "A failure would have limited customer impact."
        }
    },
    "risk_area": {
        "type": "choice",
        "instructions": "What is the primary risk area introduced or affected by this pull request?",
        "criteria": {
            "security": "Authentication, authorization, credentials, access control",
            "payments": "Payments, billing, refunds, financial transactions",
            "database": "Database schema, queries, migrations, persistence",
            "infrastructure": "Cloud infrastructure, deployment, networking, configuration",
            "api": "Public APIs, contracts, integrations",
            "business_logic": "Core application or business logic",
            "ui": "User interface or presentation behavior",
            "other": "Other changes not covered above"
        }
    },
    "blast_radius": {
        "type": "score",
        "instructions": "How broad could the impact be if this pull request causes a production failure?",
        "criteria": [
            "Isolated",
            "Small",
            "Moderate",
            "Large",
            "System-wide"
        ]
    },
    "test_adequacy": {
        "type": "score",
        "instructions": "How adequate is the available testing evidence for the behavior changed by this pull request?",
        "criteria": [
            "Very poor",
            "Poor",
            "Adequate",
            "Good",
            "Excellent"
        ]
    },
    "rollback_difficulty": {
        "type": "score",
        "instructions": "How difficult would it be to safely roll back this pull request after deployment?",
        "criteria": [
            "Trivial",
            "Easy",
            "Moderate",
            "Difficult",
            "Very difficult"
        ]
    }
}


def call_jev(state):
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is missing. Add it to .env.")

    payload = {"model": MODEL, "state": state, "questions": QUESTIONS}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-OpenRouter-Title": "DeployGuard",
    }

    started = time.perf_counter()
    response = requests.post(API_URL, headers=headers, json=payload, timeout=60)
    elapsed_ms = (time.perf_counter() - started) * 1000

    if not response.ok:
        raise RuntimeError(f"OpenRouter returned HTTP {response.status_code}: {response.text}")
    return response.json(), elapsed_ms


def policy(answers):
    """Demo policy: explicit rules, not a learned/validated production policy."""
    regression = answers["regression_risk"]["noul"]
    security = answers["security_change"]["noul"]
    insufficient_testing = answers["insufficient_testing"]["noul"]
    customer_impact = answers["customer_impact"]["noul"]
    area = answers["risk_area"]["choice"]
    blast = answers["blast_radius"]["score"]

    # Fail safe for security-sensitive changes: route for review, never auto-deploy.
    if security >= 0.90:
        return "BLOCK / SECURITY REVIEW"
    if area == "security" and security >= 0.60:
        return "MANUAL SECURITY REVIEW"
    if area == "payments" and customer_impact >= 0.80 and regression >= 0.60 and blast >= 3.0:
        return "CANARY DEPLOYMENT"
    if insufficient_testing >= 0.65 and regression >= 0.60:
        return "MANUAL REVIEW"
    if regression < 0.30 and customer_impact < 0.30 and blast < 2.0:
        return "AUTO-DEPLOY CANDIDATE"
    return "MANUAL REVIEW"


def reasons(answers):
    result = []
    if answers["risk_area"]["choice"] == "payments":
        result.append("The primary risk area is payment functionality.")
    if answers["risk_area"]["choice"] == "security":
        result.append("The primary risk area is security-sensitive behavior.")
    if answers["customer_impact"]["noul"] >= 0.80:
        result.append("JEV assigns a high probability to significant customer impact.")
    if answers["blast_radius"]["score"] >= 3:
        result.append("The expected blast-radius score is large or system-wide.")
    if answers["insufficient_testing"]["noul"] >= 0.60:
        result.append("JEV flags a meaningful chance that testing evidence is insufficient.")
    if answers["regression_risk"]["noul"] >= 0.60:
        result.append("JEV assigns an elevated probability to regression risk.")
    if answers["security_change"]["noul"] >= 0.60:
        result.append("Security-sensitive behavior may be affected.")
    return result


def pct(x):
    return f"{x:.0%}"


def print_score(label, answer):
    probs = answer.get("probabilities", {})
    legend = answer.get("legend", {})
    # API uses string keys for score rubric levels.
    best_key = max(probs, key=lambda k: probs[k]) if probs else None
    best_label = legend.get(str(best_key), str(best_key)) if best_key is not None else "n/a"
    best_prob = probs.get(best_key, 0) if best_key is not None else 0
    print(f"{label:<23} {best_label.upper():<18} {best_prob:.0%} probability")
    print(f"{'':23} Expected score: {answer.get('score', 0):.2f}/4 | Confidence: {answer.get('confidence', 0):.0%}")


def print_report(data, elapsed_ms, filename):
    answers = data["answers"]
    state_title = filename
    # We only infer the title from a file name if caller passes no title in the response.
    print("\n" + "=" * 68)
    print("DEPLOYGUARD  |  JEV DEPLOYMENT RISK ANALYSIS")
    print("=" * 68)
    print(f"PR scenario: {state_title}")
    print(f"Model: {data.get('model', MODEL)} | API latency: {elapsed_ms:.0f} ms")
    print("\nRISK SIGNALS")
    print("-" * 68)
    print(f"{'Regression risk':<23} {pct(answers['regression_risk']['noul'])}")
    print(f"{'Security change':<23} {pct(answers['security_change']['noul'])}")
    print(f"{'Insufficient testing':<23} {pct(answers['insufficient_testing']['noul'])}")
    print(f"{'Significant customer impact':<23} {pct(answers['customer_impact']['noul'])}")
    area = answers["risk_area"]
    print(f"{'Primary risk area':<23} {area['choice'].upper()} | confidence {area.get('confidence', 0):.0%}")
    print()
    print_score("Blast radius", answers["blast_radius"])
    print_score("Test adequacy", answers["test_adequacy"])
    print_score("Rollback difficulty", answers["rollback_difficulty"])

    decision = policy(answers)
    print("\n" + "=" * 68)
    print(f"RECOMMENDATION: {decision}")
    print("=" * 68)
    print("WHY")
    for item in reasons(answers):
        print(f"  • {item}")
    print("\nNote: This is a prototype recommendation from demo policy rules.")
    print("It is not a validated production safety gate. Review before deployment.")
    print("=" * 68 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze a PR scenario with TypeSafe JEV via OpenRouter.")
    parser.add_argument("pr_file", help="Path to a PR state JSON file")
    parser.add_argument("--save", help="Optional path to save raw JEV response JSON")
    args = parser.parse_args()

    try:
        state = json.loads(Path(args.pr_file).read_text())
        result, elapsed_ms = call_jev(state)
        if "answers" not in result:
            raise RuntimeError(f"Unexpected API response: {json.dumps(result, indent=2)}")
        print_report(result, elapsed_ms, state.get("title", args.pr_file))
        if args.save:
            Path(args.save).write_text(json.dumps(result, indent=2))
            print(f"Raw response saved to {args.save}")
    except (OSError, json.JSONDecodeError, requests.RequestException, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
