"""MIREAL SNS Agent — Insights Fetch

Meta Insights API から IG + FB のパフォーマンスデータを取得し、
data/insights/ に保存する。

実行: GitHub Actions cron (毎晩 23:00 JST = 14:00 UTC) または手動
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

GRAPH_API = "https://graph.facebook.com/v21.0"
ROOT = Path(__file__).parent.parent
INSIGHTS_DIR = ROOT / "data" / "insights"
POSTS_DIR = INSIGHTS_DIR / "posts"
TIMELINE_FILE = INSIGHTS_DIR / "account_timeline.jsonl"
SUMMARY_FILE = INSIGHTS_DIR / "summary.md"
HISTORY_FILE = ROOT / "data" / "history.json"

# IG メディア毎の取得メトリクス
IG_MEDIA_METRICS = "reach,likes,comments,shares,saved,total_interactions"


# ---------- utils ----------

def get_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        print(f"❌ {name} not set", flush=True)
        sys.exit(1)
    return v


def ok(msg):
    print(f"✅ {msg}", flush=True)


def info(msg):
    print(f"   {msg}", flush=True)


def warn(msg):
    print(f"⚠️  {msg}", flush=True)


# ---------- fetchers ----------

def fetch_ig_media_insights(media_id: str, token: str) -> dict | None:
    """1つの IG 投稿の insights を取得"""
    r = requests.get(
        f"{GRAPH_API}/{media_id}/insights",
        params={"access_token": token, "metric": IG_MEDIA_METRICS},
        timeout=15,
    )
    if r.status_code != 200:
        warn(f"IG media {media_id}: HTTP {r.status_code} {r.text[:160]}")
        return None
    data = r.json().get("data", [])
    return {item["name"]: item["values"][0]["value"] for item in data if item.get("values")}


def fetch_ig_account(ig_id: str, token: str) -> dict:
    """IG ビジネスアカウントの現状値とインサイトを取得"""
    result = {}

    # 1) プロフィールから follower数・投稿数
    r = requests.get(
        f"{GRAPH_API}/{ig_id}",
        params={
            "access_token": token,
            "fields": "username,followers_count,follows_count,media_count",
        },
        timeout=15,
    )
    if r.status_code == 200:
        j = r.json()
        result["username"] = j.get("username")
        result["followers"] = j.get("followers_count")
        result["follows"] = j.get("follows_count")
        result["media_count"] = j.get("media_count")
    else:
        warn(f"IG profile: HTTP {r.status_code} {r.text[:160]}")

    # 2) account-level insights (前日 1日分)
    r = requests.get(
        f"{GRAPH_API}/{ig_id}/insights",
        params={
            "access_token": token,
            "metric": "reach,profile_views,website_clicks",
            "period": "day",
            "metric_type": "total_value",
        },
        timeout=15,
    )
    if r.status_code == 200:
        for item in r.json().get("data", []):
            name = item.get("name")
            tv = item.get("total_value", {})
            if "value" in tv:
                result[name] = tv["value"]
    else:
        warn(f"IG insights: HTTP {r.status_code} {r.text[:160]}")

    return result


def fetch_fb_page(page_id: str, token: str) -> dict:
    """FB ページの現状値"""
    r = requests.get(
        f"{GRAPH_API}/{page_id}",
        params={
            "access_token": token,
            "fields": "name,fan_count,followers_count",
        },
        timeout=15,
    )
    if r.status_code != 200:
        warn(f"FB page: HTTP {r.status_code} {r.text[:160]}")
        return {}
    j = r.json()
    return {
        "name": j.get("name"),
        "followers": j.get("followers_count") or j.get("fan_count"),
        "fan_count": j.get("fan_count"),
    }


# ---------- summary ----------

def write_markdown_summary(snapshot: dict, history_recent: list):
    """data/insights/summary.md に人間向けサマリーを書く"""
    lines = []
    lines.append("# MIREAL SNS — Insights Summary")
    lines.append("")
    lines.append(f"_Last updated: {snapshot['date']} UTC_")
    lines.append("")
    lines.append("## Account")
    lines.append("")
    ig = snapshot.get("ig", {})
    fb = snapshot.get("fb", {})
    lines.append(f"| Platform | Followers | Reach (1d) | Profile views (1d) | Website clicks (1d) |")
    lines.append(f"|---|---|---|---|---|")
    lines.append(
        f"| **Instagram** @{ig.get('username', 'mireal_inc')} | "
        f"{ig.get('followers', '—')} | "
        f"{ig.get('reach', '—')} | "
        f"{ig.get('profile_views', '—')} | "
        f"{ig.get('website_clicks', '—')} |"
    )
    lines.append(f"| **Facebook** {fb.get('name', 'MIREAL.Official')} | {fb.get('followers', '—')} | — | — | — |")
    lines.append("")

    # 過去14日の投稿パフォーマンス
    posts = snapshot.get("posts", [])
    if posts:
        lines.append("## Recent Posts (last 30d)")
        lines.append("")
        lines.append("| Date | Pillar | Template | Reach | Likes | Saved | Comments | Shares |")
        lines.append("|---|---|---|---|---|---|---|---|")
        for p in sorted(posts, key=lambda x: x.get("date", ""), reverse=True):
            m = p.get("metrics", {}) or {}
            lines.append(
                f"| {p.get('date', '?')} | {p.get('pillar', '?')} | {p.get('template', '?')} | "
                f"{m.get('reach', '—')} | {m.get('likes', '—')} | {m.get('saved', '—')} | "
                f"{m.get('comments', '—')} | {m.get('shares', '—')} |"
            )
        lines.append("")

        # Top 3 by reach
        sorted_posts = sorted(
            [p for p in posts if (p.get("metrics") or {}).get("reach") is not None],
            key=lambda p: p["metrics"]["reach"],
            reverse=True,
        )[:3]
        if sorted_posts:
            lines.append("### 🏆 Top 3 by reach")
            lines.append("")
            for i, p in enumerate(sorted_posts, 1):
                m = p["metrics"]
                lines.append(
                    f"{i}. **{p.get('date', '?')}** ({p.get('pillar', '?')}-{p.get('template', '?')}) — "
                    f"reach **{m.get('reach')}**, saved {m.get('saved', 0)}, likes {m.get('likes', 0)}"
                )
            lines.append("")

    SUMMARY_FILE.write_text("\n".join(lines), encoding="utf-8")


# ---------- main ----------

def main():
    print("=" * 60)
    print("MIREAL SNS Agent — Insights Fetch")
    print("=" * 60)

    page_token = get_env("FB_PAGE_ACCESS_TOKEN")
    ig_id = get_env("IG_BUSINESS_ACCOUNT_ID")
    fb_page_id = get_env("FB_PAGE_ID")

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    INSIGHTS_DIR.mkdir(parents=True, exist_ok=True)
    POSTS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Account-level snapshot
    print("\n[1/3] Account snapshot")
    ig_account = fetch_ig_account(ig_id, page_token)
    fb_page = fetch_fb_page(fb_page_id, page_token)
    info(
        f"IG @{ig_account.get('username', '?')}: followers={ig_account.get('followers')}, "
        f"reach(1d)={ig_account.get('reach')}, "
        f"profile_views(1d)={ig_account.get('profile_views')}, "
        f"website_clicks(1d)={ig_account.get('website_clicks')}"
    )
    info(f"FB {fb_page.get('name', '?')}: followers={fb_page.get('followers')}")

    # 2. Per-post insights (last 30 days)
    print("\n[2/3] Per-post insights (last 30d)")
    history = {}
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            warn("history.json parse error")

    posts = history.get("posts", [])
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    recent = []
    for p in posts:
        ig_media_id = p.get("ig_media_id")
        if not ig_media_id:
            continue
        try:
            ts = datetime.fromisoformat(p["timestamp"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if ts < cutoff:
            continue
        recent.append(p)

    if not recent:
        info("対象投稿なし (まだ投稿していない or 30日以内なし)")

    post_snapshots = []
    for p in recent:
        metrics = fetch_ig_media_insights(p["ig_media_id"], page_token)
        if metrics is None:
            continue
        info(
            f"{p.get('date', '?')} ({p.get('pillar', '?')}-{p.get('template', '?')}): "
            f"reach={metrics.get('reach')}, likes={metrics.get('likes')}, "
            f"saved={metrics.get('saved')}, comments={metrics.get('comments')}, shares={metrics.get('shares')}"
        )
        post_snapshots.append({
            "date": p.get("date"),
            "ig_media_id": p["ig_media_id"],
            "pillar": p.get("pillar"),
            "format": p.get("format"),
            "template": p.get("template"),
            "metrics": metrics,
        })

    # 3. Save
    print("\n[3/3] Save")
    snapshot = {
        "date": today,
        "ig": ig_account,
        "fb": fb_page,
        "posts": post_snapshots,
    }

    daily_path = POSTS_DIR / f"{today}.json"
    daily_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    info(f"Saved: {daily_path}")

    # timeline jsonl に1行追記（重複防止のため、同日があれば置換）
    timeline_lines = []
    if TIMELINE_FILE.exists():
        for line in TIMELINE_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
                if e.get("date") == today:
                    continue  # 今日のは新しく書く
                timeline_lines.append(line)
            except json.JSONDecodeError:
                pass
    new_entry = {
        "date": today,
        "ig_followers": ig_account.get("followers"),
        "ig_reach_1d": ig_account.get("reach"),
        "ig_profile_views_1d": ig_account.get("profile_views"),
        "ig_website_clicks_1d": ig_account.get("website_clicks"),
        "ig_media_count": ig_account.get("media_count"),
        "fb_followers": fb_page.get("followers"),
        "posts_tracked": len(post_snapshots),
    }
    timeline_lines.append(json.dumps(new_entry, ensure_ascii=False))
    TIMELINE_FILE.write_text("\n".join(timeline_lines) + "\n", encoding="utf-8")
    info(f"Timeline: {TIMELINE_FILE} ({len(timeline_lines)} entries)")

    # markdown summary
    write_markdown_summary(snapshot, recent)
    info(f"Summary: {SUMMARY_FILE}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
