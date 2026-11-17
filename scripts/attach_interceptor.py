"""Attach the interceptor to the Gateway without losing anything else the Gateway has.

update-gateway REPLACES the whole configuration, so this reads the live Gateway first and sends it back
with the interceptor added (authorizer, policy engine, protocol and role all preserved).

    python3 scripts/attach_interceptor.py               # attach it, wait until READY, print the result

Needs REGION, GATEWAY_ID and INTERCEPTOR_ARN in the environment.
Run it again after any deploy that changes the Gateway resource itself.
"""
import json
import os
import sys
import time

import boto3

KEEP = ["name", "description", "roleArn", "protocolType", "protocolConfiguration", "authorizerType",
        "authorizerConfiguration", "policyEngineConfiguration", "exceptionLevel", "kmsKeyArn"]


def build_update(gateway, interceptor_arn):
    update = {key: gateway[key] for key in KEEP if gateway.get(key) is not None}
    update["interceptorConfigurations"] = [{
        "interceptor": {"lambda": {"arn": interceptor_arn}},
        "interceptionPoints": ["REQUEST"],
        "inputConfiguration": {"passRequestHeaders": True},  # the interceptor needs the Authorization header
    }]
    return update


def main(argv):
    client = boto3.client("bedrock-agentcore-control", region_name=os.environ["REGION"])
    gateway_id, interceptor_arn = os.environ["GATEWAY_ID"], os.environ["INTERCEPTOR_ARN"]
    update = build_update(client.get_gateway(gatewayIdentifier=gateway_id), interceptor_arn)

    client.update_gateway(gatewayIdentifier=gateway_id, **update)
    for _ in range(30):
        time.sleep(3)
        gateway = client.get_gateway(gatewayIdentifier=gateway_id)
        if gateway["status"] == "READY":
            break
    interceptors = [c["interceptor"]["lambda"]["arn"] for c in gateway.get("interceptorConfigurations", [])]
    print(json.dumps({"status": gateway["status"], "interceptors": interceptors,
                      "policy": gateway.get("policyEngineConfiguration", {}).get("mode")}, indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
