"""Print an access token for a test user.

    export TOKEN=$(python3 scripts/get_jwt.py)               # TEST_USER1
    export TOKEN2=$(python3 scripts/get_jwt.py "$TEST_USER2")

Needs REGION, CLIENT_ID, TEST_USER1 and TEST_PASSWORD in the environment. Tokens last about an hour.
"""
import os
import sys

import boto3

user = sys.argv[1] if len(sys.argv) > 1 else os.environ["TEST_USER1"]
idp = boto3.client("cognito-idp", region_name=os.environ["REGION"])
response = idp.initiate_auth(
    ClientId=os.environ["CLIENT_ID"],
    AuthFlow="USER_PASSWORD_AUTH",
    AuthParameters={"USERNAME": user, "PASSWORD": os.environ["TEST_PASSWORD"]},
)
print(response["AuthenticationResult"]["AccessToken"])
