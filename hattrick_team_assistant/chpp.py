"""
CHPPClient - thin OAuth1-signed wrapper around Hattrick's CHPP XML API.

Usage:
    from hattrick_team_assistant import CHPPClient
    client = CHPPClient.from_credentials_file(".chpp-credentials.json")
    team = client.team_details(158111)
    print(team["TeamName"])

Design principles:
- One method per CHPP endpoint, named with snake_case Python convention.
- All methods return parsed dicts (nested), not raw XML.
- Built-in caching (memory + disk) with sensible per-endpoint TTL.
- Built-in throttling: minimum spacing between live requests (default 1 req/sec).
- Read-only: no `set*` methods, by design. This client cannot modify game state.

References:
- https://chpp.hattrick.org/ - API docs
- https://wiki.hattrick.org/wiki/CHPP_Manual
"""

from __future__ import annotations

import json
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Optional

import requests
from requests_oauthlib import OAuth1Session

from .cache import XMLCache


CHPP_BASE_URL = "https://chpp.hattrick.org/chppxml.ashx"
OAUTH_REQUEST_TOKEN_URL = "https://chpp.hattrick.org/oauth/request_token.ashx"
OAUTH_AUTHORIZE_URL = "https://chpp.hattrick.org/oauth/authorize.aspx"
OAUTH_ACCESS_TOKEN_URL = "https://chpp.hattrick.org/oauth/access_token.ashx"


# Per-endpoint TTL hints in seconds. Endpoints whose underlying data changes
# only on weekly/economy/training days can be cached longer; live data like
# matches in progress needs a shorter TTL.
DEFAULT_TTL = {
    "teamdetails":     6 * 3600,   # 6h - team info changes slowly
    "worlddetails":    24 * 3600,  # 24h - country/league reference data
    "leaguedetails":   3 * 3600,   # 3h - standings update after each match
    "matches":         1 * 3600,   # 1h - schedule may shift
    "matchdetails":    24 * 3600,  # 24h - finished matches don't change
    "players":         3 * 3600,
    "playerdetails":   3 * 3600,
    "arenadetails":    24 * 3600,
    "economy":         3 * 3600,   # 3h - changes only on economy update day
    "training":        3 * 3600,
    "clubdetails":     6 * 3600,
    "lineup":          0,          # 0 = always live, don't cache
    "transfersteam":   1 * 3600,
    "youthplayerlist": 6 * 3600,
}


class CHPPError(RuntimeError):
    """Raised when the CHPP API returns an error or an HTTP-level failure."""


