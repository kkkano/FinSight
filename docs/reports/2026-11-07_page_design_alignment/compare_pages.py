from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent
font = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 20)
sections = []
for page in ['welcome', 'dashboard', 'track-record']:
    for theme in ['light', 'dark']:
        reference = Image.open(root / f'reference-{page}-{theme}-1440.png').convert('RGB')
        actual = Image.open(root / f'{page}-{theme}-1440.png').convert('RGB')
        assert reference.size == actual.size == (1440, 960)
        combined = Image.new('RGB', (2880, 1000), '#f1f3f5')
        draw = ImageDraw.Draw(combined)
        draw.text((20, 8), '设计稿（原型数据）', fill='#172033', font=font)
        draw.text((1460, 8), '实现（接口结构测试数据，非生产行情）', fill='#172033', font=font)
        combined.paste(reference, (0, 40))
        combined.paste(actual, (1440, 40))
        combined.save(root / f'compare-{page}-{theme}.png')
        sections.append(f'<h2>{page} · {theme}</h2><div class="pair"><figure><figcaption>设计稿</figcaption><img src="reference-{page}-{theme}-1440.png"></figure><figure><figcaption>实现（测试接口数据）</figcaption><img src="{page}-{theme}-1440.png"></figure></div><details><summary>390px实现</summary><img width="390" src="{page}-{theme}-390.png"></details>')
(root / 'index.html').write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>FinSight页面设计对照</title><style>body{font:14px/1.6 system-ui;margin:20px;color:#172033;background:#f5f6f8}h1{font-size:24px}h2{margin-top:32px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:12px}figure{margin:0}figcaption{padding:8px}img{max-width:100%;border:1px solid #d7dce3}details{margin:12px 0}@media(max-width:900px){.pair{grid-template-columns:1fr}}</style><h1>FinSight页面设计对照</h1><p>桌面1440×960，移动390×844；价格、记录是版式验收数据，不进入生产。</p>' + ''.join(sections) + '</html>', encoding='utf-8')
print({'comparisons': 6, 'screenshots': len(list(root.glob('*.png')))})
