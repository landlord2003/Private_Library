#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建二级分类体系：在 categories 表插入二级节点（parent_id 关联一级），
并为 book_categories 表增加 subcategory_id 列。幂等，可重复运行。"""
import sqlite3, uuid

DB = "data/library.db"

# 一级 -> 二级子类清单（基于各一级实际标签分布设计）
TAX = {
    "计算机与编程": [
        "编程语言", "算法与数据结构", "人工智能与机器学习", "Web开发",
        "计算机科学基础", "软件工程", "图形与游戏开发", "网络安全",
        "操作系统与系统编程", "数据库与数据科学",
    ],
    "历史与人文": [
        "中国史", "世界史", "传记与回忆录", "考古与文物",
        "文化史", "战争史", "政治史", "历史理论与方法",
        "地方史", "社会史",
    ],
    "文学与小说": [
        "长篇小说", "短篇小说", "历史小说", "科幻与奇幻",
        "散文", "诗歌", "经典文学", "回忆录与纪实",
        "戏剧", "外国文学",
    ],
    "哲学与思想": [
        "哲学理论", "中国哲学与思想", "政治哲学", "西方哲学",
        "宗教与神秘主义", "易学与术数", "伦理学", "逻辑与方法论",
    ],
    "科学与科普": [
        "数学", "物理学", "天文学与航天", "地球与地理",
        "生命科学", "医学与中医", "化学", "科学史与科普", "环境科学",
    ],
    "经济与管理": [
        "经济学理论", "金融与投资", "企业管理", "宏观经济",
        "行业研究", "市场营销", "供应链与运营",
    ],
    "心理与成长": [
        "心理学", "个人成长与自我提升", "人际关系与情感", "心理健康", "励志与成功",
    ],
    "教育学习": [
        "教材与教辅", "学习方法", "教育理论", "学科辅导",
    ],
    "艺术设计": [
        "绘画", "插画与漫画", "摄影", "艺术史",
        "博物馆与策展", "设计", "书法与工艺美术",
    ],
    "社会与政治": [
        "政治理论", "国际关系", "社会学", "法律与宪法",
        "社会思潮", "治理与民主",
    ],
    "生活与健康": [
        "美食与料理", "旅行与目的地", "园艺与种植", "家居与生活方式", "健康养生",
    ],
    "其他": [
        "待整理", "手工与DIY", "生活技巧", "综合杂项",
    ],
}


def main():
    con = sqlite3.connect(DB)
    cur = con.cursor()
    # 增加 subcategory_id 列（幂等）
    cols = [r[1] for r in cur.execute("PRAGMA table_info(book_categories)")]
    if "subcategory_id" not in cols:
        cur.execute("ALTER TABLE book_categories ADD COLUMN subcategory_id TEXT")
        print("[schema] book_categories.subcategory_id 已添加")
    else:
        print("[schema] subcategory_id 已存在，跳过")

    inserted = 0
    for parent_name, subs in TAX.items():
        pr = cur.execute("SELECT id FROM categories WHERE name=?", (parent_name,)).fetchone()
        if not pr:
            print(f"[warn] 找不到一级分类: {parent_name}，跳过")
            continue
        pid = pr[0]
        for i, sub in enumerate(subs):
            ex = cur.execute("SELECT id FROM categories WHERE name=? AND parent_id=?", (sub, pid)).fetchone()
            if ex:
                continue
            sid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO categories(id,name,parent_id,description,sort_order,created_at) VALUES(?,?,?,?,?,datetime('now'))",
                (sid, sub, pid, None, i,),
            )
            inserted += 1
    con.commit()

    # 统计
    total = cur.execute("SELECT COUNT(*) FROM categories WHERE parent_id IS NOT NULL").fetchone()[0]
    con.close()
    print(f"[done] 本次新增二级子类 {inserted} 个；现有二级子类共 {total} 个")


if __name__ == "__main__":
    main()
