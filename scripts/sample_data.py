"""Put one sample paper in each test user's library, the way add_paper will later: PDF, metadata sidecar, catalog.

    python3 scripts/seed_sample.py

TEST_USER1 gets "Attention Is All You Need", TEST_USER2 gets BERT. Needs REGION, POOL_ID, BUCKET, TEST_USER1
and TEST_USER2. Afterwards start an ingestion job so the Knowledge Base indexes them.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timezone

import boto3

REGION = os.environ["REGION"]
POOL_ID = os.environ["POOL_ID"]
BUCKET =  os.environ["BUCKET"]

PAPERS = {
    os.environ["TEST_USER1"]: ("1706.03762", "Attention Is All You Need", 2017,
                               ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit", "Llion Jones",
                                "Aidan N. Gomez", "Lukasz Kaiser", "Illia Polosukhin"]),
    os.environ["TEST_USER2"]: ("1810.04805", "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
                               2018, ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"]),
}
UA = {"User-Agent": "research-assistant-demo/0.1 (learning project)"}
idp, s3 = boto3.client("cognito-idp", region_name=REGION), boto3.client("s3", region_name=REGION)


def user_sub(username):
    attributes = idp.admin_get_user(UserPoolId=POOL_ID, Username=username)["UserAttributes"]
    return next(a["Value"] for a in attributes if a["Name"] == "sub")


for username, (arxiv_id, title, year, authors) in PAPERS.items():
    sub = user_sub(username)
    print(f"{username} ({sub}): saving {arxiv_id} ({len(authors)} authors)")
    request = urllib.request.Request(f"https://arxiv.org/pdf/{arxiv_id}", headers=UA)
    pdf = urllib.request.urlopen(request, timeout=60).read()
    assert pdf.startswith(b"%PDF"), f"arXiv did not return a PDF for {arxiv_id}"
    key = f"library/{sub}/{arxiv_id}.pdf"
    s3.put_object(Bucket=BUCKET, Key=key + ".metadata.json", ContentType="application/json",
                  Body=json.dumps({"metadataAttributes": {"user_id": sub, "arxiv_id": arxiv_id}}).encode())
    s3.put_object(Bucket=BUCKET, Key=key, Body=pdf, ContentType="application/pdf")
    s3.put_object(Bucket=BUCKET, Key=f"catalog/{sub}/{arxiv_id}.json", ContentType="application/json",
                  Body=json.dumps({"arxiv_id": arxiv_id, "title": title, "year": year, "authors": authors,
                                   "saved_at": datetime.now(timezone.utc).isoformat()}).encode())
    print(f"{username} ({sub}): saved {arxiv_id} ({len(pdf) // 1024} KB)")
    time.sleep(3)  # arXiv asks for roughly one request every 3 seconds
