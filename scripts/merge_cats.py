"""合并相似分类"""
import sqlite3
db = sqlite3.connect("data/library.db")

# 映射：多余类别 → 合并到哪个主类别
merge = {
    "旅行与地理":"生活与健康",
    "旅游与地理":"生活与健康",
    "政治与社会":"社会与政治",
    "法律与法规":"社会与政治",
    "法律与司法":"社会与政治",
    "法律与政治":"社会与政治",
    "医学与健康":"生活与健康",
    "自然科学":"科学与科普",
    "工程技术":"计算机与编程",
    "信息技术":"计算机与编程",
    "商业与经济":"经济与管理",
    "金融投资":"经济与管理",
    "未知":"其他",
}

for src, dst in merge.items():
    src_row = db.execute("SELECT id FROM categories WHERE name=?",(src,)).fetchone()
    dst_row = db.execute("SELECT id FROM categories WHERE name=?",(dst,)).fetchone()
    if not src_row or not dst_row: continue
    # 移动分类
    cnt = db.execute("UPDATE book_categories SET category_id=? WHERE category_id=?",(dst_row[0],src_row[0])).rowcount
    # 删除多余类别
    db.execute("DELETE FROM categories WHERE id=?",(src_row[0],))
    print(f"  {src} -> {dst}: {cnt}本")

db.commit()
db.close()
print("Done")
