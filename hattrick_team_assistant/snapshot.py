"""
Team snapshot - archive a full point-in-time capture of one team's CHPP data.

Writes each endpoint's raw XML under:
    snapshots/<team_id>/<YYYY-MM-DD>/<endpoint>.xml
plus a manifest.json describing the snapshot.

This is the CHPP-helper equivalent of an HRF dump: a self-contained, dated
folder you can diff or revisit later. Unlike the cache (which auto-overwrites
on TTL), snapshots are permanent until you delete them.

Usage from Python:
    from hattrick_team_assistant import CHPPClient, snapshot_team
    client = CHPPClient.from_credentials_file(".chpp-credentials.json")
    path = snapshot_team(client, 158111)
    print(f"snapshot written to {path}")

Usage from the command line (from the repo root):
    python -m hattrick_team_assistant.snapshot 158111 2839340 3235631
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

from .chpp import CHPPClient, CHPPError


# Team-level endpoints captured in a snapshot, with the params each needs.
# leaguedetails is handled specially below - it needs the league unit id
# discovered from the teamdetails response.
_TEAM_ENDPOINTS = [
    ("teamdetails",   {"version": "3.6"}),
    ("players",       {"version": "2.4"}),
    ("economy",       {"version": "1.4"}),
    ("training",      {"actionType": "view"}),
    ("clubdetails",   {"version": "1.5"}),
    ("matches",       {"version": "2.8"}),
    ("arenadetails",  {"version": "1.5"}),
    ("transfersteam", {"version": "1.3"}),
]


def snapshot_team(
    client: CHPPClient,
    team_id: int,
    output_root: Optional[Path] = None,
    date_str: Optional[str] = None,
) -> Path:
    """Capture a full snapshot of one team. Returns the snapshot directory path.

    output_root defaults to ./snapshots
    date_str defaults to today (YYYY-MM-DD); pass an explicit value to re-snapshot
    into a specific folder or to back-date.

    Each endpoint is fetched force-fresh (ttl=0) so the archive is a guaranteed
    point-in-time capture, not a stale cache hit. The cache is left untouched.
    """
    output_root = Path(output_root) if output_root else Path("snapshots")
    date_str = date_str or time.strftime("%Y-%m-%d")
    snap_dir = output_root / str(team_id) / date_str
    snap_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "team_id": team_id,
        "date": date_str,
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "endpoints": {},
        "errors": {},
    }

    league_unit_id: Optional[str] = None
    team_name: Optional[str] = None

    for endpoint, base_params in _TEAM_ENDPOINTS:
        params = dict(base_params)
        params["teamID"] = team_id
        try:
            xml = client.fetch_raw(endpoint, ttl=0, **params)
            (snap_dir / f"{endpoint}.xml").write_text(xml, encoding="utf-8")
            manifest["endpoints"][endpoint] = f"{endpoint}.xml"
            # opportunistically pull league unit id + team name out of teamdetails
            if endpoint == "teamdetails":
                m = re.search(r"<LeagueLevelUnitID>(\d+)</LeagueLevelUnitID>", xml)
                if m:
                    league_unit_id = m.group(1)
                m = re.search(r"<TeamName>([^<]+)</TeamName>", xml)
                if m:
                    team_name = m.group(1)
        except CHPPError as e:
            manifest["errors"][endpoint] = str(e)

    # leaguedetails needs the league unit id discovered above
    if league_unit_id:
        try:
            xml = client.fetch_raw(
                "leaguedetails", ttl=0, leagueLevelUnitID=league_unit_id, version="1.6"
            )
            (snap_dir / "leaguedetails.xml").write_text(xml, encoding="utf-8")
            manifest["endpoints"]["leaguedetails"] = "leaguedetails.xml"
        except CHPPError as e:
            manifest["errors"]["leaguedetails"] = str(e)
    else:
        manifest["errors"]["leaguedetails"] = (
            "skipped - no LeagueLevelUnitID found in teamdetails"
        )

    manifest["team_name"] = team_name
    manifest["league_unit_id"] = league_unit_id

    (snap_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return snap_dir


def main(argv: Optional[list[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print(
            "Usage: python -m hattrick_team_assistant.snapshot <team_id> [<team_id> ...]\n"
            "Run from the repo root (where .chpp-credentials.json lives)."
        )
        return 2

    try:
        client = CHPPClient.from_credentials_file(".chpp-credentials.json")
    except CHPPError as e:
        print(f"ERROR: {e}")
        return 1

    print("Hattrick Team Assistant - team snapshot")
    print("=" * 50)
    exit_code = 0
    for arg in argv:
        try:
            team_id = int(arg)
        except ValueError:
            print(f"  skipping '{arg}' - not a numeric team id")
            exit_code = 2
            continue
        try:
            path = snapshot_team(client, team_id)
        except CHPPError as e:
            print(f"  {team_id}: FAILED - {e}")
            exit_code = 1
            continue
        manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
        ok = len(manifest["endpoints"])
        errs = len(manifest["errors"])
        name = manifest.get("team_name") or "?"
        status = f"{ok} endpoints captured"
        if errs:
            status += f", {errs} error(s): {', '.join(manifest['errors'])}"
        print(f"  {team_id} ({name}): {status}")
        print(f"    -> {path}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
