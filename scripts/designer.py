"""Claude をシニアアートディレクターとして駆動し、テンプレ選択 + コピー再構成を行う

T_campaign は「リード + アクセント数字 + テール + 2つのピル」の構造化フォーマット。
"""
import json
import re

# 現在優先するテンプレ（高品質、参考デザイン水準）
PREMIUM_TEMPLATES = {
    "T_campaign": (
        "3x3 写真コラージュ背景 + 中央クリームカード + アクセント色の数字 + 2つのピル型タグ。"
        "ONE DAY PROMOTION のキャンペーン感が出る。価格訴求・スピード訴求・全国対応に最強。"
    ),
}

# 既存（低優先、フォールバック）
LEGACY_TEMPLATES = {
    "T1_magazine": "マガジン表紙風、シンプル",
    "T2_split": "スプリット 写真左 + パネル右",
    "T3_card": "白カードオンフォト",
    "T4_band": "ボトムバンド",
    "T5_minimal": "センター・ミニマル",
}


def strip_json_fence(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def design_post(client, post: dict, theme: dict, model: str) -> dict:
    """Claude にデザインさせる

    出力 (T_campaign 用):
    {
      "template": "T_campaign",
      "heading_lead": "中小企業の動画は",
      "heading_accent": "¥98,000",
      "heading_tail": "から",
      "pill1_tag": "速度",
      "pill1_body": "1日で完結",
      "pill2_tag": "価格",
      "pill2_body": "税別 ¥98,000",
      "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
      "reasoning": "..."
    }
    """
    prompt = f"""あなたはMIREALのシニアアートディレクターです。
今日のSNS投稿のために、以下の構造でデザインを設計してください。

# 投稿内容（参考）
- pillar: {theme['pillar']} (A=スピード, B=価格, C=中小企業フィット, D=専門性, E=全国対応)
- format: {theme['format']}
- カレンダー指示: {theme['theme']}
- 元の heading: {post.get('heading_image', '')!r}
- 元の subheading: {post.get('subheading_image', '')!r}
- caption先頭: {post.get('caption', '')[:200]!r}

# 使うテンプレート
**T_campaign**: 3x3写真コラージュ背景 + クリームカード + リード文 + 大きなアクセント語 + テール文 + 2つのピル型タグ

このテンプレは「キャッチコピーをリード/アクセント/テールに3分割する」構造です。
例:
  リード: "中小企業の動画は"
  アクセント: "¥98,000"  (←大きく目を引く部分、数字や強い言葉)
  テール: "から"

または:
  リード: "撮影から納品まで"
  アクセント: "1日"
  テール: "で完結"

または:
  リード: "全国の中小企業へ"
  アクセント: "47都道府県"
  テール: "対応"

# 設計ルール
- heading_lead: 8〜16文字（リード文）
- heading_accent: 2〜10文字（最も視覚的に強い言葉、数字推奨）
- heading_tail: 1〜8文字（締めの言葉、無くてもOK）
- pill1_tag / pill2_tag: 2〜4文字（カテゴリ名、例: "速度" "価格" "対応エリア" "実績" "サポート"）
- pill1_body / pill2_body: 4〜10文字（具体数値や端的フレーズ、例: "1日で完結" "税別¥98,000" "全47都道府県"）
- 2つのピルは pillar に沿った相補的な内容にする（柱Bなら 価格+速度、柱Eなら 対応エリア+スピード等）
- 誇大広告NG、価格は ¥98,000(税別) で固定
- footer は固定: "ONE DAY PROMOTION  |  mireal.co.jp"

# 出力 (JSONのみ、説明文や前置きなし)
{{
  "template": "T_campaign",
  "heading_lead": "...",
  "heading_accent": "...",
  "heading_tail": "...",
  "pill1_tag": "...",
  "pill1_body": "...",
  "pill2_tag": "...",
  "pill2_body": "...",
  "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
  "reasoning": "なぜこの構成にしたか（30〜60字）"
}}
"""

    response = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    cleaned = strip_json_fence(raw)
    try:
        result = json.loads(cleaned)
    except json.JSONDecodeError:
        # フォールバック
        return {
            "template": "T_campaign",
            "heading_lead": "中小企業の動画は",
            "heading_accent": "¥98,000",
            "heading_tail": "から",
            "pill1_tag": "速度",
            "pill1_body": "1日で完結",
            "pill2_tag": "価格",
            "pill2_body": "税別¥98,000",
            "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
            "reasoning": "designer JSONパース失敗、デフォルトにフォールバック",
        }
    result.setdefault("template", "T_campaign")
    result.setdefault("footer", "ONE DAY PROMOTION  |  mireal.co.jp")
    return result
