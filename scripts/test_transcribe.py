import os, sqlite3
os.chdir(r'G:\my-library')
os.environ['HF_ENDPOINT']='https://hf-mirror.com'
os.environ['HF_HUB_DISABLE_XET']='1'

DB = r'G:\my-library\data\library.db'
c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
wh = "status='active' AND transcript IS NULL"
media_list = c.execute(f'SELECT id,title,file_path,media_type FROM media WHERE {wh} ORDER BY created_at ASC LIMIT 5').fetchall()
print(f'查到 {len(media_list)} 个待转录文件')
for m in media_list:
    m = dict(m)
    fp = m['file_path']
    fp2 = 'G'+fp[1:] if fp[1:2]==':' else fp
    print(f'  {m["title"][:30]}... 存在:{os.path.exists(fp2)}')
c.close()

# 测试转录第一个
if media_list:
    m = dict(media_list[0])
    fp = m['file_path']
    fp2 = 'G'+fp[1:] if fp[1:2]==':' else fp
    print(f'\n开始转录: {m["title"][:40]}')
    from faster_whisper import WhisperModel
    model = WhisperModel('medium', device='cuda', compute_type='float16')
    segments, info = model.transcribe(fp2, beam_size=5, language='zh', vad_filter=True)
    text = ' '.join([seg.text.strip() for seg in segments])
    print(f'转录完成，{len(text)} 字')
    print(text[:200])
