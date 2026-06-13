"""Seed a local admin AppUser for the dashboard.

Pre-creates a local admin account in ``.arr-mcp-users.json`` so the
manual-testing skill can sign in immediately, without walking through
``/auth/setup`` on every fresh stack. Idempotent: skips if any AppUser
already exists.

Usage::

    uv run python scripts/seed_users.py
    uv run python scripts/seed_users.py --services-dir PATH \
        --username admin --password password123
"""

from __future__ import annotations

import argparse

from arr_mcp.services.users import UserStore

DEFAULT_SERVICES_DIR = "test-stack/data"
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "password123"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--services-dir",
        default=DEFAULT_SERVICES_DIR,
        help=(
            "Directory containing .arr-mcp-users.json "
            f"(default: {DEFAULT_SERVICES_DIR})"
        ),
    )
    parser.add_argument(
        "--username",
        default=DEFAULT_USERNAME,
        help=f"Local admin username (default: {DEFAULT_USERNAME})",
    )
    parser.add_argument(
        "--password",
        default=DEFAULT_PASSWORD,
        help=f"Local admin password (default: {DEFAULT_PASSWORD})",
    )
    args = parser.parse_args()

    store = UserStore(args.services_dir)
    if store.has_any():
        print("AppUser already exists — skipping seed.")
        return

    store.create_local(args.username, args.password, is_admin=True)
    print(f"Seeded local admin account: {args.username} / {args.password}")


if __name__ == "__main__":
    main()
