"""
One-time OAuth 1.0a bootstrap for Hattrick CHPP.

Run after your CHPP application is approved and you've filled consumer_key +
consumer_secret into .chpp-credentials.json. From the repository root (the
folder that contains this README and the hattrick_team_assistant/ package):

    python -m hattrick_team_assistant.auth

Walks you through the standard OOB (out-of-band) OAuth flow:
  1. Get a request token
  2. Print an authorize URL - open in browser while logged in as your manager
  3. You paste back the verifier code Hattrick shows
  4. We exchange for an access token + secret and save them to
     .chpp-credentials.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from requests_oauthlib import OAuth1Session

from .chpp import (
    OAUTH_REQUEST_TOKEN_URL,
    OAUTH_AUTHORIZE_URL,
    OAUTH_ACCESS_TOKEN_URL,
)


CREDS_PATH = Path(".chpp-credentials.json")


def main() -> int:
    print("Hattrick Team Assistant - CHPP OAuth bootstrap")
    print("=" * 60)

    if not CREDS_PATH.exists():
        print(
            f"ERROR: {CREDS_PATH} not found. Copy .chpp-credentials.example.json "
            f"to {CREDS_PATH} and fill in consumer_key + consumer_secret first."
        )
        return 1

    data = json.loads(CREDS_PATH.read_text(encoding="utf-8"))

    consumer_key = data.get("consumer_key", "")
    consumer_secret = data.get("consumer_secret", "")

    if not consumer_key or consumer_key.startswith("PASTE-"):
        print(
            "ERROR: consumer_key not filled in. Open .chpp-credentials.json, paste "
            "the consumer key from your approved CHPP application, save, retry. "
            f"(Looking in current working directory: {Path.cwd()})"
        )
        return 2

    if not consumer_secret or consumer_secret.startswith("PASTE-"):
        print("ERROR: consumer_secret not filled in. Same as above for the secret.")
        return 2

    # Step 1: request a temporary OAuth token, OOB callback
    print("\nStep 1: requesting a temporary OAuth token...")
    oauth = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        callback_uri="oob",
    )
    try:
        fetch_response = oauth.fetch_request_token(OAUTH_REQUEST_TOKEN_URL)
    except Exception as e:
        print(f"FAILED to fetch request token: {e}")
        return 3

    resource_owner_key = fetch_response.get("oauth_token", "")
    resource_owner_secret = fetch_response.get("oauth_token_secret", "")
    if not resource_owner_key:
        print(f"FAILED: no oauth_token in response: {fetch_response}")
        return 3
    print("OK")

    # Step 2: authorize URL
    authorize_url = oauth.authorization_url(OAUTH_AUTHORIZE_URL)
    print("\nStep 2: open the following URL in your browser while logged in")
    print("        to Hattrick as the manager account you want to authorize:")
    print()
    print(f"   {authorize_url}")
    print()
    print("        Click 'Allow' on the page that appears. Hattrick will show you")
    print("        a short verifier code (~5-7 characters).")
    print()
    verifier = input("Paste the verifier code here and press Enter: ").strip()
    if not verifier:
        print("FAILED: empty verifier. Aborting.")
        return 4

    # Step 3: exchange for access token
    print("\nStep 3: exchanging verifier for permanent access token...")
    oauth = OAuth1Session(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=resource_owner_key,
        resource_owner_secret=resource_owner_secret,
        verifier=verifier,
    )
    try:
        access_response = oauth.fetch_access_token(OAUTH_ACCESS_TOKEN_URL)
    except Exception as e:
        print(f"FAILED to exchange verifier: {e}")
        return 5

    access_token = access_response.get("oauth_token", "")
    access_token_secret = access_response.get("oauth_token_secret", "")
    if not access_token or not access_token_secret:
        print(f"FAILED: missing oauth_token in access response: {access_response}")
        return 5
    print("OK")

    # Step 4: write back
    data["access_token"] = access_token
    data["access_token_secret"] = access_token_secret
    data.pop("_comment_", None)
    CREDS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nWrote permanent credentials to {CREDS_PATH}.")
    print()
    print("Quick smoke test - fetching your team details...")
    from .chpp import CHPPClient
    try:
        client = CHPPClient.from_credentials_file(CREDS_PATH)
        me = client.team_details()
        # CHPP teamdetails has a Teams > Team list, pick the first
        teams = me.get("Teams", {}).get("Team", [])
        if isinstance(teams, dict):
            teams = [teams]
        for t in teams:
            print(f"  team_id={t.get('TeamID')}  name={t.get('TeamName')}")
        print("\nAll set. Try `from hattrick_team_assistant import CHPPClient` in Python.")
        return 0
    except Exception as e:
        print(f"Smoke test failed: {e}")
        print("Credentials are saved, but verify them manually.")
        return 6


if __name__ == "__main__":
    sys.exit(main())
