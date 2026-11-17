"""Give the Runtime the guardrail settings: two environment variables and the ApplyGuardrail permission file.

    python3 scripts/set_runtime_guardrail.py

Edits $PROJECT/agentcore/agentcore.json (needs GUARDRAIL_ID and GUARDRAIL_VERSION in the environment),
keeping everything else in the file. The project has one runtime; it is found by itself. Run `agentcore validate` afterwards.
"""
import json
import os
import sys

CONFIG = os.path.join(os.environ.get("PROJECT", "PaperAssistantDemo"), "agentcore", "agentcore.json")
POLICY_FILE = "policies/allow_guardrails.json"   # relative to the agent's code folder


def apply(config, guardrail_id, version, runtime=None):
    matches = [r for r in config["runtimes"] if runtime in (None, r["name"])]
    if len(matches) != 1:
        raise SystemExit(f"expected one runtime{' named ' + runtime if runtime else ''}, found {len(matches)}")
    rt = matches[0]
    env = [e for e in rt.get("envVars", []) if e["name"] not in ("GUARDRAIL_ID", "GUARDRAIL_VERSION")]
    rt["envVars"] = env + [{"name": "GUARDRAIL_ID", "value": guardrail_id}, {"name": "GUARDRAIL_VERSION", "value": version}]
    policies = rt.get("additionalPolicies", [])
    rt["additionalPolicies"] = policies + ([POLICY_FILE] if POLICY_FILE not in policies else [])
    return config


if __name__ == "__main__":
    gid, version = os.environ.get("GUARDRAIL_ID"), os.environ.get("GUARDRAIL_VERSION")
    if not gid or not version:
        sys.exit("set GUARDRAIL_ID and GUARDRAIL_VERSION first")
    with open(CONFIG) as f:
        config = json.load(f)
    with open(CONFIG, "w") as f:
        updated = apply(config, gid, version)
        json.dump(updated, f, indent=2)
        f.write("\n")
    print(f"runtime {updated['runtimes'][0]['name']} now has GUARDRAIL_ID, GUARDRAIL_VERSION and {POLICY_FILE}")
