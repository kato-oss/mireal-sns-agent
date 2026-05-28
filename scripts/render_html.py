"""HTML/CSS テンプレートを Playwright で 1080x1080 JPG にレンダリングする

使い方:
    from render_html import render_template
    path = render_template(
        template_name="T1_magazine",
        variables={"heading": "...", "subheading": "...", "footer": "..."},
        bg_path=Path("assets/backgrounds/processed/bg-001.jpg"),
        output_path=Path("data/images/generated/2026-05-28.jpg"),
    )
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).parent.parent
TEMPLATES_DIR = ROOT / "templates"
IMAGES_DIR = ROOT / "data" / "images" / "generated"

CANVAS_SIZE = 1080


def list_templates():
    """templates/*.html のID（拡張子なし）リストを返す"""
    if not TEMPLATES_DIR.exists():
        return []
    return sorted([p.stem for p in TEMPLATES_DIR.glob("*.html")])


def substitute(template_html: str, variables: dict) -> str:
    """{{key}} を value に置換。改行は <br> に変換。"""
    out = template_html
    for key, value in variables.items():
        if value is None:
            value = ""
        # heading/subheading の \n を HTML 改行に
        rendered = str(value).replace("\n", "<br>")
        out = out.replace("{{" + key + "}}", rendered)
    return out


async def _render(html: str, output_path: Path, quality: int = 92):
    """Playwright で HTML をスクリーンショット

    file:// の背景画像を正しくロードするため、HTML を ROOT 配下に一時保存して
    goto() で開く。set_content() は about:blank コンテキストになり file:// URL が
    制約されるため使わない。
    """
    # HTML をプロジェクトルート配下の一時パスに保存
    tmp_html = ROOT / ".render_tmp.html"
    tmp_html.write_text(html, encoding="utf-8")
    tmp_url = tmp_html.resolve().as_uri()

    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": CANVAS_SIZE, "height": CANVAS_SIZE},
            device_scale_factor=1,
        )
        page = await context.new_page()
        try:
            await page.goto(tmp_url, wait_until="networkidle")
            # フォントと画像の読込完了を待つ
            try:
                await page.evaluate("document.fonts.ready")
            except Exception:
                pass
            # 念のため少し待機（背景画像の描画用）
            await page.wait_for_timeout(500)
            await page.screenshot(
                path=str(output_path),
                type="jpeg",
                quality=quality,
                full_page=False,
                clip={"x": 0, "y": 0, "width": CANVAS_SIZE, "height": CANVAS_SIZE},
            )
        finally:
            await browser.close()
            try:
                tmp_html.unlink()
            except Exception:
                pass


def render_template(
    template_name: str,
    variables: dict,
    bg_paths=None,
    output_path: Path | None = None,
) -> Path:
    """テンプレートをレンダリングして JPG を保存、パスを返す

    bg_paths:
      - None: 背景なし
      - Path: 単一背景。{{bg_url}} で参照
      - list[Path]: 複数背景。{{bg_url_0}}, {{bg_url_1}}, ... と {{bg_url}}(=bg_url_0)
    """
    template_path = TEMPLATES_DIR / f"{template_name}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    html = template_path.read_text(encoding="utf-8")

    # bg_paths を list に正規化
    if bg_paths is None:
        paths = []
    elif isinstance(bg_paths, (str, Path)):
        paths = [Path(bg_paths)]
    else:
        paths = [Path(p) for p in bg_paths]

    for i, p in enumerate(paths):
        p = p.resolve()
        if not p.exists():
            raise FileNotFoundError(f"Background not found: {p}")
        variables[f"bg_url_{i}"] = p.as_uri()
    variables["bg_url"] = paths[0].resolve().as_uri() if paths else ""

    html = substitute(html, variables)

    if output_path is None:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        from datetime import datetime
        output_path = IMAGES_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jpg"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    asyncio.run(_render(html, output_path))
    return output_path


if __name__ == "__main__":
    # スタンドアロンテスト
    import random
    tpls = list_templates()
    if not tpls:
        print("No templates found", file=sys.stderr)
        sys.exit(1)
    bg_dir = ROOT / "assets" / "backgrounds" / "processed"
    bgs = sorted(bg_dir.glob("bg-*.jpg")) if bg_dir.exists() else []
    tpl = sys.argv[1] if len(sys.argv) > 1 else random.choice(tpls)
    # T_campaign は 9 枚使う、それ以外は 1 枚
    if tpl.startswith("T_campaign") and len(bgs) >= 9:
        chosen_bgs = random.sample(bgs, 9)
    else:
        chosen_bgs = [random.choice(bgs)] if bgs else []

    path = render_template(
        template_name=tpl,
        variables={
            "heading_lead": "中小企業の動画は",
            "heading_accent": "¥98,000",
            "heading_tail": "から",
            "pill1_tag": "速度",
            "pill1_body": "1日で完結",
            "pill2_tag": "価格",
            "pill2_body": "税別 ¥98,000",
            "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
            "heading": "地方の小売店\nを動画で照らす",
            "subheading": "全国47都道府県、出張撮影。\n地域に根ざした1日完結の動画制作。",
        },
        bg_paths=chosen_bgs,
    )
    print(f"Generated: {path}  (template: {tpl}, bgs: {len(chosen_bgs)})")
