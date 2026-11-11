#!/usr/bin/env python3
"""Имитация чернил на бумаге: чёрно-белая картинка -> тёплая бумага с неровным краем и растёкшимися чернилами."""
import sys, numpy as np
from PIL import Image
from scipy.ndimage import gaussian_filter, map_coordinates

def noise(shape, scale, rng):
    """шум одного масштаба 0..1 (scale — размер «пятна» в пикселях)"""
    h, w = shape
    small = rng.random((max(2, int(h / scale) + 2), max(2, int(w / scale) + 2)))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(img, np.float32) / 255

def ink_on_paper(src, strength=1.0, seed=7, out_w=None):
    rng = np.random.default_rng(seed)
    im = Image.open(src).convert('L')
    if out_w and im.width != out_w:
        im = im.resize((out_w, round(im.height * out_w / im.width)), Image.LANCZOS)
    L = np.asarray(im, np.float32) / 255
    h, w = L.shape
    k = w / 2000.0                                   # все размеры заданы для картинки шириной 2000
    ink = 1 - L                                      # 1 = чёрное

    # 1. неровный край: чуть «плывём» координатами по низкочастотному шуму
    amp = 1.6 * strength * k
    dx = (noise((h, w), 9 * k, rng) - .5) * 2 * amp + (noise((h, w), 3 * k, rng) - .5) * amp
    dy = (noise((h, w), 9 * k, rng) - .5) * 2 * amp + (noise((h, w), 3 * k, rng) - .5) * amp
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    ink = map_coordinates(ink, [yy + dy, xx + dx], order=1, mode='nearest')

    # 2. растекание чернил: размыли и снова подтянули контраст — края округлились, тонкие линии чуть налились
    b = gaussian_filter(ink, 1.1 * k * (0.6 + 0.4 * strength))
    lo, hi = 0.28 - 0.06 * strength, 0.72 - 0.06 * strength
    core = np.clip((b - lo) / (hi - lo), 0, 1)
    # 3. мягкая кайма (чернила впитались в волокна бумаги)
    halo = gaussian_filter(ink, 3.2 * k) * 0.22 * strength
    a = np.clip(core + halo * (1 - core), 0, 1)

    # 4. неравномерная плотность и просветы бумаги в чернилах
    dens = 1 - 0.13 * strength * noise((h, w), 70 * k, rng) - 0.07 * strength * noise((h, w), 14 * k, rng)
    grain = noise((h, w), 1.4 * k, rng)
    holes = np.clip((grain - 0.80) / 0.2, 0, 1) * 0.55 * strength   # редкие светлые точки в чёрном
    a = np.clip(a * dens - holes * a, 0, 1)

    # 5. бумага: тёплый тон, волокна, лёгкая неравномерность и виньетка
    paper = np.ones((h, w, 3), np.float32) * np.array([0.962, 0.945, 0.905], np.float32)
    fib = (noise((h, w), 2.2 * k, rng) - .5) * 0.035 + (noise((h, w), 38 * k, rng) - .5) * 0.04 + (noise((h, w), 260 * k, rng) - .5) * 0.05
    paper += fib[..., None]
    yv, xv = (yy / h - .5), (xx / w - .5)
    paper *= (1 - 0.10 * np.clip(np.sqrt(xv ** 2 + yv ** 2) * 1.5 - .25, 0, 1))[..., None]

    # 6. умножение: чернила тёплого чёрного
    inkc = np.array([0.10, 0.085, 0.075], np.float32)
    res = paper * (1 - a[..., None] * (1 - inkc))
    return Image.fromarray((np.clip(res, 0, 1) * 255).astype(np.uint8))

if __name__ == '__main__':
    # python3 tools/ink_on_paper.py исходник.jpg результат.jpg [сила=1.0] [ширина]
    src, dst = sys.argv[1], sys.argv[2]
    st = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
    w = int(sys.argv[4]) if len(sys.argv) > 4 else None
    ink_on_paper(src, st, out_w=w).save(dst, quality=77, optimize=True, progressive=True)
