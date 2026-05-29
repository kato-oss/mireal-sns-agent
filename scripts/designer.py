"""Claude をシニアアートディレクターとして駆動し、テンプレ選択 + 変数生成を行う

4つの高品質テンプレから content に最適なものを Claude が選び、
そのテンプレが要求する変数を生成する。
"""
import json
import re


TEMPLATE_SPECS = {
    "T_campaign": {
        "desc": (
            "9枚の写真コラージュ背景 + 中央クリームカード + ブランド行 + "
            "リード文/巨大アクセント語/テール文の3分割ヘッドライン + 2つのピル型タグ。"
            "ONE DAY のキャンペーン訴求、価格・スピード・全国対応のキーポイント並列訴求に最適。"
        ),
        "best_for": "柱B(価格)+柱A(速度)同時訴求、柱E(全国)、構造的アピール",
        "variables_schema": {
            "heading_lead": "8〜16字。リード文 例: '中小企業の動画は'",
            "heading_accent": "2〜10字。最も視覚的に強い言葉、数字推奨 例: '¥98,000'",
            "heading_tail": "1〜8字。締めの言葉、省略可 例: 'から'",
            "pill1_tag": "2〜4字。例: '速度'",
            "pill1_body": "4〜10字。例: '1日で完結'",
            "pill2_tag": "2〜4字。例: '価格'",
            "pill2_body": "4〜10字。例: '税別¥98,000'",
            "footer": "固定 'ONE DAY PROMOTION  |  mireal.co.jp'",
        },
    },
    "T_listicle": {
        "desc": (
            "暗化した写真背景 + 上部に白ピル型タグ + 大きな見出し + "
            "超巨大な数字+選 のアクセント + 下に保存ブックマークタグ。"
            "「X選」「X個」「X理由」など、Tips型カルーセル(F1)に最強。"
        ),
        "best_for": "柱A/C/D Tips系。'失敗する5つの理由' '知らないと損する3つ' 等",
        "variables_schema": {
            "top_tag": "6〜14字。例: '中小企業必見' 'プロが教える'",
            "heading": "1〜2行、合計15〜26字。改行は \\n。例: '動画制作で失敗する\\n本当の理由'",
            "number": "1〜2桁の数字。例: '5' '7' '3'",
            "number_suffix": "1〜3字。'選' '個' '理由' '方法'",
            "footer": "固定 'ONE DAY PROMOTION  |  mireal.co.jp'",
        },
    },
    "T_overlay": {
        "desc": (
            "写真背景の上に白い角丸カードが中央配置。上部に黒い小タグ。"
            "カード内: 大見出し + 赤いディバイダー + 説明文。"
            "Howto系、宣言型、ガイド系に最適。"
        ),
        "best_for": "柱C(中小企業フィット)、How-to/Guide、'XXする方法' '誰でもできるXX'",
        "variables_schema": {
            "top_tag": "4〜10字。例: '誰でもできる' '中小企業向け'",
            "heading": "1〜2行、合計14〜24字。改行は \\n。例: '予算20万円で\\n動画を作る方法'",
            "subheading": "30〜70字、改行で読みやすく。",
            "footer": "固定",
        },
    },
    "T_tipcard": {
        "desc": (
            "クリーム色の無地背景 + 角に装飾ライン + 中央に 'POINT' バッジ + "
            "大見出し + 説明文。写真を使わない、教育/ナレッジ系の上品なカード。"
            "F1 Tips型/F4 制作裏側 で写真をあえて使わないクリーンな訴求に。"
        ),
        "best_for": "柱D(専門性)、知識訴求、'XXとは' 'XXの仕組み'",
        "variables_schema": {
            "badge": "3〜8字。'POINT' 'CHECK' '専門家解説' '裏話' 等",
            "heading": "1〜2行、合計14〜22字。改行は \\n。",
            "subheading": "30〜60字。",
            "footer": "固定",
        },
    },
    "T_softbg": {
        "desc": (
            "クリーム背景に写真を22%不透明度でテクスチャとして重ねる + "
            "Serif (明朝系) フォントでタイポを上品に組む + 中央センター配置。"
            "雑誌スプレッド/編集デザインの高級感。写真の主張を抑えて、文字で語る。"
        ),
        "best_for": "ブランドメッセージ系、ビジョン訴求、感情的・情緒的なメッセージ、"
                    "「動画でビジネスを動かす」など本質訴求",
        "variables_schema": {
            "label": "上部の小ラベル、英字推奨 6〜18字。例: 'CREATIVE STUDIO' 'EDITORIAL' 'BUSINESS VISION'",
            "heading": "1〜2行、合計14〜22字。Serifで描画されるので情緒的に。",
            "subheading": "30〜70字。",
            "footer": "固定",
        },
    },
}


