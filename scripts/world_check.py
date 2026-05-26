"""世情チェック — 災害・大事件の発生時は投稿を抑制

NHKニュースRSSから最新ヘッドラインを取得し、危険キーワードがあれば投稿停止。
"""
import sys
import urllib.request
import xml.etree.ElementTree as ET

NHK_NEWS_RSS = "https://www3.nhk.or.jp/rss/news/cat0.xml"

# 投稿停止すべきトピックのキーワード
DANGER_KEYWORDS = [
    # 災害
    "震度", "津波", "地震", "噴火", "豪雨", "大雨特別警報", "土砂崩れ",
    "原発事故",
    # 事件・事故
    "殺人", "殺害", "刺殺", "射殺", "誘拐",
    "墜落", "脱線", "炎上事故", "爆発事故",
    "テロ", "爆弾",
    # 政治・国際
    "戦争", "ミサイル発射", "侵攻",
    # 訃報
    "訃報", "ご逝去", "死去",
    # 感染症
    "感染拡大", "緊急事態宣言",
]


def fetch_recent_headlines(rss_url=NHK_NEWS_RSS, limit=15, timeout=10):
    """NHK RSSから直近のヘッドライン一覧を取得"""
    try:
        req = urllib.request.Request(
            rss_url,
            headers={"User-Agent": "MIREAL-SNS-Agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as response:
            xml_text = response.read()
    except Exception as e:
        print(f"⚠️  ニュース取得失敗: {e}")
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"⚠️  RSSパース失敗: {e}")
        return []

    headlines = []
    for item in root.iter("item"):
        title_el = item.find("title")
        if title_el is not None and title_el.text:
            headlines.append(title_el.text.strip())
        if len(headlines) >= limit:
            break
    return headlines


def is_safe_to_post():
    """投稿してよいか判定。

    Returns: (safe: bool, reason: str)
    """
    headlines = fetch_recent_headlines()
    if not headlines:
        # フェッチ失敗時は過剰自粛を避け、投稿を許可する
        return True, "ニュース取得不可、投稿を継続"

    triggered = []
    for headline in headlines:
        for kw in DANGER_KEYWORDS:
            if kw in headline:
                triggered.append({"keyword": kw, "headline": headline})
                break

    if triggered:
        examples = triggered[:3]
        reason_lines = ["世情NG。検出した危険トピック:"]
        for t in examples:
            reason_lines.append(f"  - [{t['keyword']}] {t['headline']}")
        return False, "\n".join(reason_lines)

    return True, f"世情OK ({len(headlines)} 件のヘッドラインを精査、危険キーワード無し)"


if __name__ == "__main__":
    safe, reason = is_safe_to_post()
    print(f"{'✅' if safe else '🛑'} {reason}")
    sys.exit(0 if safe else 1)