class CHPPClient:
    """OAuth1-authenticated client for Hattrick CHPP. Read-only, multi-team aware."""

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_token_secret: str,
        cache_dir: Optional[Path] = None,
        min_request_interval: float = 1.0,
    ):
        if not all([consumer_key, consumer_secret, access_token, access_token_secret]):
            raise CHPPError(
                "Missing one or more OAuth credentials. Run `python -m team_assistant.auth` "
                "to bootstrap, or fill in .chpp-credentials.json manually."
            )
        self._session = OAuth1Session(
            consumer_key,
            client_secret=consumer_secret,
            resource_owner_key=access_token,
            resource_owner_secret=access_token_secret,
        )
        self._cache = XMLCache(cache_dir or Path("cache"))
        self._min_interval = min_request_interval
        self._last_request_at = 0.0

    # ---------- construction helpers ----------

    @classmethod
    def from_credentials_file(cls, path: str | Path, **kwargs) -> "CHPPClient":
        """Load credentials from a JSON file with keys consumer_key, consumer_secret,
        access_token, access_token_secret."""
        path = Path(path)
        if not path.exists():
            raise CHPPError(
                f"Credentials file not found: {path}. Copy .chpp-credentials.example.json "
                f"to .chpp-credentials.json and fill in your CHPP keys."
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            consumer_key=data["consumer_key"],
            consumer_secret=data["consumer_secret"],
            access_token=data["access_token"],
            access_token_secret=data["access_token_secret"],
            **kwargs,
        )

    # ---------- low-level call ----------

    def _request(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """Make a CHPP call, possibly served from cache. Returns the raw XML text."""
        params = dict(params or {})
        params["file"] = endpoint
        params.setdefault("version", "1.0")

        if ttl is None:
            ttl = DEFAULT_TTL.get(endpoint, 0)

        # Cache lookup
        if ttl > 0:
            cached = self._cache.get(endpoint, params, ttl=ttl)
            if cached is not None:
                return cached

        # Throttle live calls
        elapsed = time.time() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

        try:
            response = self._session.get(CHPP_BASE_URL, params=params, timeout=20)
            self._last_request_at = time.time()
        except requests.RequestException as e:
            raise CHPPError(f"Network error calling {endpoint}: {e}") from e

        if response.status_code != 200:
            raise CHPPError(
                f"CHPP {endpoint} returned HTTP {response.status_code}: {response.text[:300]}"
            )

        text = response.text
        # CHPP can return XML errors with status 200; detect them
        if "<Error>" in text and "<ErrorCode>" in text:
            raise CHPPError(f"CHPP {endpoint} returned error XML: {text[:500]}")

        if ttl > 0:
            self._cache.put(endpoint, params, text)
        return text

    def _call(
        self,
        endpoint: str,
        params: Optional[dict[str, Any]] = None,
        ttl: Optional[int] = None,
    ) -> dict:
        """Make a CHPP call and return the parsed dict."""
        return self._parse(self._request(endpoint, params, ttl))

    def fetch_raw(self, endpoint: str, ttl: Optional[int] = None, **params) -> str:
        """Fetch any CHPP endpoint and return the raw XML text (not parsed).
        Used by the snapshot module to archive responses verbatim. Example:
            client.fetch_raw("economy", teamID=158111)
        """
        return self._request(endpoint, params, ttl)

    @staticmethod
    def _parse(xml_text: str) -> dict:
        """Parse XML into a nested dict. Lists are inferred from repeated tags."""
        root = ET.fromstring(xml_text)
        return _et_to_dict(root)

    # ---------- public endpoints ----------

    def team_details(self, team_id: Optional[int] = None) -> dict:
        """Public team info. Without team_id, returns the authenticated user's primary team."""
        params = {"teamID": team_id} if team_id else {}
        return self._call("teamdetails", params)

    def world_details(
        self,
        country_id: Optional[int] = None,
        league_id: Optional[int] = None,
        include_regions: bool = False,
    ) -> dict:
        """Country / league reference data."""
        params: dict[str, Any] = {"version": "1.9"}
        if country_id:
            params["countryID"] = country_id
        if league_id:
            params["leagueID"] = league_id
        if include_regions:
            params["includeRegions"] = "true"
        return self._call("worlddetails", params)

    def league_details(self, league_unit_id: int) -> dict:
        """League series standings + 8-team roster."""
        return self._call(
            "leaguedetails",
            {"leagueLevelUnitID": league_unit_id, "version": "1.6"},
        )

    def matches(
        self,
        team_id: int,
        first_date: Optional[str] = None,
        last_date: Optional[str] = None,
        is_youth: bool = False,
    ) -> dict:
        """List of past + upcoming matches for a team. Dates in 'YYYY-MM-DD'."""
        params: dict[str, Any] = {"teamID": team_id, "version": "2.8"}
        if first_date:
            params["FirstMatchDate"] = first_date
        if last_date:
            params["LastMatchDate"] = last_date
        if is_youth:
            params["isYouth"] = "true"
        return self._call("matches", params)

    def match_details(self, match_id: int, match_type: Optional[int] = None) -> dict:
        """Detailed match data: lineups, ratings, events. matchID is the CHPP match ID."""
        params: dict[str, Any] = {"matchID": match_id, "version": "3.1"}
        if match_type is not None:
            params["sourceSystem"] = "hattrick"  # placeholder; CHPP variants
        return self._call("matchdetails", params)

    def players(self, team_id: Optional[int] = None) -> dict:
        """Public player list for a team. For your own team, returns full skills.
        For opponents, returns visible-to-public skills only."""
        params = {"teamID": team_id, "version": "2.4"} if team_id else {"version": "2.4"}
        return self._call("players", params)

    def player_details(self, player_id: int) -> dict:
        """Full player details. Skills are fully visible only for your own players."""
        return self._call("playerdetails", {"playerID": player_id, "version": "2.9"})

    def arena_details(self, team_id: Optional[int] = None) -> dict:
        """Stadium info: capacity, sections, attendance history."""
        params = {"teamID": team_id, "version": "1.5"} if team_id else {"version": "1.5"}
        return self._call("arenadetails", params)

    # ---------- private endpoints (own teams only) ----------

    def economy(self, team_id: Optional[int] = None) -> dict:
        """Cash, income, costs, sponsor mood, weekly net. Owner-only data."""
        params = {"teamID": team_id, "version": "1.4"} if team_id else {"version": "1.4"}
        return self._call("economy", params)

    def training(self, team_id: Optional[int] = None) -> dict:
        """Current training type, intensity, stamina share."""
        params = {"actionType": "view"}
        if team_id:
            params["teamID"] = team_id
        return self._call("training", params)

    def club_details(self, team_id: Optional[int] = None) -> dict:
        """Staff, fan club, junior team, rankings."""
        params = {"teamID": team_id, "version": "1.5"} if team_id else {"version": "1.5"}
        return self._call("clubdetails", params)

    def lineup(self, match_id: int, team_id: Optional[int] = None) -> dict:
        """Read your next-match lineup. Not cached - always live."""
        params: dict[str, Any] = {"matchID": match_id, "version": "1.9"}
        if team_id:
            params["teamID"] = team_id
        return self._call("lineup", params)

    def transfers_team(self, team_id: Optional[int] = None, page: int = 0) -> dict:
        """Your team's historical buy/sell transactions."""
        params: dict[str, Any] = {"version": "1.3", "pageIndex": page}
        if team_id:
            params["teamID"] = team_id
        return self._call("transfersteam", params)

    def youthplayer_list(self, youth_team_id: int) -> dict:
        """Youth squad roster + skills with confidence ranges."""
        return self._call(
            "youthplayerlist",
            {"youthTeamID": youth_team_id, "version": "1.1"},
        )

    # ---------- cache management ----------

    def clear_cache(self) -> int:
        """Drop all cached responses. Returns number of entries dropped."""
        return self._cache.invalidate()


# ----------- small XML helper -------------

def _et_to_dict(elem: ET.Element) -> dict | str:
    """Convert an ElementTree node into a nested dict. Repeated child tags
    become lists. Leaf nodes return their text content (str)."""
    children = list(elem)
    if not children:
        return (elem.text or "").strip()

    result: dict[str, Any] = {}
    counts: dict[str, int] = {}
    for c in children:
        counts[c.tag] = counts.get(c.tag, 0) + 1

    for child in children:
        value = _et_to_dict(child)
        if counts[child.tag] > 1:
            result.setdefault(child.tag, []).append(value)
        else:
            result[child.tag] = value
    return result
