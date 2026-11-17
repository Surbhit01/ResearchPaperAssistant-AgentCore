import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_PDF = "https://arxiv.org/pdf/{}"
ATOM = {"a": "http://www.w3.org/2005/Atom"}
# New-style (2401.12345, optional v2) or old-style (cs/0112017)
ARXIV_ID = re.compile(r"^(\d{4}\.\d{4,5}(v\d+)?|[a-z\-]+(\.[A-Z]{2})?/\d{7}(v\d+)?)$")
USER_AGENT = "research-assistant-skeleton/0.1 (learning project)"
MAX_PDF_BYTES = 25 * 1024 * 1024

s3 = boto3.client("s3")
bedrock_agent = boto3.client("bedrock-agent")
bedrock_agent_runtime = boto3.client("bedrock-agent-runtime")


class ToolError(Exception):
    """A failure the agent should be told about in plain words (not an internal error)."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def lambda_handler(event, context):
    full_name = context.client_context.custom["bedrockAgentCoreToolName"] ## <GATEWAY_TARGET>__{TOOLNAME} -researchassistant__search_arxiv
    tool = full_name.split("___", 1)[-1]

    try:
        if tool == "search_arxiv":
            return search_arxiv(event["query"], int(event.get("max_results", 5)))
        if tool == "add_paper":
            return add_paper(event["arxiv_id"], user_id=_caller(event))
        if tool == "list_papers":
            return list_papers(user_id=_caller(event))
        if tool == "search_library":
            return search_library(event["query"], event.get("arxiv_ids"), user_id=_caller(event))
    except ToolError as e:
        return {"error": {"code": e.code, "message": str(e)}}
    return {"error": {"code": "UNKNOWN_TOOL", "message": tool}}


def _caller(event):
    """The user id is injected by the Gateway interceptor, never supplied by the model."""
    user_id = (event.get("_caller") or {}).get("user_id")
    if not user_id:
        raise PermissionError("missing caller identity")
    return user_id


def _canonical(arxiv_id):
    """2307.03172v3 -> 2307.03172, so one paper has one identity whatever version is asked for."""
    return re.sub(r"v\d+$", "", arxiv_id)


def _fetch(url, timeout=15, limit=None):
    """GET from arXiv with one retry. Raises ToolError (not a stack trace) when arXiv is unavailable."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read(limit + 1) if limit else resp.read()
            break
        except (TimeoutError, urllib.error.URLError, ConnectionError) as e:
            if attempt == 2:
                raise ToolError("ARXIV_UNAVAILABLE", "arXiv did not respond; try again in a moment") from e
            time.sleep(1)
    if limit and len(body) > limit:
        raise ToolError("PDF_TOO_LARGE", f"the PDF is larger than {limit // (1024 * 1024)} MB")
    return body


def _query_arxiv(**params):
    root = ET.fromstring(_fetch(f"{ARXIV_API}?{urllib.parse.urlencode(params)}"))
    papers = []
    # Each entry is a paper 
    for entry in root.findall("a:entry", ATOM):
        papers.append({
            "arxiv_id": entry.findtext("a:id", namespaces=ATOM).rsplit("/abs/", 1)[-1],
            "title": " ".join(entry.findtext("a:title", namespaces=ATOM).split()),
            "authors": [a.findtext("a:name", namespaces=ATOM) for a in entry.findall("a:author", ATOM)],
            "year": int(entry.findtext("a:published", namespaces=ATOM)[:4]),
            "abstract": " ".join(entry.findtext("a:summary", namespaces=ATOM).split()),
        })
    return papers


def search_arxiv(query, max_results):
    max_results = max(1, min(max_results, 10))  # defence in depth; Policy comes later
    return {"papers": _query_arxiv(search_query=f"all:{query}", max_results=max_results)}


def _start_ingestion():
    """Index new documents. Only one job may run at a time; a conflict means one is already running."""
    try:
        bedrock_agent.start_ingestion_job(
            knowledgeBaseId=os.environ["KB_ID"], dataSourceId=os.environ["DATA_SOURCE_ID"])
        return "STARTED"
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            return "RUNNING"
        raise


def add_paper(arxiv_id, user_id):
    if not ARXIV_ID.match(arxiv_id):
        return {"error": {"code": "INVALID_ARXIV_ID", "message": arxiv_id}}
    paper_id = _canonical(arxiv_id)

    found = _query_arxiv(id_list=paper_id)
    if not found:
        return {"error": {"code": "NOT_FOUND", "message": paper_id}}
    info = found[0]

    pdf = _fetch(ARXIV_PDF.format(paper_id), timeout=20, limit=MAX_PDF_BYTES)
    if not pdf.startswith(b"%PDF"):
        raise ToolError("NOT_A_PDF", "arXiv did not return a PDF for this paper")

    bucket = os.environ["BUCKET"]
    doc_key = f"library/{user_id}/{paper_id}.pdf"
    # The Knowledge Base reads <document>.metadata.json next to each document and stores these
    # values with every chunk; search_library filters on user_id.
    s3.put_object(Bucket=bucket, Key=f"{doc_key}.metadata.json", ContentType="application/json",
                  Body=json.dumps({"metadataAttributes": {"user_id": user_id, "arxiv_id": paper_id}}).encode())
    s3.put_object(Bucket=bucket, Key=doc_key, Body=pdf, ContentType="application/pdf")
    # Display details live outside library/, so the Knowledge Base never tries to ingest them.
    saved_at = datetime.now(timezone.utc)
    s3.put_object(Bucket=bucket, Key=f"catalog/{user_id}/{paper_id}.json", ContentType="application/json",
                  Body=json.dumps({"arxiv_id": paper_id, "title": info["title"], "year": info["year"],
                                   "authors": info["authors"], "saved_at": saved_at.isoformat()}).encode())

    indexing = _start_ingestion()
    return {"saved": info["title"], "arxiv_id": paper_id,
            "status": "INDEXING" if indexing == "STARTED" else "QUEUED"}