def strip_json_fence(content: str) -> str:
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def design_post(client, post: dict, theme: dict, model: str, force_template: str | None = None) -> dict:
    # force_template が指定されていれば、そのテンプレだけを Claude に見せる
    if force_template and force_template in TEMPLATE_SPECS:
        active_specs = {force_template: TEMPLATE_SPECS[force_template]}
    else:
        active_specs = TEMPLATE_SPECS

    tpl_listing_lines = []
    for tid, spec in active_specs.items():
        schema_lines = "\n    ".join(f"- {k}: {v}" for k, v in spec["variables_schema"].items())
        tpl_listing_lines.append(
            f"## {tid}\n"
            f"  概要: {spec['desc']}\n"
            f"  最適: {spec['best_for']}\n"
            f"  必要変数:\n    {schema_lines}"
        )
    tpl_listing = "\n\n".join(tpl_listing_lines)

    force_note = ""
    if force_template:
        force_note = f"\n# 制約\n強制指定: **{force_template}** を必ず使用する。下記の選定ルールは無視し、このテンプレに合うようにコピーを最適化する。\n"

    prompt = f"""あなたはMIREALのシニアアートディレクターです。
今日のSNS投稿のために、最適なテンプレを選び、そのテンプレに必要な変数を全て生成してください。
{force_note}

# 投稿内容
- pillar: {theme['pillar']} (A=スピード, B=価格, C=中小企業フィット, D=専門性, E=全国対応)
- format: {theme['format']} (F1=Tips型カルーセル, F2=数字インパクト, F3=リールBA, F4=リール裏側, F5=事例紹介)
- カレンダー指示テーマ: {theme['theme']}
- 元の heading: {post.get('heading_image', '')!r}
- 元の subheading: {post.get('subheading_image', '')!r}
- caption先頭: {post.get('caption', '')[:200]!r}

# 利用可能なテンプレート

{tpl_listing}

# 選定ルール
- format F1 (Tips型カルーセル) → **T_listicle** (X選パターン) を最優先
- format F2 (数字インパクト) → **T_campaign** (リード+アクセント数字+ピル構造)
- format F5 (事例紹介) → **T_overlay** (写真+白カード) または **T_campaign**
- 柱D 専門性訴求で写真より概念訴求 → **T_tipcard** (無地クリーム)
- 情緒的・ブランドメッセージ・本質訴求 → **T_softbg** (Serif編集デザイン)
- **pillar R (クリエイター募集)** → **T_overlay** (写真+白カード、求人広告感) または **T_tipcard** (無地クリーンな募集案内) または **T_campaign** (構造化された募集情報)。T_listicle (X選) と T_softbg (情緒的) は避ける。heading は「映像クリエイター 募集」固定なので、T_campaign の場合は heading_lead='映像クリエイター' / heading_accent='募集' / heading_tail='' とする。
- **pillar N (海外映像ニュース)** → **T_listicle** (上部 'VIDEO NEWS' タグ + 大見出し) または **T_overlay** (写真+白カードでニュース感) または **T_softbg** (Serif編集デザインで雑誌風) を推奨。T_campaign (キャンペーン感が強い) は避ける。top_tag は「海外ニュース」「VIDEO NEWS」「FILM TECH」等を使う。
- 柱A/B/C/Eで写真ベース → **T_listicle** or **T_overlay** or **T_campaign**
- 連続して同じテンプレを使わない（直近 history を確認できる場合）

# 出力 (JSONのみ、説明文や前置きなし、コードフェンスなし)
{{
  "template": "T_listicle" など利用可能IDのいずれか,
  "variables": {{ ... 選んだテンプレートの変数を全部 ... }},
  "reasoning": "なぜこのテンプレを選んだか・なぜこのコピーにしたか（30〜80字）"
}}

# 厳守ルール
- 価格は **¥98,000(税別)** で固定
- 誇大広告NG（業界No.1/絶対/最安値/100% は使わない）
- 絵文字は使わない
- footer は固定: "ONE DAY PROMOTION  |  mireal.co.jp"
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
        # フォールバック: T_listicle にデフォルト値
        return {
            "template": "T_listicle",
            "variables": {
                "top_tag": "中小企業必見",
                "heading": "1日で動画ができる\n本当の理由",
                "number": "3",
                "number_suffix": "つ",
                "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
            },
            "reasoning": "designer JSONパース失敗、T_listicleにフォールバック",
        }

    # 必須項目の確認
    if result.get("template") not in TEMPLATE_SPECS:
        result["template"] = "T_listicle"
    if "variables" not in result or not isinstance(result.get("variables"), dict):
        result["variables"] = {}
    # footer は固定値で上書き保証
    result["variables"]["footer"] = "ONE DAY PROMOTION  |  mireal.co.jp"
    return result
