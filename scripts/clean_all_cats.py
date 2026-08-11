"""统一所有分类到标准12类"""
import sqlite3, re

db = sqlite3.connect("data/library.db")

# 关键词映射：包含这些词 → 目标分类
RULES = [
    (["计算机","编程","软件","算法","程序","Python","Java","代码","开发","web","前端","后端","Linux","网络","数据","人工智能","AI","机器学习","深度学习"], "计算机与编程"),
    (["历史","古代","近代","现代","战争","革命","王朝","帝国","考古","文明","传记","biography","人物","年谱","回忆录","memoir"], "历史与人文"),
    (["文学","小说","诗歌","散文","戏剧","故事","诗","fiction","novel","poem","童话","寓言","神话","民间"], "文学与小说"),
    (["哲学","思想","宗教","伦理","逻辑","道德","信仰","佛","道","儒","基督","伊斯兰","philosophy","神学","形而上学"], "哲学与思想"),
    (["科学","物理","化学","生物","数学","天文","地理","自然","气候","环境","生态","science","physics","biology","math"], "科学与科普"),
    (["经济","管理","商业","营销","金融","投资","会计","管理","创业","贸易","市场","economy","business","finance"], "经济与管理"),
    (["心理","成长","自我","情绪","人际","沟通","情商","幸福","成功","励志","mental","personal","self"], "心理与成长"),
    (["教育","学习","考试","教材","教学","语言","英语","日语","法语","德语","考研","高考","edu","language","考试"], "教育学习"),
    (["艺术","设计","绘画","摄影","音乐","建筑","电影","戏剧","舞蹈","书法","美学","art","design","music","photo"], "艺术设计"),
    (["社会","政治","法律","国际","政府","政策","民主","制度","political","law","legal","rights","sociology"], "社会与政治"),
    (["健康","医学","养生","饮食","运动","体育","健身","疾病","中医","西医","健康","营养","health","medical","cook"], "生活与健康"),
]

# 1. 加载所有分类
all_cats = db.execute("SELECT id, name FROM categories").fetchall()

# 2. 建立合并映射
mapping = {}  # cat_id -> target_id

# 先确保12个主分类存在且唯一
for rule_cats, target_name in RULES:
    target_id = db.execute("SELECT id FROM categories WHERE name=?", (target_name,)).fetchone()
    if not target_id:
        target_id = (f"standard_{target_name}",)
        db.execute("INSERT INTO categories(id,name) VALUES(?,?)", target_id)
    target_id = db.execute("SELECT id FROM categories WHERE name=?", (target_name,)).fetchone()[0]

    for keyword in rule_cats:
        for cid, cname in all_cats:
            if keyword.lower() in cname.lower():
                if cid != target_id:
                    mapping[cid] = target_id

# 确保"其他"存在
other_id = db.execute("SELECT id FROM categories WHERE name='其他'").fetchone()
if not other_id:
    db.execute("INSERT INTO categories(id,name) VALUES('standard_other','其他')")
    other_id = ("standard_other",)
other_id = db.execute("SELECT id FROM categories WHERE name='其他'").fetchone()[0]

# 所有未映射的 → "其他"
for cid, cname in all_cats:
    if cid not in mapping and cname not in [r[1] for r in RULES] and cname != "其他":
        mapping[cid] = other_id

# 3. 执行合并
total = 0
for src_id, dst_id in mapping.items():
    cnt = db.execute("UPDATE book_categories SET category_id=? WHERE category_id=?", (dst_id, src_id)).rowcount
    db.execute("DELETE FROM categories WHERE id=?", (src_id,))
    total += cnt
    if cnt > 0:
        src_name = [c[1] for c in all_cats if c[0] == src_id]
        dst_name = db.execute("SELECT name FROM categories WHERE id=?", (dst_id,)).fetchone()[0]
        print(f"  {src_name[0] if src_name else src_id[:8]} -> {dst_name}: {cnt}本")

db.commit()
print(f"\n总移动: {total} 本书")
print(f"剩余分类数: {db.execute('SELECT count(*) FROM categories').fetchone()[0]}")
db.close()