ACTIVE_JOB = ("STARTING", "IN_PROGRESS")


def _recent_ingestion_jobs():
    response = bedrock_agent.list_ingestion_jobs(
        knowledgeBaseId=os.environ["KB_ID"], dataSourceId=os.environ["DATA_SOURCE_ID"],
        sortBy={"attribute": "STARTED_AT", "order": "DESCENDING"}, maxResults=10)
    return response.get("ingestionJobSummaries", [])


def _paper_status(saved_at, jobs):
    """Inferred from job timing: a job that started after the paper was saved has scanned it."""
    later = [j for j in jobs if j["startedAt"] >= saved_at]
    if any(j["status"] == "COMPLETE" for j in later):
        return "READY"
    if any(j["status"] in ACTIVE_JOB for j in later):
        return "INDEXING"
    if any(j["status"] == "FAILED" for j in later):
        return "FAILED"
    return "PENDING"  # no job has looked at it yet


def list_papers(user_id):
    bucket = os.environ["BUCKET"]
    jobs = _recent_ingestion_jobs()
    papers = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=f"catalog/{user_id}/"):
        for obj in page.get("Contents", []):
            entry = json.loads(s3.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read())
            papers.append({
                "arxiv_id": entry["arxiv_id"],
                "title": entry["title"],
                "year": entry["year"],
                "saved_at": entry["saved_at"],
                "status": _paper_status(datetime.fromisoformat(entry["saved_at"]), jobs),
            })
    papers.sort(key=lambda p: p["saved_at"], reverse=True)

    # Self-heal: a paper saved while another job was running (add_paper said QUEUED) is waiting for
    # a job of its own. Start one if nothing is running.
    waiting = [p for p in papers if p["status"] == "PENDING"]
    if waiting and not any(j["status"] in ACTIVE_JOB for j in jobs):
        if _start_ingestion() == "STARTED":
            for p in waiting:
                p["status"] = "INDEXING"
    return {"papers": papers}


def _paper_titles(user_id, paper_ids):
    titles = {}
    for paper_id in paper_ids:
        try:
            entry = s3.get_object(Bucket=os.environ["BUCKET"], Key=f"catalog/{user_id}/{paper_id}.json")
            titles[paper_id] = json.loads(entry["Body"].read())["title"]
        except ClientError:
            titles[paper_id] = None
    return titles


def search_library(query, arxiv_ids, user_id):
    """Search the caller's own papers. The user filter is always applied and cannot be widened."""
    if not isinstance(query, str) or not query.strip():
        raise ToolError("EMPTY_QUERY", "query must be a non-empty string")

    # Always first: only chunks stored with this user's id are considered.
    user_filter = {"equals": {"key": "user_id", "value": user_id}}
    search_filter = user_filter
    if arxiv_ids:
        ids = [_canonical(i) for i in arxiv_ids[:10]]
        if not all(ARXIV_ID.match(i) for i in ids):
            raise ToolError("INVALID_ARXIV_ID", "arxiv_ids must be arXiv IDs such as 1706.03762")
        # Narrows the search within the caller's own papers; never replaces the user filter.
        # The API rejects orAll with fewer than two conditions, so one ID is a plain equals.
        matches = [{"equals": {"key": "arxiv_id", "value": i}} for i in ids]
        paper_filter = matches[0] if len(matches) == 1 else {"orAll": matches}
        search_filter = {"andAll": [user_filter, paper_filter]}

    response = bedrock_agent_runtime.retrieve(
        knowledgeBaseId=os.environ["KB_ID"],
        retrievalQuery={"text": query[:500]},
        retrievalConfiguration={"vectorSearchConfiguration": {
            "numberOfResults": int(os.environ.get("TOP_K", "5")), "filter": search_filter}},
    )

    min_score = float(os.environ.get("SCORE_MIN", "0.65"))
    hits = [r for r in response.get("retrievalResults", []) if r.get("score", 0) >= min_score]
    if not hits:
        return {"passages": [],
                "note": "No passages in the user's library matched this question closely enough."}

    titles = _paper_titles(user_id, {r["metadata"].get("arxiv_id") for r in hits})
    return {"passages": [{
        "paper_title": titles.get(r["metadata"].get("arxiv_id")),
        "arxiv_id": r["metadata"].get("arxiv_id"),
        "passage": r["content"]["text"],
        "score": round(r["score"], 3),
        "page": r["metadata"].get("x-amz-bedrock-kb-document-page-number"),
    } for r in hits]}
