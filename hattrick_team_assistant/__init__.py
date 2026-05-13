"""
Hattrick Team Assistant - personal CHPP helper library.

Public entry point:
    from hattrick_team_assistant import CHPPClient
    client = CHPPClient.from_credentials_file(".chpp-credentials.json")
    me = client.team_details(158111)

Run OAuth bootstrap (one-time) with:
    python -m hattrick_team_assistant.auth
"""

from .chpp import CHPPClient, CHPPError

__all__ = ["CHPPClient", "CHPPError"]
__version__ = "0.1.0"
