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
    """Playwright で HTML をスクリーンショット"""
    async with async_playwright() as p:
        browser = await p.chromium.launch(args=["--no-sandbox"])
        context = await browser.new_context(
            viewport={"width": CANVAS_SIZE, "height": CANVAS_SIZE},
            device_scale_factor=1,
        )
        page = await context.new_page()
        await page.set_content(html, wait_until="networkidle")
        # フォント読込完了を待つ
        try:
            await page.evaluate("document.fonts.ready")
        except Exception:
            pass
        await page.screenshot(
            path=str(output_path),
            type="jpeg",
            quality=quality,
            full_page=False,
            clip={"x": 0, "y": 0, "width": CANVAS_SIZE, "height": CANVAS_SIZE},
        )
        await browser.close()


def render_template(
    template_name: str,
    variables: dict,
    bg_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    """テンプレートをレンダリングして JPG を保存、パスを返す"""
    template_path = TEMPLATES_DIR / f"{template_name}.html"
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")

    html = template_path.read_text(encoding="utf-8")

    # bg_url の決定（file:// URL）
    if bg_path:
        bg_path = Path(bg_path).resolve()
        if not bg_path.exists():
            raise FileNotFoundError(f"Background not found: {bg_path}")
        bg_url = bg_path.as_uri()
    else:
        bg_url = ""
    variables = {**variables, "bg_url": bg_url}

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
    bg = random.choice(bgs) if bgs else None

    path = render_template(
        template_name=tpl,
        variables={
            "heading": "地方の小売店\nを動画で照らす",
            "subheading": "全国47都道府県、出張撮影。\n地域に根ざした1日完結の動画制作。",
            "footer": "ONE DAY PROMOTION  |  mireal.co.jp",
        },
        bg_path=bg,
    )
    print(f"Generated: {path}  (template: {tpl}, bg: {bg.name if bg else 'none'})")
