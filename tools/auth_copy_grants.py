"""Copy camera grants from the old Auth Server to the new one (docs/AUTH_V2_PLAN.md), once, before switching a
site to AUTH_PROVIDER=oidc. Run from central_manager/ (it uses central's .env, database and the snvr-a client):

    cd central_manager
    py ../tools/auth_copy_grants.py            # dry run: shows what would be copied and what can't be matched
    py ../tools/auth_copy_grants.py --apply    # write the copies

Grants are COPIED, never moved: the legacy rows stay, so switching back to AUTH_PROVIDER=legacy still works.
* role grants: the old role name -> the new role id with the same name (case-insensitive);
* user grants: the old user id -> its username (from the audit log, where every sign-in left one) -> the new
  user with that username -> its sub.
A subject that already has oidc grants is skipped (the Access page wins). Anything unmatched is listed: give it
on the Access page by hand.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())  # central_manager/

from auth_sdk import AuthSDK  # noqa: E402
from tortoise import Tortoise  # noqa: E402

from app.access.models import AccessGrant  # noqa: E402
from app.audit.models import AuditEvent  # noqa: E402
from database.config import TORTOISE_ORM  # noqa: E402
from settings.settings import settings  # noqa: E402


async def main(apply: bool) -> int:
    if not settings.AUTH_OIDC_CLIENT_SECRET:
        print("AUTH_OIDC_CLIENT_SECRET is empty in .env")
        return 1
    sdk = AuthSDK(settings.AUTH_ISSUER, settings.AUTH_APP_KEY, settings.AUTH_OIDC_CLIENT_ID,
                  settings.AUTH_OIDC_CLIENT_SECRET, api_url=settings.AUTH_API_URL or None)
    try:
        roles = await sdk.roles()
        members = await sdk.list_all_members()
    finally:
        await sdk.stop()
    role_ids = {str(r["name"]).lower(): str(r["id"]) for r in roles}
    subs = {str(m["username"]).lower(): str(m["sub"]) for m in members}
    print(f"New Auth Server: {len(roles)} roles, {len(members)} members")

    await Tortoise.init(config=TORTOISE_ORM)
    try:
        legacy = await AccessGrant.filter(auth_source="legacy")
        done = {(g.subject_type, g.subject) for g in await AccessGrant.filter(auth_source="oidc")}
        usernames: dict[str, str] = {}
        for user_id, username in await AuditEvent.filter(user_id__not_isnull=True).exclude(auth_source="oidc") \
                .order_by("id").values_list("user_id", "username"):
            usernames[str(user_id)] = username  # latest wins

        by_subject: dict[tuple[str, str], list[AccessGrant]] = {}
        for g in legacy:
            by_subject.setdefault((g.subject_type, g.subject), []).append(g)

        copies, unmatched = [], []
        for (subject_type, subject), grants in sorted(by_subject.items()):
            if subject_type == "role":
                target, shown = role_ids.get(subject.lower()), f"role {subject}"
            else:
                name = usernames.get(subject)
                target, shown = (subs.get(name.lower()) if name else None), f"user {subject} ({name or 'unknown'})"
            if target is None:
                unmatched.append(shown)
                continue
            if (subject_type, target) in done:
                print(f"  skip  {shown}: already has grants on the new server")
                continue
            print(f"  copy  {shown} -> {target}: {len(grants)} grant row(s)")
            copies += [AccessGrant(subject_type=subject_type, subject=target, auth_source="oidc",
                                   all_cameras=g.all_cameras, group_id=g.group_id, camera_id=g.camera_id)
                       for g in grants]
        for shown in unmatched:
            print(f"  NO MATCH  {shown}: give it on the Access page")
        if apply and copies:
            await AccessGrant.bulk_create(copies)
        print(f"{'Copied' if apply else 'Would copy'} {len(copies)} row(s); {len(unmatched)} subject(s) unmatched"
              + ("" if apply else ". Run with --apply to write."))
        return 0
    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write the copies (default: dry run)")
    sys.exit(asyncio.run(main(ap.parse_args().apply)))
