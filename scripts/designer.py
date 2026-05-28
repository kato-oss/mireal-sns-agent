"""Claude をシニアデザイナーとして駆動し、テンプレート選択 + 微調整を行う

このエージェントは原稿(heading/subheading) と pillar/format を見て、
最も合うテンプレートを選び、必要なら text を微調整する。
"""
import json
import re

TEMPLATE_DESCRIPTIONS = {
    "T1_magazine": (
        "マガジン表紙風。写真フル背景、下部に向かって濃紺グラデで重く、"
        "ヘッドラインは画面下半分に大胆配置。"
        "情緒的・編集的なテーマ向き。事例紹介・ストーリーテリングに最適。"
    ),
    "T2_split": (
        "スプリット編集。左46%が写真、右54%が濃紺の独立パネルでテキスト。"
        "情報整理感が出る。専門性アピール・裏側紹介・FAQに最適。"
    ),
    "T3_card": (
        "フローティングカード。写真を背景に、中央に白いカードを浮かべて"
        "ダーク文字でタイポを置く。明るく信頼感のあるトーン。"
        "価格訴求・サービス紹介・差別化ポイントに最適。"
    ),
    "T4_band": (
        "ボトムバンド。写真が上半分(50%)、下半分が濃紺バーで白文字。"
        "雑誌の見開き感、ビジュアル重視。"
        "ブランドメッセージ・ビジョン訴求・余白で語るテーマに最適。"
    ),
    "T5_minimal": (
        "センター・ミニマル。写真は重く暗化(82%)し、中央に巨大な見出し。"
        "宣言文・マニフェスト感。"
        "強いステートメント・問題提起・キャッチーな1フレーズ訴求に最適。"
    ),
}


def strip_json_fence(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def design_post(client, post: dict, theme: dict, model: str) -> dict:
    """Claude にテンプレートを選ばせる

    入力: post (heading_image, subheading_image, caption, hashtags),
          theme (pillar, format, theme, weekday)
    出力: {"template": "T1_magazine", "heading": "...", "subheading": "...",
           "footer": "...", "reasoning": "..."}
    """
    tpl_listing = "\n".join(
        f"- **{tid}**: {desc}" for tid, desc in TEMPLATE_DESCRIPTIONS.items()
    )

    prompt = f"""あなたはMIREALのシニアアートディレクターです。
今日のSNS投稿に**最適なデザインテンプレート**を選び、画像上に載せるテキストを微調整してください。

# 投稿内容
- pillar: {theme['pillar']} (A=スピード, B=価格, C=中小企業フィット, D=専門性, E=全国対応)
- format: {theme['format']}
- カレンダー指示: {theme['theme']}
- 元の heading: {post.get('heading_image', '')!r}
- 元の subheading: {post.get('subheading_image', '')!r}
- caption先頭: {post.get('caption', '')[:200]!r}

# 利用可能なテンプレート
{tpl_listing}

# 判断ルール
- pillar B (価格) や 数字キャッチーな内容 → T3_card / T5_minimal が映える
- pillar D (専門性) / 事例詳細 → T2_split が情報整理に強い
- 事例紹介 / 情緒的・ストーリーテリング → T1_magazine / T4_band
- 強い1フレーズ・宣言文 → T5_minimal
- ビジュアル重視・余白で語る → T4_band

# テキスト微調整のルール（テンプレ毎の文字数制約）
- T1_magazine, T3_card, T4_band: heading 1行あたり最大 **10文字**、最大2行 (合計20字以内)
- T2_split: 表示エリアが狭いため heading 1行あたり最大 **6文字**、最大3行 (合計18字以内)
- T5_minimal: heading 1行あたり最大 **8文字**、最大2行 (合計16字以内)
- 上記を超える場合は heading を短縮して**パンチライン化**する (印象的な凝縮した言葉に)
- subheading は 60文字以内、改行で読みやすく
- footer は固定: "ONE DAY PROMOTION  |  mireal.co.jp"

# 出力 (JSONのみ、説明文や前置きなし)
{{
  "template": "T1_magazine" など利用可能IDのいずれか,
  "heading": "画像に乗せる最終ヘッドライン（改行は \\n）",
  "subheading": "画像に乗せる最終サブテキスト（改行は \\n）",
  "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
  "reasoning": "なぜこのテンプレートを選んだか（30〜80字）"
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
        # フォールバック: 元のテキストでT1にする
        return {
            "template": "T1_magazine",
            "heading": post.get("heading_image", ""),
            "subheading": post.get("subheading_image", ""),
            "footer": post.get("footer_image", "ONE DAY PROMOTION  |  mireal.co.jp"),
            "reasoning": "designer JSONパース失敗、T1にフォールバック",
        }
    # テンプレート名の妥当性チェック
    if result.get("template") not in TEMPLATE_DESCRIPTIONS:
        result["template"] = "T1_magazine"
        result.setdefault("reasoning", "")
        result["reasoning"] += " (テンプレ未定義のためT1フォールバック)"
    return result
