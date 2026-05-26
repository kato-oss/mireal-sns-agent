"""MIREAL SNS Agent — Meta (IG + FB) 投稿ライブラリ

環境変数:
  TARGET                  both | ig | fb       (デフォルト: both)
  CAPTION                 投稿本文              (必須)
  IMAGE_URL               画像URL (HTTPS公開)   (IGは必須、FBは任意)
  FB_PAGE_ID              FBページID
  FB_PAGE_ACCESS_TOKEN    無期限Pageトークン
  IG_BUSINESS_ACCOUNT_ID  IGビジネスアカウントID

GitHub Actions の 02-test-post.yml / 03-daily-post.yml から呼ばれる。

kill_switch.txt が STOP の場合は即終了する。
"""
import os
import sys
import time
import json
from pathlib import Path

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
KILL_SWITCH = Path(__file__).parent.parent / "kill_switch.txt"
HISTORY = Path(__file__).parent.parent / "data" / "history.json"


def fail(msg):
    print(f"❌ {msg}", flush=True)
    sys.exit(1)


def ok(msg):
    print(f"✅ {msg}", flush=True)


def info(msg):
    print(f"   {msg}", flush=True)


def check_kill_switch():
    """kill_switch.txt が STOP なら投稿停止"""
    try:
        content = KILL_SWITCH.read_text(encoding="utf-8").strip().upper()
    except FileNotFoundError:
        return
    if "STOP" in content:
        print("🛑 kill_switch.txt = STOP → 投稿を中止します", flush=True)
        sys.exit(0)


def post_to_fb(page_id: str, page_token: str, message: str, image_url: str | None = None) -> dict:
    """Facebookページに投稿。

    image_url があれば /photos、なければ /feed エンドポイント。
    """
    if image_url:
        endpoint = f"{GRAPH_API}/{page_id}/photos"
        params = {
            "access_token": page_token,
            "url": image_url,
            "message": message,
        }
    else:
        endpoint = f"{GRAPH_API}/{page_id}/feed"
        params = {
            "access_token": page_token,
            "message": message,
        }
    r = requests.post(endpoint, params=params, timeout=60)
    if r.status_code != 200:
        fail(f"FB post failed (HTTP {r.status_code}): {r.text}")
    return r.json()


def post_to_ig(ig_id: str, page_token: str, image_url: str, caption: str) -> dict:
    """Instagram Business アカウントに画像投稿（2段階）

    Step 1: media container を作成
    Step 2: container が FINISHED になるまで待つ
    Step 3: media_publish で公開
    """
    # Step 1: Create container
    r = requests.post(
        f"{GRAPH_API}/{ig_id}/media",
        params={
            "access_token": page_token,
            "image_url": image_url,
            "caption": caption,
        },
        timeout=60,
    )
    if r.status_code != 200:
        fail(f"IG container create failed (HTTP {r.status_code}): {r.text}")
    container_id = r.json().get("id")
    if not container_id:
        fail(f"IG container create returned no id: {r.text}")
    info(f"IG container created: {container_id}")

    # Step 2: Poll until FINISHED (最大30秒)
    for attempt in range(15):
        r = requests.get(
            f"{GRAPH_API}/{container_id}",
            params={"access_token": page_token, "fields": "status_code"},
            timeout=10,
        )
        if r.status_code != 200:
            fail(f"IG container status check failed: {r.text}")
        status = r.json().get("status_code")
        info(f"IG container status (attempt {attempt + 1}/15): {status}")
        if status == "FINISHED":
            break
        if status == "ERROR":
            fail(f"IG container went to ERROR: {r.json()}")
        if status == "EXPIRED":
            fail(f"IG container EXPIRED before publish: {r.json()}")
        time.sleep(2)
    else:
        fail("IG container did not reach FINISHED within 30s")

    # Step 3: Publish
    r = requests.post(
        f"{GRAPH_API}/{ig_id}/media_publish",
        params={
            "access_token": page_token,
            "creation_id": container_id,
        },
        timeout=60,
    )
    if r.status_code != 200:
        fail(f"IG publish failed (HTTP {r.status_code}): {r.text}")
    return r.json()


def append_history(record: dict):
    """data/history.json に投稿記録を追記"""
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(HISTORY.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {"posts": []}
    data["posts"].append(record)
    HISTORY.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    check_kill_switch()

    target = os.environ.get("TARGET", "both").lower().strip()
    caption = os.environ.get("CAPTION", "").strip()
    image_url = os.environ.get("IMAGE_URL", "").strip()

    if not caption:
        fail("CAPTION is required")
    if target not in ("both", "ig", "fb"):
        fail(f"TARGET must be one of: both, ig, fb (got: {target!r})")

    page_id = os.environ.get("FB_PAGE_ID")
    page_token = os.environ.get("FB_PAGE_ACCESS_TOKEN")
    ig_id = os.environ.get("IG_BUSINESS_ACCOUNT_ID")
    if not (page_id and page_token and ig_id):
        fail("FB_PAGE_ID / FB_PAGE_ACCESS_TOKEN / IG_BUSINESS_ACCOUNT_ID は必須です")

    print("=" * 60)
    print("MIREAL SNS Agent — Post")
    print("=" * 60)
    print(f"Target:    {target}")
    print(f"Caption:   {caption[:120]}{'…' if len(caption) > 120 else ''}")
    print(f"Image URL: {image_url or '(none)'}")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
    print()

    record = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "target": target,
        "caption": caption,
        "image_url": image_url,
        "results": {},
    }

    # Instagram
    if target in ("ig", "both"):
        if not image_url:
            fail("IG への投稿には IMAGE_URL が必須です")
        print("[Instagram]")
        ig_result = post_to_ig(ig_id, page_token, image_url, caption)
        media_id = ig_result.get("id", "(unknown)")
        ok(f"IG posted: media_id={media_id}")
        record["results"]["instagram"] = {"media_id": media_id}
        print()

    # Facebook
    if target in ("fb", "both"):
        print("[Facebook]")
        fb_result = post_to_fb(page_id, page_token, caption, image_url=image_url or None)
        post_id = fb_result.get("post_id") or fb_result.get("id", "(unknown)")
        ok(f"FB posted: id={post_id}")
        record["results"]["facebook"] = {"post_id": post_id}
        print()

    append_history(record)
    print("=" * 60)
    print("🎉 POST COMPLETED")
    print("=" * 60)
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
