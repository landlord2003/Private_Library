# -*- coding: utf-8 -*-
"""生成"我的图书馆"桌面图标 library.ico：深蓝渐变底 + 白色翻开的书 + 金色书签"""
from PIL import Image, ImageDraw

S = 1024  # 主画布尺寸

# ---------- 1. 渐变圆角背景（深蓝 -> 青蓝）----------
top = (26, 60, 158)      # 深蓝
bottom = (16, 155, 219)  # 青蓝
grad = Image.new("RGB", (S, S))
for y in range(S):
    t = y / (S - 1)
    r = int(top[0] + (bottom[0] - top[0]) * t)
    g = int(top[1] + (bottom[1] - top[1]) * t)
    b = int(top[2] + (bottom[2] - top[2]) * t)
    ImageDraw.Draw(grad).line([(0, y), (S, y)], fill=(r, g, b))

mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=200, fill=255)
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
img.paste(grad, (0, 0), mask)
d = ImageDraw.Draw(img)

# ---------- 2. 翻开的书（两页白色，中间书脊）----------
cx = S // 2
book_top, book_bot = 300, 760
page_out = 90  # 左右外扩

# 左页（从书脊向外、微上翘的曲线）
left_pts = [
    (cx, book_top + 30),
    (cx - 160, book_top - 10),
    (cx - 300, book_top),
    (cx - 380, book_top + 40),
    (cx - page_out - 300, book_bot - 60),
    (cx - page_out - 300 + 60, book_bot + 20),
    (cx - 260, book_bot - 10),
    (cx - 120, book_bot - 40),
    (cx, book_bot - 70),
]
# 右页（镜像）
right_pts = [(S - x, y) for x, y in left_pts]

# 书页阴影底（略向下偏移的深色，制造厚度）
for pts, off in ((left_pts, 26), (right_pts, 26)):
    shifted = [(x, y + off) for x, y in pts]
    d.polygon(shifted, fill=(10, 40, 90, 255))

# 白色书页
d.polygon(left_pts, fill=(255, 255, 255, 255))
d.polygon(right_pts, fill=(245, 250, 255, 255))

# 页面内纹线（模拟文字行）
for i in range(4):
    yy = book_top + 90 + i * 90
    d.line([(cx - 320, yy), (cx - 90, yy + 22)], fill=(150, 175, 210, 255), width=14)
    d.line([(cx + 90, yy + 22), (cx + 320, yy)], fill=(150, 175, 210, 255), width=14)

# 书脊
d.line([(cx, book_top + 30), (cx, book_bot - 70)], fill=(120, 150, 190, 255), width=10)

# ---------- 3. 金色书签（右页顶部垂下）----------
bm = [(cx + 150, book_top + 55), (cx + 250, book_top + 42), (cx + 250, book_top + 320),
      (cx + 200, book_top + 275), (cx + 150, book_top + 320)]
d.polygon(bm, fill=(255, 193, 59, 255))

# ---------- 4. 保存为多尺寸 ico ----------
sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
img.save(r"G:\my-library\library.ico", format="ICO", sizes=sizes)

# 同时导出一张 png 预览
img.save(r"G:\my-library\scripts\icon_preview.png")
print("icon saved")
