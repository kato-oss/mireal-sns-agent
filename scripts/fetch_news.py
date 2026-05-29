"""海外の映像機材ニュース RSS フィードから記事を取得する

機材レビュー / 新製品情報 / 編集ソフト更新 に特化。
記事の og:image (製品写真) も抽出して返す。
"""
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser
import requests

# 海外の映像機材/プロダクション RSS フィード (機材寄せ)
RSS_FEEDS = [
    ("DPReview",         "https://www.dpreview.com/feeds/news.xml"),
    ("PetaPixel",        "https://petapixel.com/feed/"),
    ("NoFilmSchool",     "https://nofilmschool.com/rss.xml"),
    ("CineD",            "https://www.cined.com/feed/"),
    ("Newsshooter",      "https://www.newsshooter.com/feed/"),
    ("ProVideoCoalition","https://www.provideocoalition.com/feed/"),
    ("Engadget",         "https://www.engadget.com/rss.xml"),
]

# 機材関連のキーワード（タイトル/サマリーに含まれていればOK）
VIDEO_KEYWORDS = [
    # 機材一般
    "camera", "lens", "drone", "gimbal", "stabilizer", "tripod",
    "microphone", "audio recorder", "monitor", "light", "lighting",
    "ssd", "memory card", "rig",
    # メーカー・ブランド
    "sony", "canon", "panasonic", "nikon", "fujifilm", "fuji",
    "sigma", "tamron", "samyang", "leica", "blackmagic", "red",
    "arri", "dji", "atomos", "smallrig", "tilta",
    "rode", "sennheiser", "shure", "zoom", "tascam",
    "godox", "aputure", "nanlite",
    # AI動画
    "ai video", "runway", "sora", "pika", "luma", "stable video",
    "veo", "kling", "minimax",
    # 編集ソフト
    "premiere", "davinci", "final cut", "fcpx", "after effects",
    "resolve", "video editing", "color grading",
    "raw", "log", "codec", "prores",
    # アクション
    "review", "hands-on", "first look", "tested", "comparison",
    "release", "announcement", "launch", "unveil", "introduces",
    "specs", "features", "update",
    # 業界
    "cinematography", "filmmaker", "videographer",
]

# 投稿に向かないトピックを含む記事は除外
NEGATIVE_KEYWORDS = [
    "horror", "slasher", "killer", "murder", "homicide", "killing",
    "violence", "violent", "blood", "gore", "torture",
    "death", "dying", "corpse", "shooting victim", "shootings",
    "war", "weapon", "rifle", "missile", "soldier",
    "politics", "political", "election", "president", "congress",
    "trump", "biden", "putin",
    "crime", "criminal", "arrested", "indicted", "lawsuit",
    "fraud", "scam", "scandal", "abuse",
    "porn", "pornography", "sexual", "nude",
    "obituary", "funeral", "tragedy",
    "fatal", "fatality", "casualties",
]


def extract_summary(entry) -> str:
    text = entry.get("summary") or entry.get("description") or ""
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:600]


def fetch_og_image(article_url: str, timeout: int = 15) -> Optional[str]:
    """記事ページから og:image (製品写真) を抽出"""
    try:
        r = requests.get(
            article_url,
            timeout=timeout,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; MIREAL-SNS/1.0)",
                "Accept": "text/html,application/xhtml+xml,*/*",
            },
        )
        if r.status_code != 200:
            return None
        html = r.text

        # og:image (priority)
        for pat in [
            r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
            r'<meta[^>]+name=["\']twitter:image(?::src)?["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']twitter:image(?::src)?["\']',
        ]:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                url = m.group(1).strip()
                if url and not url.startswith("data:") and url.startswith(("http://", "https://")):
                    return url
    except Exception:
        pass
    return None


def fetch_articles(hours: int = 72, max_per_feed: int = 30) -> list[dict]:
    """過去X時間以内の映像機材関連記事を取得 (og:image は agent側で個別に取得)"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    articles = []

    for source, url in RSS_FEEDS:
        try:
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"  Failed to fetch {source}: {e}")
            continue
        if not feed.entries:
            continue

        for entry in feed.entries[:max_per_feed]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    published = None
            if not published:
                published = datetime.now(timezone.utc)
            if published < cutoff:
                continue

            title = entry.get("title", "").strip()
            summary = extract_summary(entry)
            url_field = entry.get("link", "")
            if not title or not url_field:
                continue

            full_text = (title + " " + summary).lower()
            if not any(kw in full_text for kw in VIDEO_KEYWORDS):
                continue
            if any(neg in full_text for neg in NEGATIVE_KEYWORDS):
                continue

            articles.append({
                "source": source,
                "title": title,
                "summary": summary,
                "url": url_field,
                "published": published.isoformat(),
            })

    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles


if __name__ == "__main__":
    articles = fetch_articles(hours=72)
    print(f"Found {len(articles)} gear-related articles in last 72h\n")
    for i, a in enumerate(articles[:20], 1):
        print(f"[{i}] {a['source']} ({a['published'][:10]})")
        print(f"    {a['title']}")
        og = fetch_og_image(a["url"])
        print(f"    OG image: {og[:100] if og else '(none)'}")
        print(f"    URL: {a['url']}")
        print()
