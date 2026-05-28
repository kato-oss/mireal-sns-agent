"""MIREAL ブランド画像生成 (PIL ベース) v2

設計方針:
- ソリッドの濃紺背景（グラデは使わない）
- メインテキストは白、視認性最優先
- 黄色はアクセントとしてのみ少量使用（細い水平線、ブランド下のマーカー）
- タイポグラフィのヒエラルキーを明確に: heading >> subheading > footer
- 余白を十分に取り、ノイズを排除して上質さを担保
"""
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- パレット ---
BG_DEEP = (8, 28, 51)              # 濃紺 #081C33（より深く、黒に寄せた紺）
TEXT_PRIMARY = (250, 250, 250)     # メインテキスト
TEXT_DIM = (190, 200, 215)         # サブテキスト用（少し落ち着いた白）
ACCENT = (230, 255, 0)             # ブランドイエロー #E6FF00

CANVAS_SIZE = 1080
SAFE_MARGIN_X = 110
IMAGES_DIR = Path(__file__).parent.parent / "data" / "images" / "generated"

# --- フォントパス候補 ---
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
]
FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "C:/Windows/Fonts/YuGothR.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
]


def find_font_path(candidates):
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def load_font(size, bold=False):
    path = find_font_path(FONT_BOLD_CANDIDATES if bold else FONT_REGULAR_CANDIDATES)
    if not path:
        print(
            f"⚠️  Noto Sans CJK が見つかりません ({'Bold' if bold else 'Regular'})。",
            file=sys.stderr,
        )
        return ImageFont.load_default()
    return ImageFont.truetype(path, size)


