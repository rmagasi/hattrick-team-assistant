# Hattrick Team Assistant - Python helper

This is the local Python helper that talks to Hattrick CHPP once the application
"Hattrick Team Assistant" is approved by the CHPP administrators.

## Status

- CHPP application: submitted 2026-05-13, pending review.
- Until approved, this code is NOT YET USABLE. Approval is the unblocker.
- Do not run the OAuth bootstrap until you have an approved consumer key + secret.

## What's here

```
hattrick-team-assistant/
├── README.md                       this file
├── requirements.txt                requests, requests-oauthlib
├── .gitignore                      protects real credentials from being committed
├── .chpp-credentials.example.json  template, copy and fill in
└── hattrick_team_assistant/        the Python package (importable name)
    ├── __init__.py                 exports CHPPClient, CHPPError
    ├── chpp.py                     main client, one method per CHPP endpoint
    ├── auth.py                     one-time OAuth 1.0a bootstrap
    └── cache.py                    tiny disk + memory cache for XML responses
```

Project folder uses hyphens (matches the GitHub repo). Python package uses
underscores (Python identifier rule, hyphens not allowed).

## Setup once your CHPP application is approved

1. **Install dependencies** (if not already installed):

   ```
   pip install -r requirements.txt --break-system-packages
   ```

2. **Copy the credentials template:**

   ```
   cp .chpp-credentials.example.json .chpp-credentials.json
   ```

3. **Paste the consumer key + consumer secret** from the Hattrick CHPP Manager
   page into `.chpp-credentials.json`. Leave the two `access_token*` fields
   alone for now, the next step fills them in.

4. **Run the OAuth bootstrap:**

   ```
   python -m hattrick_team_assistant.auth
   ```

   This prints an authorize URL. Open it in your browser while logged in to
   Hattrick as the manager account you want to authorize (typically `robi_`).
   Click Allow, copy the verifier code Hattrick shows, paste it back to the
   prompt. The script writes the permanent access tokens to
   `.chpp-credentials.json` and runs a smoke test.

5. **Use it from Python:**

   ```python
   from hattrick_team_assistant import CHPPClient

   client = CHPPClient.from_credentials_file(".chpp-credentials.json")

   # Public data
   league = client.league_details(11329)            # III.1 Hungary
   matches = client.matches(team_id=158111)         # Hetvehely schedule
   opp = client.team_details(team_id=578979)        # scout an opponent

   # Private data (own teams)
   eco = client.economy(team_id=3235631)            # Apa lanyai economy
   training = client.training(team_id=158111)
   ```

## Design notes

- **Read-only by design.** No `set_lineup`, `place_bid` or any other endpoint
  that modifies game state. The CHPP application was submitted for read-only
  access only.
- **OAuth 1.0a** as required by Hattrick CHPP. Each user runs the bootstrap
  once per Hattrick manager account they want to authorize.
- **Cache, 2-tier** (memory + disk under `cache/`), invalidated by TTL per
  endpoint (see `DEFAULT_TTL` in `chpp.py`).
- **Throttle, 1 req/sec** minimum spacing between live calls. Well within
  CHPP rate limits.
- **Errors as exceptions,** anything that's not a 200 OK with valid XML raises
  `CHPPError`. Callers should expect to handle them.
- **No global state,** the client is instantiated per-script, credentials stay
  in the file you load.

## What's NOT here

- A web UI. This is a local library for use from Python or via the LLM helper.
- Multi-user support. Each manager runs their own copy with their own creds.
- Background polling / daemons.

## Once you've used it for a bit

If you find specific analytical patterns useful, fold them into a `recipes/`
subpackage with one function per analysis. The CHPP wrapper stays generic.
