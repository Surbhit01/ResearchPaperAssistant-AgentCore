import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

import boto3

REGION = "us-east-1"
_THINKING = re.compile(r"<thinking>.*?(?:</thinking>|$)", re.DOTALL)


def clean_thinking(text):
    """Drop the model's <thinking> blocks, including one that is still being streamed."""
    return _THINKING.sub("", text).strip()


def _tokens(response):
    auth = response["AuthenticationResult"]
    return {
        "access": auth["AccessToken"],
        "refresh": auth.get("RefreshToken"),
        "expires_at": time.time() + auth["ExpiresIn"],
    }


def sign_in(client_id, username, password):
    print(f"Signing in {username}…")
    idp = boto3.client("cognito-idp", region_name=REGION)
    return _tokens(idp.initiate_auth(
        ClientId=client_id, AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password}))


def refresh(client_id, refresh_token):
    idp = boto3.client("cognito-idp", region_name=REGION)
    tokens = _tokens(idp.initiate_auth(
        ClientId=client_id, AuthFlow="REFRESH_TOKEN_AUTH",
        AuthParameters={"REFRESH_TOKEN": refresh_token}))
    tokens["refresh"] = refresh_token  # a refresh does not return a new refresh token
    return tokens


def parse_event(line):
    """One SSE line -> ("tool", name) | ("text", chunk) | None."""
    line = line.strip()
    if line.startswith("data:"):
        line = line[5:].strip()
    try:
        event = json.loads(line)["event"]
    except (ValueError, KeyError, TypeError):
        return None
    start = event.get("contentBlockStart", {}).get("start", {})
    if "toolUse" in start:
        return ("tool", start["toolUse"]["name"])
    text = event.get("contentBlockDelta", {}).get("delta", {}).get("text")
    return ("text", text) if text else None


def stream_chat(runtime_arn, access_token, session_id, prompt):
    """Call the deployed agent; yield ("tool", name) and ("text", chunk) as they arrive."""
    url = (f"https://bedrock-agentcore.{REGION}.amazonaws.com/runtimes/"
           f"{urllib.parse.quote(runtime_arn, safe='')}/invocations?qualifier=DEFAULT")
    req = urllib.request.Request(url, data=json.dumps({"prompt": prompt}).encode(), headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            for raw in resp:
                item = parse_event(raw.decode())
                if item:
                    yield item
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Runtime returned HTTP {e.code}: {e.read().decode()[:300]}") from e

