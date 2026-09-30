# codex-sub

ChatGPT-subscription GPT access for agents — **no API key, no Platform billing**.

Uses the same OAuth tokens as `codex login` and calls the subscription-backed
Responses endpoint (`chatgpt.com/backend-api/codex/responses`). Usage draws
from the ChatGPT plan's allowance.

## Setup (one time, ~1 minute)

```bash
npm install -g @openai/codex
codex-sub login        # or: codex login --device-auth
```

You'll get a URL + one-time code. Open the URL in a browser signed into
ChatGPT, enter the code, approve. Tokens land in `~/.codex/auth.json`
(0600, same as the Codex CLI). Done — every agent on this machine can now
call GPT through your subscription.

## Use

```bash
codex-sub status                                  # auth state, no secrets shown
codex-sub complete --model gpt-6-astra "prompt"   # one completion → stdout
echo "prompt" | codex-sub complete                # prompt via stdin
codex-sub complete --system "..." "prompt"        # with system instructions
codex-sub models                                  # model ids seen in Codex CLI
```

Env: `CODEX_SUB_MODEL` overrides the default model (`gpt-6-astra`).

From Python:

```python
from codex_sub import complete
text = complete("write a haiku about deploys", model="gpt-6-luna")
```

## How it works

- `codex_sub/auth.py` — loads `~/.codex/auth.json`, proactively refreshes the
  access token when <5 min of life remains. Refresh is guarded by an
  exclusive file lock: **only one refresher may own the file** (refresh
  tokens rotate server-side; two concurrent refreshers invalidate each other).
  On a 401 mid-request the client refreshes once and retries once.
- `codex_sub/client.py` — POSTs the Responses API shape with
  `Authorization: Bearer` + `ChatGPT-Account-ID` (from token claims) +
  `originator: codex_cli_rs`, mimicking the official CLI. Parses both
  non-streamed JSON and SSE streams.

Zero dependencies — stdlib only.

## Honest warnings

1. **This rides an undocumented surface.** OpenAI can change the endpoint,
   token shape, or model allowlist at any time. It broke nothing today;
   when it breaks, `codex-sub status` + `codex-sub refresh` is the triage,
   and re-running `codex login --device-auth` is the fix.
2. **Gray zone, not a contract.** Third-party reuse of Codex OAuth is
   tolerated in practice but not officially blessed. Don't build a product
   on it; fine for personal agent use.
3. **Model allowlist.** Only models the Codex backend serves are reachable
   (see `codex-sub models`). If a model 404s/400s here, it's not allowlisted
   for subscription auth.
4. **One refresher.** Don't run `codex` CLI commands concurrently with
   long `codex-sub` jobs — racing refreshes can invalidate the session.
5. **Never commit `~/.codex/auth.json`.** It lives outside any repo; keep it
   that way.

## The official future

OpenAI announced **"Sign in with ChatGPT"** for third-party apps at DevDay
(Sep 30, 2026) — partner-gated at launch. When it opens to self-serve, that
becomes the supported version of this. Until then, this is the working
stopgap.
