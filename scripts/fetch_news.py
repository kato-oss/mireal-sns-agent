"""海外の映像ニュース RSS フィードから記事を取得する

複数のフィードから取得 → 映像関連キーワードでフィルタ → 過去72時間以内に絞る
"""
from datetime import datetime, timezone, timedelta
from typing import Optional

import feedparser

# 海外の映像/テック RSS フィード
RSS_FEEDS = [
    ("TheVerge",         "https://www.theverge.com/rss/index.xml"),
    ("NoFilmSchool",     "https://nofilmschool.com/rss.xml"),
    ("TechCrunch",       "https://techcrunch.com/feed/"),
    ("Engadget",         "https://www.engadget.com/rss.xml"),
    ("VentureBeat",      "https://venturebeat.com/feed/"),
    ("PetaPixel",        "https://petapixel.com/feed/"),
    ("DPReview",         "https://www.dpreview.com/feeds/news.xml"),
]

# 映像関連のキーワード（タイトル/サマリーに含まれていればOK）
VIDEO_KEYWORDS = [
    # 一般
    "video", "film", "filmmaker", "filmmaking", "cinematography", "cinematographer",
    "videographer", "videography",
    # 編集ソフト
    "premiere", "davinci", "final cut", "fcpx", "after effects",
    "video editing", "video editor", "color grading",
    # AI動画
    "ai video", "runway", "sora", "pika", "luma", "stable video",
    "veo", "kling", "minimax",
    # カメラ機材
    "sony alpha", "sony fx", "canon eos r", "blackmagic", "red camera",
    "atomos", "dji", "drone", "gimbal", "ronin",
    # 配信・SNS
    "youtube", "tiktok", "reels", "shorts", "streaming",
    "creator economy",
    # 業界
    "video marketing", "viral video", "video ad",
]

# 投稿に向かないトピックを含む記事は除外 (ブランド毀損リスク回避)
NEGATIVE_KEYWORDS = [
    # 暴力的・恐怖系コンテンツ
    "horror", "slasher", "killer", "murder", "homicide", "killing",
    "violence", "violent", "blood", "gore", "torture",
    "death", "dying", "corpse", "shooting",
    # 戦争・武器
    "war", "weapon", "gun", "rifle", "missile", "soldier",
    # 政治
    "politics", "political", "election", "president", "congress", "senator",
    "trump", "biden", "putin", "xi jinping",
    # 犯罪
    "crime", "criminal", "arrested", "indicted", "lawsuit",
    "fraud", "scam", "scandal", "abuse",
    # 性的コンテンツ
    "porn", "pornography", "sexual", "nude", "nudity",
    # 訃報・事故
    "obituary", "funeral", "tragedy", "tragic",
    "fatal", "fatality", "casualties",
]


def parse_date_safe(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        # feedparser がほとんどケースで struct_time を published_parsed に入れてくれる
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(s)
    except Exception:
        return None


def extract_summary(entry) -> str:
    """記事のサマリーをプレーンテキストで取得 (HTMLタグは除去)"""
    import re
    text = entry.get("summary") or entry.get("description") or ""
    text = re.sub(r"<[^>]+>", "", text)  # HTMLタグ除去
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:600]


def fetch_articles(hours: int = 72, max_per_feed: int = 30) -> list[dict]:
    """過去X時間以内の映像関連記事を取得"""
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
            # 公開時刻チェック
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                except Exception:
                    published = None
            if not published:
                published = parse_date_safe(entry.get("published"))
            if not published:
                published = datetime.now(timezone.utc)

            if published < cutoff:
                continue

            title = entry.get("title", "").strip()
            summary = extract_summary(entry)
            url_field = entry.get("link", "")

            if not title or not url_field:
                continue

            # キーワードフィルタ
            full_text = (title + " " + summary).lower()
            if not any(kw in full_text for kw in VIDEO_KEYWORDS):
                continue
            # ネガティブキーワード除外 (ブランド毀損リスク回避)
            if any(neg in full_text for neg in NEGATIVE_KEYWORDS):
                continue

            articles.append({
                "source": source,
                "title": title,
                "summary": summary,
                "url": url_field,
                "published": published.isoformat(),
            })

    # 新しい順にソート
    articles.sort(key=lambda a: a["published"], reverse=True)
    return articles


if __name__ == "__main__":
    # スタンドアロン実行: 取得した記事を確認
    articles = fetch_articles(hours=72)
    print(f"Found {len(articles)} video-related articles in last 72h\n")
    for i, a in enumerate(articles[:20], 1):
        print(f"[{i}] {a['source']} ({a['published'][:10]})")
        print(f"    {a['title']}")
        print(f"    {a['url']}")
        print()