def measure(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_by_width(text, font, max_width, draw):
    """日本語混在テキストを1文字ずつ折返し。明示的な \\n は尊重する。"""
    lines = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for ch in paragraph:
            test = current + ch
            w, _ = measure(draw, test, font)
            if w > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
    return lines


def auto_fit_font(
    draw, text, max_width, max_height, max_lines, base_size,
    bold=True, min_size=32, line_height_factor=1.15,
):
    """テキストが領域に収まる最大フォントサイズを段階的に探す (自動折り返しあり)"""
    size = base_size
    while size >= min_size:
        font = load_font(size, bold=bold)
        lines = wrap_by_width(text, font, max_width, draw)
        line_h = int(measure(draw, "あ", font)[1] * line_height_factor)
        total_h = line_h * len(lines)
        if len(lines) <= max_lines and total_h <= max_height:
            return font, lines, line_h
        size -= 6
    font = load_font(min_size, bold=bold)
    lines = wrap_by_width(text, font, max_width, draw)
    line_h = int(measure(draw, "あ", font)[1] * line_height_factor)
    return font, lines, line_h


def auto_fit_font_strict(
    draw, text, max_width, max_height, base_size,
    bold=True, min_size=32, line_height_factor=1.15,
):
    """改行(\\n)を尊重して、各行が max_width に収まる最大フォントサイズを返す。

    自動折り返しは一切しない（heading 用）。
    どうしても min_size でも入らなければ妥協してそのまま返す。
    """
    paragraphs = [p for p in text.split("\n") if p]
    if not paragraphs:
        paragraphs = [""]
    size = base_size
    while size >= min_size:
        font = load_font(size, bold=bold)
        max_w = max(measure(draw, p, font)[0] for p in paragraphs)
        line_h = int(measure(draw, "あ", font)[1] * line_height_factor)
        total_h = line_h * len(paragraphs)
        if max_w <= max_width and total_h <= max_height:
            return font, paragraphs, line_h
        size -= 4
    font = load_font(min_size, bold=bold)
    line_h = int(measure(draw, "あ", font)[1] * line_height_factor)
    return font, paragraphs, line_h


def draw_lines_centered(draw, lines, font, line_h, y_start, color, x_center):
    y = y_start
    for line in lines:
        w, _ = measure(draw, line, font)
        x = x_center - w // 2
        draw.text((x, y), line, font=font, fill=color)
        y += line_h
    return y


def generate_image(
    heading,
    subheading="",
    footer="MIREAL.Official  |  mireal.co.jp",
    output_path=None,
    bg_image_path=None,
    overlay_strength=0.55,
):
    """ブランド画像を生成して JPG として保存

    bg_image_path が指定されれば、その画像を背景にして暗化オーバーレイ + テキスト合成。
    指定されなければソリッドの濃紺背景にテキストのみ。
    """
    if bg_image_path:
        with Image.open(bg_image_path) as src:
            src = src.convert("RGB")
            if src.size != (CANVAS_SIZE, CANVAS_SIZE):
                src = src.resize((CANVAS_SIZE, CANVAS_SIZE), Image.LANCZOS)
            black = Image.new("RGB", src.size, (0, 0, 0))
            img = Image.blend(src, black, overlay_strength)
    else:
        img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), BG_DEEP)
    draw = ImageDraw.Draw(img)
    x_center = CANVAS_SIZE // 2

    # ============================================================
    # 1. ヘッダー: MIREAL ワードマーク + アンダーライン
    # ============================================================
    brand_text = "MIREAL"
    brand_font = load_font(30, bold=True)
    bw, bh = measure(draw, brand_text, brand_font)
    brand_y = 92
    # 文字間を広めに見せるため、letter-spacing相当の処理は省略しシンプルに
    draw.text((x_center - bw // 2, brand_y), brand_text, font=brand_font, fill=TEXT_PRIMARY)
    # 短いイエローアンダーライン (54px x 3px)
    under_y = brand_y + bh + 14
    draw.rectangle([x_center - 27, under_y, x_center + 27, under_y + 3], fill=ACCENT)

    # ============================================================
    # 2. メインコンテンツ: heading + アクセント線 + subheading
    # ============================================================
    content_max_w = CANVAS_SIZE - SAFE_MARGIN_X * 2

    # heading (strict mode: 改行を尊重、自動折返ししない)
    h_font, h_lines, h_lh = auto_fit_font_strict(
        draw, heading,
        max_width=content_max_w,
        max_height=520,
        base_size=140,
        bold=True,
        min_size=56,
        line_height_factor=1.18,
    )
    h_block_h = h_lh * len(h_lines)

    # subheading
    s_font = s_lines = s_lh = None
    s_block_h = 0
    if subheading:
        s_font, s_lines, s_lh = auto_fit_font(
            draw, subheading,
            max_width=content_max_w - 60,  # 内側に少し寄せる
            max_height=240,
            max_lines=4,
            base_size=44,
            bold=False,
            min_size=28,
            line_height_factor=1.5,
        )
        s_block_h = s_lh * len(s_lines)

    # アクセントレイアウト定数
    ACCENT_LINE_W = 80
    ACCENT_LINE_H = 3
    GAP_H_TO_LINE = 56
    GAP_LINE_TO_S = 56

    total_block_h = h_block_h
    if subheading:
        total_block_h += GAP_H_TO_LINE + ACCENT_LINE_H + GAP_LINE_TO_S + s_block_h

    # 縦方向: ブランド(下端 ~140px)とフッター(上端 ~880px)の間で中央配置
    work_top = 230
    work_bottom = 880
    y_start = work_top + (work_bottom - work_top - total_block_h) // 2

    # heading
    y = draw_lines_centered(draw, h_lines, h_font, h_lh, y_start, TEXT_PRIMARY, x_center)

    # アクセント線
    if subheading:
        y += GAP_H_TO_LINE
        draw.rectangle(
            [x_center - ACCENT_LINE_W // 2, y, x_center + ACCENT_LINE_W // 2, y + ACCENT_LINE_H],
            fill=ACCENT,
        )
        y += ACCENT_LINE_H + GAP_LINE_TO_S
        # subheading
        y = draw_lines_centered(draw, s_lines, s_font, s_lh, y, TEXT_DIM, x_center)

    # ============================================================
    # 3. フッター: 細い黄色ライン + footer text
    # ============================================================
    footer_line_y = CANVAS_SIZE - 140
    draw.rectangle(
        [x_center - 40, footer_line_y, x_center + 40, footer_line_y + 2],
        fill=ACCENT,
    )
    f_font = load_font(22, bold=False)
    fw, fh = measure(draw, footer, f_font)
    draw.text(
        (x_center - fw // 2, footer_line_y + 30),
        footer,
        font=f_font,
        fill=TEXT_DIM,
    )

    # 保存
    if output_path is None:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        output_path = IMAGES_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jpg"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="JPEG", quality=95, optimize=True, subsampling=0)
    return output_path


if __name__ == "__main__":
    # スタンドアロンテスト (背景を1枚ランダムに選ぶ)
    import random
    bg_dir = Path(__file__).parent.parent / "assets" / "backgrounds" / "processed"
    bgs = sorted(bg_dir.glob("bg-*.jpg")) if bg_dir.exists() else []
    bg = random.choice(bgs) if bgs else None
    path = generate_image(
        heading="地方の小売店\nを動画で照らす",
        subheading="全国47都道府県、出張撮影。\n地域に根ざした1日完結の動画制作。",
        footer="ONE DAY PROMOTION  |  mireal.co.jp",
        bg_image_path=bg,
    )
    print(f"Generated: {path}  (bg: {bg.name if bg else 'PIL only'})")
