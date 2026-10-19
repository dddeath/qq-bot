"""Render screenshot node IDs and an unranked candidate sidebar."""
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
from PIL import Image, ImageDraw, ImageFont


def render(image_path, value, output_directory, font_path=None):
    fonts = [font_path] if font_path else [
        'C:/Windows/Fonts/msyh.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    font_file = next((p for p in fonts if p and Path(p).is_file()), None)
    if not font_file:
        raise ValueError('Chinese font missing: configure font_path')
    font = ImageFont.truetype(font_file, 25)
    small = ImageFont.truetype(font_file, 22)
    title = ImageFont.truetype(font_file, 32)
    source = Image.open(image_path).convert('RGB')
    scale = min(1., 1500 / source.width)
    source = source.resize((round(source.width*scale), round(source.height*scale)))
    entries = {}
    ids = set(value.get('predictions', {})) | set(value.get('fixed_nodes', {}))
    ids |= {k for k,v in value.get('node_types', {}).items() if v['type'].startswith('未知')}
    for key in sorted(ids, key=lambda s: int(s[1:])):
        candidates = value.get('predictions', {}).get(key, [])
        fixed = value.get('fixed_nodes', {}).get(key)
        label = (fixed['resolved_type']+' · 模板固定' if fixed else
                 candidates[0]+' · 唯一候选' if len(candidates)==1 else
                 f'候选 ×{len(candidates)}' if candidates else '未确定')
        entries[key] = {'label': label, 'candidates': candidates,
                        'status': 'fixed' if fixed else 'single' if len(candidates)==1 else 'multiple' if candidates else 'unknown'}
    def wrap(text, width=510):
        lines, line = [], ''
        for ch in text.split(' / '):
            part = (' / ' if line else '') + ch
            if small.getlength(line+part)>width:
                lines.append(line); line=''; part=ch
            line += part
        return lines+[line]
    rows=[]
    for key,entry in entries.items():
        lines=wrap(' / '.join(entry['candidates'])) if entry['status']=='multiple' else []
        rows.append((key,entry,lines))
    header=90
    height=max(source.height+header, header+sum(64+len(lines)*32 for _,_,lines in rows)+30)
    canvas=Image.new('RGB',(source.width+590,height),'#101822')
    canvas.paste(source,(0,header)); draw=ImageDraw.Draw(canvas)
    draw.text((24,16),f"黑流树海 · 第 {value['floor']} 层",font=title,fill='white')
    draw.text((24,57),value['template'],font=small,fill='#a9bacb')
    x=source.width+28; y=24
    draw.text((x,y),'节点预测',font=title,fill='white');y=header
    colors={'fixed':'#67e2b2','single':'#67caff','multiple':'#ffd078','unknown':'#b4bfcc'}
    for key,entry,lines in rows:
        color=colors[entry['status']]
        draw.text((x,y),key+'  '+entry['label'],font=font,fill=color)
        for index,line in enumerate(lines):
            draw.text((x,y+36+index*32),line,font=small,fill='#e5eaf0')
        y+=64+len(lines)*32
        position=value['node_positions'].get(key)
        if position is None:
            continue
        cx,cy=position[0]*scale,position[1]*scale+header
        radius=44
        box=(cx-radius,cy-radius,cx+radius,cy+radius)
        if entry['status'] in ('multiple','unknown'):
            for angle in range(0,360,30): draw.arc(box,angle,angle+18,fill=color,width=3)
        else: draw.ellipse(box,outline=color,width=3)
        text=key+(f" · {len(entry['candidates'])}种" if entry['status']=='multiple' else '')
        width=small.getlength(text)+16
        lx=max(4,min(source.width-width-4,cx-width/2));ly=max(header,cy-radius-32)
        draw.rounded_rectangle((lx,ly,lx+width,ly+30),radius=5,fill='#101822')
        draw.text((lx+8,ly),text,font=small,fill=color)
    output=Path(output_directory);output.mkdir(parents=True,exist_ok=True)
    path=output/('prediction-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')+'-'+uuid4().hex[:8]+'.png')
    canvas.save(path)
    return {'image_path':str(path.resolve()), 'annotation_nodes':entries}
