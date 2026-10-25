"""Generate 60 fictional badges plus negatives. No real people or identity documents."""

import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parent / "generated"


def main():
    OUT.mkdir(exist_ok=True)
    random.seed(42)
    fonts = [Path("C:/Windows/Fonts/segoeui.ttf"), Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")]
    font = next((str(p) for p in fonts if p.exists()), None)
    labels = []
    for i in range(72):
        negative = i >= 60
        names = ["Avery Demo", "Zoë Demo", "Алекс Демо", "Νίκη Δοκιμή"]
        name = f"{names[(i // 6) % len(names)]} {i:02d}"
        org = f"Fictional Lab {i % 7}"
        image = Image.new("RGB", (1200, 800), "#284c3d")
        d = ImageDraw.Draw(image)
        d.rounded_rectangle((60, 60, 1140, 740), radius=25, fill="#eee7d6")
        texts = (
            ["FICTIONAL DEMO CONFERENCE", name, org, "Engineer"]
            if not negative
            else ["FICTIONAL TEST — NO NAME OR COMPANY", "SYNTHETIC NEGATIVE FIXTURE"]
        )
        for n, text in enumerate(texts):
            face = ImageFont.truetype(font, 48 if n else 30) if font else ImageFont.load_default(size=40)
            d.text((110, 110 + n * 145), text, font=face, fill="#173b30")
        variant = i % 6 if not negative else 0
        if variant == 1:
            image = image.rotate(8, resample=Image.Resampling.BICUBIC, fillcolor="#284c3d")
        if variant == 2:
            image = image.filter(ImageFilter.GaussianBlur(2))
        if variant == 3:
            image = image.point(lambda p: int(p * 0.35))
        if variant == 4:
            overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
            ImageDraw.Draw(overlay).ellipse((600, -100, 900, 900), fill=(255, 255, 255, 190))
            image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
        if variant == 5:
            image = image.resize((360, 240))
        filename = f"badge-{i:02d}.jpg"
        image.save(OUT / filename, quality=85)
        labels.append(
            {
                "image": filename,
                "name": None if negative else name,
                "organization": None if negative else org,
                "difficulty": "negative" if negative else "good" if variant == 0 else "hard",
            }
        )
    (OUT / "gold.json").write_text(json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Generated {len(labels)} fictional fixtures in {OUT}")


if __name__ == "__main__":
    main()
