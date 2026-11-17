
"""Check that the Gateway is READY, has the interceptor, and shows its policy mode. Exits 1 if the interceptor is missing.

    python3 scripts/check_gateway.py

Run it after every deploy. Needs REGION and GATEWAY_ID in the environment.
"""
import os
import sys

import boto3


def summarise(gateway):
    interceptors = [c["interceptor"]["lambda"]["arn"].split(":")[-1] for c in gateway.get("interceptorConfigurations") or []]
    return {"status": gateway["status"], "interceptors": interceptors,
            "policy_mode": (gateway.get("policyEngineConfiguration") or {}).get("mode")}


if __name__ == "__main__":
    gateway = boto3.client("bedrock-agentcore-control", region_name=os.environ["REGION"]).get_gateway(
        gatewayIdentifier=os.environ["GATEWAY_ID"])
    summary = summarise(gateway)
    print(f"status={summary['status']}  interceptors={summary['interceptors'] or 'NONE'}  policy_mode={summary['policy_mode'] or 'NONE'}")
    if not summary["interceptors"]:
        sys.exit("INTERCEPTOR MISSING: run  python3 scripts/attach_interceptor.py")
