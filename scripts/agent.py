"""MIREAL SNS Agent — メインオーケストレーター

毎朝 8:00 JST に GitHub Actions cron から起動される。

実行フロー:
  1. kill_switch チェック
  2. 世情チェック（災害・大事件があれば中止）
  3. CALENDAR.md と今日の曜日からテーマ決定
  4. history.json で重複・連続フォーマット回避
  5. Claude API で投稿原稿生成
  6. 別Claude callでセルフレビュー (最大3回リトライ)
  7. PIL で画像生成
  8. 画像をリポジトリにコミット → raw URL を取得
  9. IG + FB に投稿
  10. history.json 更新 → コミット
"""
import os
import sys
import json
import re
import random
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

from anthropic import Anthropic

# 同ディレクトリのスクリプトを再利用
sys.path.insert(0, str(Path(__file__).parent))
from generate_image import generate_image          # noqa: E402
from world_check import is_safe_to_post            # noqa: E402
from post_to_meta import post_to_ig, post_to_fb    # noqa: E402
from designer import design_post                   # noqa: E402
from render_html import render_template            # noqa: E402

ROOT = Path(__file__).parent.parent
PLAYBOOK_DIR = ROOT / "playbook"
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"
KILL_SWITCH_FILE = ROOT / "kill_switch.txt"
BG_DIR = ROOT / "assets" / "backgrounds" / "processed"

JST = timezone(timedelta(hours=9))

CONTENT_MODEL = os.environ.get("CLAUDE_CONTENT_MODEL", "claude-opus-4-7")
REVIEW_MODEL = os.environ.get("CLAUDE_REVIEW_MODEL", "claude-opus-4-7")

# 週次クリエイター募集用のフォーム
RECRUIT_FORM_URL = "https://forms.gle/tUJwFQmTdDotYWN49"


# ---------- utilities ----------

def fail(msg, exit_code=1):
    print(f"❌ {msg}", flush=True)
    sys.exit(exit_code)


def ok(msg):
    print(f"✅ {msg}", flush=True)


def info(msg):
    print(f"   {msg}", flush=True)


def step(msg):
    print(f"\n=== {msg} ===", flush=True)


def check_kill_switch():
    if not KILL_SWITCH_FILE.exists():
        return
    content = KILL_SWITCH_FILE.read_text(encoding="utf-8").strip().upper()
    if "STOP" in content:
        print("🛑 kill_switch.txt = STOP → 投稿停止", flush=True)
        sys.exit(0)


def load_history():
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"posts": []}


def save_history(data):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_playbook():
    files = ["BRAND_GUIDELINE.md", "PILLARS.md", "FORMATS.md", "CALENDAR.md"]
    return {f: (PLAYBOOK_DIR / f).read_text(encoding="utf-8") for f in files}


def strip_json_fence(content):
    content = content.strip()
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    return content.strip()


def pick_background(history):
    """1枚だけ選ぶ。下位互換のため残す。"""
    bgs = pick_backgrounds(history, count=1)
    return bgs[0] if bgs else None


def pick_backgrounds(history, count: int = 1):
    """assets/backgrounds/processed/ から count 枚をランダムに選ぶ。

    直近5投稿で使われた背景は避ける（重複防止）。
    """
    if not BG_DIR.exists():
        return []
    bgs = sorted(BG_DIR.glob("bg-*.jpg"))
    if not bgs:
        return []
    recent_names = set()
    for p in history.get("posts", [])[-5:]:
        used = p.get("bgs_used") or ([p.get("bg_used")] if p.get("bg_used") else [])
        for n in used:
            if n:
                recent_names.add(n)
    candidates = [bg for bg in bgs if bg.name not in recent_names]
    if len(candidates) < count:
        candidates = bgs
    return random.sample(candidates, min(count, len(candidates)))


# ---------- core steps ----------

