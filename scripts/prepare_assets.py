"""加藤さんが用意した素材写真を 1080x1080 に整形して保存する

Input:  assets/backgrounds/*.{jpg,jpeg,png,JPG,JPEG,PNG} (originals, gitignored)
Output: assets/backgrounds/processed/bg-001.jpg ... (committed to git)

処理内容:
  1. EXIF orientation を適用
  2. RGBに変換
  3. 中央クロップで正方形化
  4. 1080x1080 にリサイズ (LANCZOS)
  5. JPG quality 85 で書き出し
"""
import sys
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).parent.parent
INPUT_DIR = ROOT / "assets" / "backgrounds"
OUTPUT_DIR = INPUT_DIR / "processed"

TARGET_SIZE = 1080
JPG_QUALITY = 85

VALID_EXTS = {".jpg", ".jpeg", ".png"}


def process_one(input_path: Path, output_path: Path) -> bool:
    try:
        with Image.open(input_path) as img:
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGB")

            w, h = img.size
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))

            img = img.resize((TARGET_SIZE, TARGET_SIZE), Image.LANCZOS)
            img.save(output_path, format="JPEG", quality=JPG_QUALITY, optimize=True)
        return True
    except Exception as e:
        print(f"  ❌ {input_path.name}: {e}", file=sys.stderr)
        return False


def main():
    if not INPUT_DIR.exists():
        print(f"❌ {INPUT_DIR} が存在しません")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    inputs = [
        p for p in sorted(INPUT_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in VALID_EXTS and p.parent == INPUT_DIR
    ]
    if not inputs:
        print(f"❌ {INPUT_DIR} に処理対象の画像が無い")
        sys.exit(1)

    print(f"Found {len(inputs)} images to process")
    print(f"Output: {OUTPUT_DIR}")
    print()

    # 既存の processed を一旦クリア（番号衝突防止）
    for old in OUTPUT_DIR.glob("bg-*.jpg"):
        old.unlink()

    success = 0
    failed = 0
    total_size_in = 0
    total_size_out = 0
    for i, input_path in enumerate(inputs, start=1):
        out_name = f"bg-{i:03d}.jpg"
        output_path = OUTPUT_DIR / out_name
        size_in = input_path.stat().st_size
        total_size_in += size_in
        ok = process_one(input_path, output_path)
        if ok:
            size_out = output_path.stat().st_size
            total_size_out += size_out
            success += 1
            print(f"  [OK] [{i:>3}/{len(inputs)}] {input_path.name[:50]:<50} -> {out_name} ({size_in / 1024 / 1024:.1f}MB -> {size_out / 1024:.0f}KB)")
        else:
            failed += 1

    print()
    print(f"=== Summary ===")
    print(f"Success: {success}")
    print(f"Failed:  {failed}")
    print(f"Total size in:  {total_size_in / 1024 / 1024:.1f} MB")
    print(f"Total size out: {total_size_out / 1024 / 1024:.1f} MB ({100 * total_size_out / total_size_in:.1f}%)")


if __name__ == "__main__":
    main()
