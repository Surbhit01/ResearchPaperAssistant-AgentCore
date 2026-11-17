"""Search the Knowledge Base directly, the way the search_library tool does, and print scores.

    python3 scripts/kb_search.py "How does multi-head attention work?"            # as TEST_USER1
    python3 scripts/kb_search.py "How does multi-head attention work?" --user "$TEST_USER2"
    python3 scripts/kb_search.py "How does multi-head attention work?" --no-filter     # no user filter: both users' chunks
    python3 scripts/kb_search.py "..." --paper 1706.03762 -n 3

Needs REGION, POOL_ID, KB_ID and TEST_USER1 in the environment.
"""
import argparse
import os

import boto3


def build_filter(sub, paper=None):
    """Always filters on the user; a paper id only narrows the search within the user's own papers."""
    user = {"equals": {"key": "user_id", "value": sub}}
    if not paper:
        return user
    return {"andAll": [user, {"equals": {"key": "arxiv_id", "value": paper}}]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--user")
    parser.add_argument("--paper")
    parser.add_argument("--no-filter", action="store_true")
    parser.add_argument("-n", type=int, default=5)
    args = parser.parse_args()
    region = os.environ["REGION"]
    config = {"numberOfResults": args.n}
    if not args.no_filter:
        username = args.user or os.environ["TEST_USER1"]
        attributes = boto3.client("cognito-idp", region_name=region).admin_get_user(
            UserPoolId=os.environ["POOL_ID"], Username=username)["UserAttributes"]
        config["filter"] = build_filter(next(a["Value"] for a in attributes if a["Name"] == "sub"), args.paper)
    results = boto3.client("bedrock-agent-runtime", region_name=region).retrieve(
        knowledgeBaseId=os.environ["KB_ID"], retrievalQuery={"text": args.query},
        retrievalConfiguration={"vectorSearchConfiguration": config})["retrievalResults"]
    print(f"{'score':>6}  {'paper':12} {'page':>5}  passage")
    for r in results:
        page = r["metadata"].get("x-amz-bedrock-kb-document-page-number")
        print(f"{r['score']:6.3f}  {str(r['metadata'].get('arxiv_id')):12} {'' if page is None else int(page):>5}  {' '.join(r['content']['text'].split())[:90]}")
    if not results:
        print("(no results)")
