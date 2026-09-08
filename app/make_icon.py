"""Иконка приложения: раскрытая книга, из которой идёт звуковая волна."""
from PIL import Image, ImageDraw
import os, subprocess, math

S = 1024


def draw(size=S):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 1024

    # скруглённая подложка с вертикальным градиентом
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / size
        grad.putpixel((0, y), (int(38 + 22 * t), int(52 + 34 * t), int(84 + 46 * t)))
    grad = grad.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size, size], radius=int(228 * u), fill=255)
    img.paste(grad, (0, 0), mask)

    # книга: две страницы, сходящиеся к корешку
    cx, top, bot = size / 2, 330 * u, 720 * u
    spread, lift = 300 * u, 46 * u
    page = (246, 246, 244)
    for sign in (-1, 1):
        outer = cx + sign * spread
        d.polygon([(cx, top), (outer, top - lift), (outer, bot - lift), (cx, bot)],
                  fill=page if sign < 0 else (232, 232, 229))
    d.line([(cx, top), (cx, bot)], fill=(150, 152, 158), width=max(1, int(5 * u)))

    # строки текста на левой странице
    for i in range(5):
        y = top + (58 + i * 62) * u
        d.line([(cx - 250 * u, y), (cx - 40 * u, y - 26 * u)],
               fill=(176, 180, 190), width=max(1, int(12 * u)))

    # звуковая волна на правой странице
    amp0, x0 = 96 * u, cx + 70 * u
    for i in range(7):
        x = x0 + i * 34 * u
        a = amp0 * (0.35 + 0.65 * math.sin((i + 1) / 8 * math.pi))
        y = top + 300 * u - i * 9 * u
        d.rounded_rectangle([x - 9 * u, y - a / 2, x + 9 * u, y + a / 2],
                            radius=9 * u, fill=(255, 189, 92))
    return img


def main():
    base = draw()
    it = "AppIcon.iconset"
    os.makedirs(it, exist_ok=True)
    for px in (16, 32, 64, 128, 256, 512, 1024):
        base.resize((px, px), Image.LANCZOS).save(f"{it}/icon_{px}x{px}.png")
        if px <= 512:
            base.resize((px * 2, px * 2), Image.LANCZOS).save(f"{it}/icon_{px}x{px}@2x.png")
    for f in os.listdir(it):                       # iconutil признаёт не все размеры
        if f not in {"icon_16x16.png", "icon_16x16@2x.png", "icon_32x32.png",
                     "icon_32x32@2x.png", "icon_128x128.png", "icon_128x128@2x.png",
                     "icon_256x256.png", "icon_256x256@2x.png", "icon_512x512.png",
                     "icon_512x512@2x.png"}:
            os.remove(os.path.join(it, f))
    subprocess.run(["iconutil", "-c", "icns", it, "-o", "AppIcon.icns"], check=True)
    print("AppIcon.icns готов")


if __name__ == "__main__":
    main()
