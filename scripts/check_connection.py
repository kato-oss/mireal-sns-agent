"""MIREAL SNS Agent — Connection Test

Meta Graph API への接続と権限を検証する。投稿は一切しない。
GitHub Actions の 01-connection-test.yml から実行される。
"""
import os
import sys
import json
from datetime import datetime, timezone

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"

REQUIRED_ENV = [
    "META_APP_ID",
    "META_APP_SECRET",
    "FB_PAGE_ID",
    "FB_PAGE_ACCESS_TOKEN",
    "IG_BUSINESS_ACCOUNT_ID",
    "ANTHROPIC_API_KEY",
]

REQUIRED_SCOPES = {
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_comments",
    "instagram_manage_insights",
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "pages_manage_metadata",
}


def fail(msg):
    print(f"❌ {msg}", flush=True)
    sys.exit(1)


def ok(msg):
    print(f"✅ {msg}", flush=True)


def warn(msg):
    print(f"⚠️  {msg}", flush=True)


def get_env(name):
    val = os.environ.get(name)
    if not val:
        fail(f"Environment variable {name} is not set")
    return val


def main():
    print("=" * 60)
    print("MIREAL SNS Agent — Connection Test")
    print("=" * 60)

    # 1. 環境変数の存在確認
    print("\n[1/5] Checking environment variables…")
    env = {name: get_env(name) for name in REQUIRED_ENV}
    ok(f"All {len(REQUIRED_ENV)} required env vars are set")

    # 2. Page token の有効性確認 (GET /me)
    print("\n[2/5] Verifying Page token via /me…")
    r = requests.get(
        f"{GRAPH_API}/me",
        params={
            "access_token": env["FB_PAGE_ACCESS_TOKEN"],
            "fields": "id,name,category",
        },
        timeout=10,
    )
    if r.status_code != 200:
        fail(f"Page token invalid (HTTP {r.status_code}): {r.text}")
    me = r.json()
    if me.get("id") != env["FB_PAGE_ID"]:
        fail(
            f"Token belongs to id={me.get('id')!r} but FB_PAGE_ID={env['FB_PAGE_ID']!r}. "
            "GitHub Secretsの設定を見直してください。"
        )
    ok(f"Page token valid → {me.get('name')!r} (category: {me.get('category')!r})")

    # 3. Facebookページ詳細取得
    print("\n[3/5] Fetching Facebook Page detail…")
    r = requests.get(
        f"{GRAPH_API}/{env['FB_PAGE_ID']}",
        params={
            "access_token": env["FB_PAGE_ACCESS_TOKEN"],
            "fields": "name,fan_count,followers_count,link",
        },
        timeout=10,
    )
    if r.status_code != 200:
        fail(f"Cannot read FB page detail (HTTP {r.status_code}): {r.text}")
    page = r.json()
    fb_followers = page.get("followers_count", "n/a")
    ok(f"FB Page reachable → followers={fb_followers}, url={page.get('link', 'n/a')}")

    # 4. Instagram Business Account 詳細取得
    print("\n[4/5] Fetching Instagram Business Account…")
    r = requests.get(
        f"{GRAPH_API}/{env['IG_BUSINESS_ACCOUNT_ID']}",
        params={
            "access_token": env["FB_PAGE_ACCESS_TOKEN"],
            "fields": "username,name,biography,followers_count,follows_count,media_count",
        },
        timeout=10,
    )
    if r.status_code != 200:
        fail(f"Cannot read IG account (HTTP {r.status_code}): {r.text}")
    ig = r.json()
    ok(
        f"IG account reachable → @{ig.get('username')} "
        f"followers={ig.get('followers_count')} posts={ig.get('media_count')}"
    )

    # 5. Token の debug (有効期限と権限スコープ)
    print("\n[5/5] Debugging token (expiry & scopes)…")
    r = requests.get(
        f"{GRAPH_API}/debug_token",
        params={
            "input_token": env["FB_PAGE_ACCESS_TOKEN"],
            "access_token": f"{env['META_APP_ID']}|{env['META_APP_SECRET']}",
        },
        timeout=10,
    )
    if r.status_code != 200:
        fail(f"Cannot debug token (HTTP {r.status_code}): {r.text}")
    debug = r.json().get("data", {})

    expires_at = debug.get("expires_at", 0)
    if expires_at == 0:
        ok("Token is permanent (no expiry) ✨")
    else:
        exp = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        warn(
            f"Token expires at {exp.isoformat()}. "
            "Page tokenとして取得し直すと無期限になります。"
        )

    granted = set(debug.get("scopes", []))
    missing = REQUIRED_SCOPES - granted
    if missing:
        warn(f"Missing scopes: {sorted(missing)}")
        warn("Meta App → ユースケース → カスタマイズで権限を追加してください。")
    else:
        ok(f"All required scopes granted ({len(granted)} total)")

    # Anthropic key の形式チェック (ネットワーク呼び出しはしない)
    if env["ANTHROPIC_API_KEY"].startswith("sk-ant-"):
        ok("ANTHROPIC_API_KEY format looks valid")
    else:
        warn("ANTHROPIC_API_KEY does not start with 'sk-ant-' — typo の可能性")

    # サマリ
    print("\n" + "=" * 60)
    print("CONNECTION TEST PASSED ✅")
    print("=" * 60)
    summary = {
        "facebook_page": {
            "id": me.get("id"),
            "name": me.get("name"),
            "followers": fb_followers,
        },
        "instagram_account": {
            "username": ig.get("username"),
            "followers": ig.get("followers_count"),
            "media_count": ig.get("media_count"),
        },
        "token_permanent": expires_at == 0,
        "scopes_count": len(granted),
        "missing_scopes": sorted(missing) if missing else [],
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
