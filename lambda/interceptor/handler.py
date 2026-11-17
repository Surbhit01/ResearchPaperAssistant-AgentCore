import base64
import json


def _sub_from_header(auth_header):
    # Gateway has ALREADY validated this JWT (signature, issuer, client, expiry)
    # before invoking us, so we only read the payload here. Never log the token.
    token = auth_header.split(" ", 1)[-1]
    payload = token.split(".")[1]
    payload += "=" * (-len(payload) % 4)
    return json.loads(base64.urlsafe_b64decode(payload))["sub"]


def _reject(request_id, message):
    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayResponse": {
            "statusCode": 403,
            "body": {"jsonrpc": "2.0", "id": request_id,
                     "error": {"code": -32001, "message": message}},
        }},
    }


def lambda_handler(event, context):
    request = event["mcp"]["gatewayRequest"]
    body = request["body"]
    # tools/list -> List all tools available to the model (No additional param required)
    # tools/call -> Call a tool with the provided arguments (Requires arguments param and tool name)
    if body.get("method") == "tools/call":
        headers = {k.lower(): v for k, v in request.get("headers", {}).items()}
        try:
            sub = _sub_from_header(headers["authorization"])
        except (KeyError, IndexError, ValueError):
            return _reject(body.get("id"), "caller identity unavailable")
        args = body.setdefault("params", {}).setdefault("arguments", {})
        args["_caller"] = {"user_id": sub}      # overwrites anything the model sent

    return {
        "interceptorOutputVersion": "1.0",
        "mcp": {"transformedGatewayRequest": {"body": body}},
    }
