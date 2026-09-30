"""Single-completion client for the subscription-backed Responses endpoint.

POST https://chatgpt.com/backend-api/codex/responses
  Authorization: Bearer <access_token>
  ChatGPT-Account-ID: <account id from token claims>

Speaks the Responses API shape. Requests non-streamed output but also
parses SSE streams in case the endpoint forces streaming.
"""

import json
import http.client
import urllib.error
import urllib.request

from .auth import (
    AuthError,
    account_id,
    ensure_fresh_tokens,
    refresh_now,
)

RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
DEFAULT_MODEL = "gpt-6-astra"  # present in the Codex CLI's own model list


class ClientError(Exception):
    pass


def _headers(access_token):
    acct = account_id(access_token)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}",
        # mimic the official CLI so the request isn't fingerprinted as foreign
        "originator": "codex_cli_rs",
    }
    if acct:
        headers["ChatGPT-Account-ID"] = acct
    return headers


def _extract_text_nostream(data):
    """Pull assistant text out of a non-streamed Responses API payload."""
    chunks = []
    for item in data.get("output", []) or []:
        for part in item.get("content", []) or []:
            if part.get("type") == "output_text" and part.get("text"):
                chunks.append(part["text"])
    if chunks:
        return "".join(chunks)
    # some shapes put text directly on the message item
    for item in data.get("output", []) or []:
        if item.get("type") == "message" and isinstance(item.get("content"), str):
            chunks.append(item["content"])
    return "".join(chunks)


def _extract_text_sse(raw):
    """Parse a text/event-stream body into the final assistant text."""
    text_parts = []
    completed_text = None
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        payload = line[len("data:"):].strip()
        if payload == "[DONE]":
            break
        try:
            event = json.loads(payload)
        except json.JSONDecodeError:
            continue
        etype = event.get("type", "")
        if etype in ("response.output_text.delta", "response.text.delta"):
            delta = event.get("delta", "")
            if isinstance(delta, str):
                text_parts.append(delta)
        elif etype == "response.completed":
            completed_text = _extract_text_nostream(event.get("response", {}))
    return completed_text or "".join(text_parts)


def complete(prompt, model=DEFAULT_MODEL, system=None, max_output_tokens=4000,
             timeout=180):
    """One model completion, billed to the ChatGPT plan. Returns text."""
    # this endpoint requires stream=true; output is parsed from SSE events
    body = {"model": model, "stream": True, "store": False}
    # this endpoint requires `input` as a list of messages, not a string
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body["input"] = messages
    # NOTE: this endpoint rejects max_output_tokens — keep the body minimal.
    # The parameter is kept in the signature for API compatibility.

    def _do_request(access_token):
        req = urllib.request.Request(
            RESPONSES_URL,
            data=json.dumps(body).encode(),
            headers=_headers(access_token),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as res:
            try:
                raw_bytes = res.read()
            except http.client.IncompleteRead as e:
                # endpoint closes the chunked stream without a terminating
                # chunk; the partial body is complete for our purposes
                raw_bytes = e.partial
            raw = raw_bytes.decode("utf-8", errors="replace")
            ctype = res.headers.get("Content-Type", "") or ""
        # the endpoint streams SSE but sends no Content-Type header,
        # so sniff the body instead of trusting the header
        if "text/event-stream" in ctype or raw.lstrip().startswith("event:"):
            return _extract_text_sse(raw)
        return _extract_text_nostream(json.loads(raw))

    tokens = ensure_fresh_tokens()
    try:
        text = _do_request(tokens["access_token"])
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        if e.code == 401:
            # token died mid-flight: one guarded refresh, then retry once
            tokens = refresh_now()
            try:
                text = _do_request(tokens["access_token"])
            except urllib.error.HTTPError as e2:
                err2 = e2.read().decode("utf-8", errors="replace")[:500]
                raise ClientError(f"request failed after refresh ({e2.code}): {err2}")
        else:
            raise ClientError(f"request failed ({e.code}): {err_body}")
    if not text:
        raise ClientError("endpoint returned no text")
    return text