def recruit_theme() -> dict:
    """週次クリエイター募集投稿のテーマ (CALENDAR を使わない)"""
    now_jst = datetime.now(JST)
    return {
        "date": now_jst.strftime("%Y-%m-%d"),
        "weekday": ["月", "火", "水", "木", "金", "土", "日"][now_jst.weekday()],
        "week_num": min(((now_jst.day - 1) // 7) + 1, 4),
        "pillar": "R",
        "format": "RECRUIT",
        "theme": "クリエイター募集 - ディレクター/カメラマン/編集者/モーショングラファー",
    }


def pick_todays_theme(playbook, override_pillar=None):
    """CALENDAR.md から今日の柱・フォーマット・テーマを引く"""
    now_jst = datetime.now(JST)
    weekday = now_jst.weekday()  # 0=月, 6=日
    weekday_jp = ["月", "火", "水", "木", "金", "土", "日"][weekday]

    if weekday == 6:
        fail("日曜日は投稿スキップの設定です", exit_code=0)

    week_num = min(((now_jst.day - 1) // 7) + 1, 4)

    calendar = playbook["CALENDAR.md"]
    week_block_pattern = re.compile(
        rf"## Week {week_num}.*?\n(.+?)(?=## |\Z)",
        re.DOTALL,
    )
    m = week_block_pattern.search(calendar)
    if not m:
        info(f"Week {week_num} のテーブルが無い、Week 1 にフォールバック")
        m = re.search(r"## Week 1.*?\n(.+?)(?=## |\Z)", calendar, re.DOTALL)
        if not m:
            fail("CALENDAR.md に Week 1 が見つかりません")

    week_table = m.group(1)
    row_pattern = re.compile(
        rf"\|\s*{weekday_jp}\s*\|\s*([A-E])\s*\|\s*(F\d)\s*\|\s*([^|]+?)\s*\|"
    )
    row = row_pattern.search(week_table)
    if not row:
        fail(f"{weekday_jp}曜の行が Week {week_num} に見つかりません")

    pillar, format_, theme_text = row.group(1), row.group(2), row.group(3).strip()
    if override_pillar:
        pillar = override_pillar.upper()
        info(f"柱を強制指定: {pillar}")

    return {
        "date": now_jst.strftime("%Y-%m-%d"),
        "weekday": weekday_jp,
        "week_num": week_num,
        "pillar": pillar,
        "format": format_,
        "theme": theme_text,
    }


def generate_post(client, playbook, history, theme):
    """Claude API で投稿原稿（画像テキスト + キャプション + ハッシュタグ）を生成"""
    recent = history.get("posts", [])[-10:]
    recent_lines = [
        f"  - {p.get('date', '?')} {p.get('pillar', '?')}-{p.get('format', '?')}: {p.get('theme', '?')}"
        for p in recent
    ]
    recent_str = "\n".join(recent_lines) if recent_lines else "  (まだ無し)"

    # クリエイター募集モード (pillar=R) は別プロンプト
    if theme.get("pillar") == "R":
        return _generate_recruit_post(client, playbook, recent_str, theme)

    system_prompt = f"""あなたはMIREAL株式会社のSNS運用担当エージェントです。
以下のブランドガイドラインに**完全準拠**して、Instagram / Facebook 用の投稿を生成してください。

# BRAND GUIDELINE
{playbook['BRAND_GUIDELINE.md']}

# PILLARS
{playbook['PILLARS.md']}

# FORMATS
{playbook['FORMATS.md']}

# 出力ルール (厳守)
- 出力は **JSON のみ**、説明文・前置き・コードフェンスなし
- スキーマ:
  {{
    "heading_image": "画像中央の大文字。1-2行、合計20文字以内。改行は \\n",
    "subheading_image": "画像中央のサブ文字。1-3行、合計60文字以内。改行は \\n",
    "footer_image": "画像下のフッター。20文字以内、例: 'ONE DAY PROMOTION  |  mireal.co.jp'",
    "caption": "SNS本文。400-800字。ガイドライン準拠。改行 \\n で読みやすく",
    "hashtags": ["#動画制作", "#ONEDAYPROMOTION", ...]  // 12-15個、層別配分
  }}

# 厳守ルール
- 絵文字は使わない
- 誇大広告（「業界No.1」「絶対」「最安値」等）禁止
- 価格は ¥98,000(税別) で固定
- 政治・宗教・差別・天災・事件・競合言及は禁止
"""

    user_prompt = f"""今日のお題:
- 日付: {theme['date']}
- 曜日: {theme['weekday']} (Week {theme['week_num']})
- 訴求柱: {theme['pillar']}
- フォーマット: {theme['format']}
- カレンダー指示テーマ: 「{theme['theme']}」

直近の投稿（重複・冗長を避けるため参照）:
{recent_str}

このお題に沿った投稿原稿を JSON で生成してください。
画像のheadingは数字や強い言葉で目を引くこと。subheadingで補足。caption本文はSNSで読まれやすいように改行を入れて。
"""

    response = client.messages.create(
        model=CONTENT_MODEL,
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = response.content[0].text
    cleaned = strip_json_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        fail(f"生成応答のJSONパース失敗: {e}\n--- raw ---\n{raw}")


def _generate_recruit_post(client, playbook, recent_str, theme):
    """クリエイター募集投稿の Claude プロンプト"""
    system_prompt = f"""あなたはMIREAL株式会社の採用担当エージェントです。
週次の「映像クリエイター募集」SNS投稿を生成します。

# BRAND GUIDELINE (トーン参考)
{playbook['BRAND_GUIDELINE.md']}

# 募集の背景
- **募集職種**: ディレクター / カメラマン / 動画編集者 / モーショングラファー
- **働き方**: 案件単位での参加、フルリモート可、副業OK、全国の案件あり
- **報酬**: 案件ごとに事前提示、相場通り
- **応募方法**: Google フォーム (URLはagentが本文末尾に自動付加するので、本文中には書かない)
- **MIREALの魅力**: ONE DAY PROMOTION のような独自プロダクトに関わる、中小企業向けの実需が安定して多い、地方含む全国の現場経験ができる

# 出力ルール (厳守)
- 出力は **JSON のみ**、説明文・前置き・コードフェンスなし
- スキーマ:
  {{
    "heading_image": "画像中央の大文字。1-2行、合計20字以内。改行は \\n。例: '映像クリエイター\\n募集中'",
    "subheading_image": "画像中央のサブ文字。1-3行、合計60字以内。",
    "footer_image": "画像下のフッター。例 'CREATORS WANTED  |  mireal.co.jp'",
    "caption": "SNS本文。400-700字。応募動機を喚起、改行で読みやすく。フォームURLは本文に含めない。",
    "hashtags": ["#映像クリエイター募集", ...] // 12-15個、募集系を多めに
  }}

# 厳守ルール
- 絵文字は使わない
- 誇大広告NG（業界No.1、絶対、最高 等）
- 価格表記なし（ONE DAY PROMO ではない）
- 文末に応募ハードルを下げる一言を入れる（例：「気になった方はまずフォームから」）
- ハッシュタグには #映像クリエイター #カメラマン募集 #動画編集者募集 #モーションデザイナー募集 #フリーランス映像 #映像制作 #動画制作 等を含める
"""

    user_prompt = f"""今週のクリエイター募集投稿を JSON で生成してください。

# 今日のお題
- 日付: {theme['date']} ({theme['weekday']})
- 種別: クリエイター募集 (週1回の定期投稿)

# 直近の通常投稿（重複・冗長を避けるため参考）
{recent_str}

映像業界の人が「これは応募してみたい」と思う、具体的で誠実な投稿を作ってください。
heading_image は「目に飛び込んでくる強い言葉」にしてください。
"""

    import re as _re
    response = client.messages.create(
        model=CONTENT_MODEL,
        max_tokens=2500,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = response.content[0].text
    cleaned = strip_json_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        fail(f"募集投稿の Claude応答 JSON パース失敗: {e}\n--- raw ---\n{raw}")


def self_review(client, playbook, post):
    """別Claude callでブランド準拠審査"""
    review_prompt = f"""あなたはMIREAL社のコンプライアンス担当エージェントです。
以下のSNS投稿原稿を、ブランドガイドラインに照らして審査してください。

# BRAND GUIDELINE
{playbook['BRAND_GUIDELINE.md']}

# 投稿原稿
{json.dumps(post, ensure_ascii=False, indent=2)}

# 審査項目
1. 価格は ¥98,000(税別) で正しく表記されているか（言及されている場合）
2. 禁止トピック（政治・宗教・差別・天災・事件・競合言及）に該当しないか
3. 誇大広告（業界No.1、絶対、最安値、100%等）に該当しないか
4. NGワード（神、ヤバい、マジ等の口語スラング）が含まれていないか
5. ブランド人格（頼れる兄貴分のような、専門家風NG）から逸脱していないか
6. ハッシュタグ数は12〜15個か
7. 絵文字を使っていないか

# 出力 (JSON のみ、説明文なし)
{{
  "verdict": "PASS" or "FAIL",
  "issues": ["..."],
  "advice": "FAILの場合の修正方針"
}}
"""

    response = client.messages.create(
        model=REVIEW_MODEL,
        max_tokens=1000,
        messages=[{"role": "user", "content": review_prompt}],
    )
    raw = response.content[0].text
    cleaned = strip_json_fence(raw)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"verdict": "FAIL", "issues": ["レビュー応答パース失敗"], "advice": raw[:500]}


def git_commit_push(message, *paths):
    """指定パスをコミット&プッシュ。差分なしならスキップ。"""
    subprocess.run(["git", "config", "user.email", "agent@mireal.co.jp"], check=True)
    subprocess.run(["git", "config", "user.name", "MIREAL SNS Agent"], check=True)
    subprocess.run(["git", "add", *paths], check=True)
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    )
    if not status.stdout.strip():
        info("git: 変更なし、commit スキップ")
        return
    subprocess.run(["git", "commit", "-m", message], check=True)
    subprocess.run(["git", "push"], check=True)


def build_raw_url(repo_full_name, relative_path, branch="main"):
    return f"https://raw.githubusercontent.com/{repo_full_name}/{branch}/{relative_path}"


# ---------- main ----------

def main():
    step("MIREAL SNS Agent — Daily Post")
    print(f"Started at: {datetime.now(JST).strftime('%Y-%m-%d %H:%M:%S JST')}")

    dry_run = os.environ.get("DRY_RUN", "false").lower() == "true"
    override_pillar = (os.environ.get("FORCE_PILLAR") or "").strip() or None
    repo = os.environ.get("GH_REPO", "kato-oss/mireal-sns-agent")

    if dry_run:
        info("DRY_RUN モード: 生成のみで実投稿しない")

    # 1. Kill switch
    check_kill_switch()
    ok("kill switch OK")

    # 2. 世情チェック (SKIP_WORLD_CHECK=true で手動スキップ可)
    step("世情チェック")
    skip_world = os.environ.get("SKIP_WORLD_CHECK", "false").lower() == "true"
    if skip_world:
        info("SKIP_WORLD_CHECK=true → 世情チェックを手動スキップ")
    else:
        safe, reason = is_safe_to_post()
        print(reason)
        if not safe and not dry_run:
            print("🛑 世情NG、投稿中止", flush=True)
            sys.exit(0)

    # 3. テーマ決定 (MODE=recruit なら募集テーマ、それ以外はカレンダー)
    step("今日のテーマ決定")
    playbook = read_playbook()
    history = load_history()
    mode = (os.environ.get("MODE") or "daily").lower()
    if mode == "recruit":
        info("MODE=recruit → クリエイター募集投稿")
        theme = recruit_theme()
    else:
        theme = pick_todays_theme(playbook, override_pillar=override_pillar)
    print(json.dumps(theme, ensure_ascii=False, indent=2))

    # 4. Anthropic client
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        fail("ANTHROPIC_API_KEY 未設定")
    client = Anthropic(api_key=api_key)

    # 5. 原稿生成 + セルフレビュー（最大3回）
    step("原稿生成 + セルフレビュー")
    post = None
    for attempt in range(3):
        info(f"--- 試行 {attempt + 1}/3 ---")
        post = generate_post(client, playbook, history, theme)
        info(f"生成: heading={post.get('heading_image', '?')!r}")

        review = self_review(client, playbook, post)
        info(f"レビュー: {review.get('verdict')}")
        if review.get("verdict") == "PASS":
            ok("セルフレビュー通過")
            break
        info(f"問題: {review.get('issues')}")
        info(f"助言: {review.get('advice')}")
    else:
        fail("3回試したがセルフレビュー通過せず、投稿中止")

    # 6. デザイナーエージェントがテンプレート選択 + コピー構造化
    step("デザイナーエージェント (テンプレート選定)")
    force_tpl = (os.environ.get("FORCE_TEMPLATE") or "").strip() or None
    if force_tpl:
        info(f"FORCE_TEMPLATE={force_tpl} を強制指定")
    design = design_post(client, post, theme, model=REVIEW_MODEL, force_template=force_tpl)
    template_name = design["template"]
    design_vars = design.get("variables", {})

    info(f"テンプレート: {template_name}")
    info(f"理由: {design.get('reasoning', '')}")
    info(f"変数: {json.dumps(design_vars, ensure_ascii=False, indent=2)}")

    # 7. 背景写真選択 (テンプレ別)
    if template_name == "T_campaign":
        bg_count = 9
    elif template_name == "T_tipcard":
        bg_count = 0
    else:
        # T_listicle / T_overlay / T_softbg は 1枚
        bg_count = 1
    bgs = pick_backgrounds(history, count=bg_count) if bg_count > 0 else []
    bg_names = [b.name for b in bgs] if bgs else []
    info(f"背景: {bg_names if bg_names else '(なし)'}")

    # 8. Playwright で HTML/CSS テンプレートをレンダリング
    step("画像レンダリング (Playwright + HTML/CSS)")
    try:
        image_path = render_template(
            template_name=template_name,
            variables=design_vars,
            bg_paths=bgs if bgs else None,
        )
        ok(f"Playwright レンダリング成功: {image_path.name}")
    except Exception as e:
        info(f"Playwright失敗 ({e}) → PILフォールバック")
        image_path = generate_image(
            heading=design_vars.get("heading", design_vars.get("heading_accent", "MIREAL")),
            subheading=design_vars.get("subheading", design_vars.get("pill1_body", "")),
            footer="ONE DAY PROMOTION  |  mireal.co.jp",
            bg_image_path=bgs[0] if bgs else None,
        )
    image_relative = image_path.relative_to(ROOT).as_posix()
    ok(f"生成: {image_relative}")

    # 7. キャプション組み立て (募集モードはフォームURLを末尾に追加)
    hashtags_str = " ".join(post.get("hashtags", []))
    if theme.get("pillar") == "R":
        full_caption = (
            f"{post['caption']}\n\n"
            f"▼ 応募はこちらのフォームから（1分で完了）\n{RECRUIT_FORM_URL}\n\n"
            f"{hashtags_str}"
        ).strip()
    else:
        full_caption = f"{post['caption']}\n\n{hashtags_str}".strip()

    if dry_run:
        step("DRY_RUN 完了 — 投稿はスキップ")
        info(f"\n--- caption ---\n{full_caption}\n")
        info(f"--- image ---\n{image_path}\n")
        info(f"--- post (raw json) ---\n{json.dumps(post, ensure_ascii=False, indent=2)}")
        return

    # 8. 画像をコミット & push (raw URL用)
    step("画像をリポジトリへコミット")
    git_commit_push(f"post: {theme['date']} {theme['pillar']}-{theme['format']} image", image_relative)
    image_url = build_raw_url(repo, image_relative)
    info(f"image_url: {image_url}")

    # 9. 投稿
    step("Meta API 投稿")
    page_id = os.environ["FB_PAGE_ID"]
    page_token = os.environ["FB_PAGE_ACCESS_TOKEN"]
    ig_id = os.environ["IG_BUSINESS_ACCOUNT_ID"]

    info("[Instagram] posting…")
    ig_result = post_to_ig(ig_id, page_token, image_url, full_caption)
    ok(f"IG投稿: media_id={ig_result.get('id')}")

    info("[Facebook] posting…")
    fb_result = post_to_fb(page_id, page_token, full_caption, image_url=image_url)
    fb_post_id = fb_result.get("post_id") or fb_result.get("id")
    ok(f"FB投稿: id={fb_post_id}")

    # 10. history 更新 → commit
    step("history.json 更新")
    record = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "date": theme["date"],
        "weekday": theme["weekday"],
        "week_num": theme["week_num"],
        "pillar": theme["pillar"],
        "format": theme["format"],
        "theme": theme["theme"],
        "template": template_name,
        "heading_image": design_vars.get("heading") or (
            f"{design_vars.get('heading_lead', '')}{design_vars.get('heading_accent', '')}{design_vars.get('heading_tail', '')}"
        ),
        "caption_preview": post["caption"][:200],
        "image_url": image_url,
        "bgs_used": bg_names,
        "ig_media_id": ig_result.get("id"),
        "fb_post_id": fb_post_id,
    }
    history["posts"].append(record)
    save_history(history)
    git_commit_push(f"post: {theme['date']} history update", "data/history.json")

    print()
    ok("🎉 投稿完了")
    print(json.dumps(record, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
