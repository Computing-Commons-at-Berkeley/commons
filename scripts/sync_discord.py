"""CLI wrapper: create missing Discord roles/categories/channels.

Usage:
    python scripts/sync_discord.py --dry-run
    python scripts/sync_discord.py

Reads community/config/discord.yaml via COMMUNITY_REPO_PATH. Never deletes
objects that exist in Discord but not in the config.
"""

from __future__ import annotations

from commons.discord.sync import main

if __name__ == "__main__":
    raise SystemExit(main())
