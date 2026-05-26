"""MIREAL ブランド画像生成（PIL ベース）

入力: heading / subheading / footer
出力: data/images/generated/{YYYY-MM-DD}.jpg (1080x1080)

ブランドルール:
- 背景: 紺 #0A2540
- アクセント: 蛍光イエロー #E6FF00
- 左端に縦のアクセントライン
- 中央に大見出し（黄色）+ サブ見出し（白）
- 下部にフッター（黄色）
"""
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BRAND_NAVY = (10, 37, 64)         # #0A2540
BRAND_YELLOW = (230, 255, 0)      # #E6FF00
BRAND_WHITE = (245, 245, 245)
BRAND_NAVY_LIGHT = (24, 56, 92)   # subtle gradient用

CANVAS_SIZE = 1080
IMAGES_DIR = Path(__file__).parent.parent / "data" / "images" / "generated"

# 各環境でのフォントパス候補
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
            f"⚠️  Noto Sans CJK が見つかりません ({'Bold' if bold else 'Regular'})。"
            f"日本語が描画できない可能性があります。",
            file=sys.stderr,
        )
        return ImageFont.load_default()
    return ImageFont.truetype(path, size)


def measure(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_by_width(text, font, max_width, draw):
    """日本語混在テキストを1文字ずつ折り返す"""
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


def auto_fit_font(draw, text, max_width, max_height, max_lines, base_size, bold=True, min_size=32):
    """テキストが領域に収まる最大のフォントサイズを二分探索的に決める"""
    size = base_size
    while size >= min_size:
        font = load_font(size, bold=bold)
        lines = wrap_by_width(text, font, max_width, draw)
        line_h = int(measure(draw, "あ", font)[1] * 1.4)
        total_h = line_h * len(lines)
        if len(lines) <= max_lines and total_h <= max_height:
            return font, lines, line_h
        size -= 6
    # 最小でも入らなければそのまま返す
    font = load_font(min_size, bold=bold)
    lines = wrap_by_width(text, font, max_width, draw)
    line_h = int(measure(draw, "あ", font)[1] * 1.4)
    return font, lines, line_h


def draw_lines(draw, lines, font, line_h, y_start, color, max_width, x_center):
    y = y_start
    for line in lines:
        w, _ = measure(draw, line, font)
        x = x_center - w // 2
        draw.text((x, y), line, font=font, fill=color)
        y += line_h
    return y


def make_background(img):
    """微細グラデーション + 左端アクセントライン"""
    draw = ImageDraw.Draw(img)
    # 縦グラデーション
    for y in range(CANVAS_SIZE):
        t = y / CANVAS_SIZE
        r = int(BRAND_NAVY[0] * (1 - t) + BRAND_NAVY_LIGHT[0] * t)
        g = int(BRAND_NAVY[1] * (1 - t) + BRAND_NAVY_LIGHT[1] * t)
        b = int(BRAND_NAVY[2] * (1 - t) + BRAND_NAVY_LIGHT[2] * t)
        draw.line([(0, y), (CANVAS_SIZE, y)], fill=(r, g, b))
    # 左端アクセントライン
    draw.rectangle([0, 0, 18, CANVAS_SIZE], fill=BRAND_YELLOW)
    # 右下にロゴ的なドット
    draw.ellipse([CANVAS_SIZE - 70, CANVAS_SIZE - 70, CANVAS_SIZE - 40, CANVAS_SIZE - 40], fill=BRAND_YELLOW)


def generate_image(heading, subheading="", footer="MIREAL.Official  |  mireal.co.jp", output_path=None):
    """ブランド画像を生成して保存。output_path を返す。"""
    img = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), BRAND_NAVY)
    make_background(img)
    draw = ImageDraw.Draw(img)

    x_center = CANVAS_SIZE // 2
    inner_padding = 80
    content_max_width = CANVAS_SIZE - inner_padding * 2

    # HEADING (中央、大きく、黄色)
    h_font, h_lines, h_lh = auto_fit_font(
        draw, heading,
        max_width=content_max_width,
        max_height=400,
        max_lines=3,
        base_size=128,
        bold=True,
        min_size=56,
    )
    heading_total = h_lh * len(h_lines)

    # SUBHEADING (中央、中サイズ、白)
    sub_font = sub_lines = sub_lh = sub_total = None
    if subheading:
        sub_font, sub_lines, sub_lh = auto_fit_font(
            draw, subheading,
            max_width=content_max_width,
            max_height=240,
            max_lines=4,
            base_size=52,
            bold=False,
            min_size=28,
        )
        sub_total = sub_lh * len(sub_lines)

    # 縦中央配置: heading + 区切り + subheading 全体を中央に置く
    gap = 50 if subheading else 0
    block_total = heading_total + gap + (sub_total or 0)
    y_start = (CANVAS_SIZE - block_total) // 2 - 40  # 少し上寄り（フッタースペース確保）

    y = draw_lines(draw, h_lines, h_font, h_lh, y_start, BRAND_YELLOW, content_max_width, x_center)
    if subheading:
        y += gap
        y = draw_lines(draw, sub_lines, sub_font, sub_lh, y, BRAND_WHITE, content_max_width, x_center)

    # FOOTER (下から96pxの位置)
    f_font = load_font(28, bold=True)
    fw, fh = measure(draw, footer, f_font)
    draw.text((x_center - fw // 2, CANVAS_SIZE - 96), footer, font=f_font, fill=BRAND_YELLOW)

    if output_path is None:
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        output_path = IMAGES_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.jpg"
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, format="JPEG", quality=92, optimize=True)
    return output_path


if __name__ == "__main__":
    # スタンドアロンでテスト実行
    path = generate_image(
        heading="¥98,000で\n1日完結",
        subheading="動画制作の業界平均60〜80万円。\nそれを8〜10分の1で、即日納品。",
        footer="ONE DAY PROMOTION  |  mireal.co.jp",
    )
    print(f"Generated: {path}")
