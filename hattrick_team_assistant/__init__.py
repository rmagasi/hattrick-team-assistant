"""
Hattrick Team Assistant - personal CHPP helper library.

Public entry point:
    from hattrick_team_assistant import CHPPClient, snapshot_team
    client = CHPPClient.from_credentials_file(".chpp-credentials.json")
    me = client.team_details(158111)
    snapshot_team(client, 158111)   # archive a point-in-time capture

Run OAuth bootstrap (one-time) with:
    python -m hattrick_team_assistant.auth

Capture a team snapshot from the command line with:
    python -m hattrick_team_assistant.snapshot 158111
"""

from .chpp import CHPPClient, CHPPError
from .snapshot import snapshot_team

__all__ = ["CHPPClient", "CHPPError", "snapshot_team"]
__version__ = "0.2.0"
