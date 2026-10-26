"""Bounded explanatory process diagrams built only from saved mechanism text."""
from __future__ import annotations

import html
import io
import textwrap

WIDTH, HEIGHT = 1280, 1120
BG, INK, MUTED, GREEN, BLUE = '#0b1420', '#eef4fb', '#a2b2c7', '#7bdac0', '#91b9ee'
CAPTION = ('Стрелки показывают порядок описания из отчёта. Движение не показывает '
           'скорость, эффективность или выполненный запуск.')


def _text(value, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError('Для схемы нужны непустые ограниченные текстовые шаги.')
    if '<' in value or '>' in value or any(ord(char) < 32 and char not in '\n\r\t' for char in value):
        raise ValueError('Текст схемы должен быть обычным текстом.')
    return ' '.join(value.split())


def _lines(value, width, count):
    lines = textwrap.wrap(str(value), width=width, break_long_words=True, break_on_hyphens=False)
    if len(lines) > count:
        lines = lines[:count]
        lines[-1] = lines[-1].rstrip(' ,.;:') + '…'
    return lines


def process_visual(steps, title=''):
    if not isinstance(steps, (list, tuple)) or len(steps) != 3:
        raise ValueError('Для схемы нужны ровно три шага механизма.')
    texts = [_text(step, 600) for step in steps]
    title = _text(title, 180) if title else 'Механизм по шагам'
    nodes = [{'id':'input','x':65,'y':85,'label':'Вход','detail':'Начало описанной последовательности.'}]
    for index, value in enumerate(texts, 1):
        nodes.append({'id':'step'+str(index),'x':65,'y':85+index*140,
                      'label':str(index)+' · '+value,'detail':value})
    nodes.append({'id':'result','x':65,'y':645,'label':'Результат','detail':'Конец описанной последовательности; результат зависит от указанных в отчёте условий.'})
    for node in nodes:
        node.update(kind='recorded',label_x=120,label_y=node['y']-10,label_align='start',line_chars=36)
    edges = [{'id':'path'+str(index),'from':nodes[index]['id'],'to':nodes[index+1]['id'],'dashed':False}
             for index in range(4)]
    scenes = []
    for index, node in enumerate(nodes):
        scenes.append({'title':'Вход' if index == 0 else 'Результат' if index == 4 else 'Шаг '+str(index),
                       'explanation':node['detail'], 'phase':'process',
                       'active_edges':[edges[index-1]['id']] if index else [],
                       'active_nodes':[node['id']]})
    return {'kind':'process_flow','title':title,'caption':CAPTION,
            'graph':{'width':680,'height':750,'nodes':nodes,'edges':edges},'scenes':scenes,
            'steps':[{'label':'Шаг '+str(index),'text':value} for index,value in enumerate(texts,1)]}


def _visual(data):
    visual = data.get('visual') or {}
    steps = visual.get('steps') or []
    texts = [step.get('text','') if isinstance(step,dict) else step for step in steps]
    return process_visual(texts, str(data.get('title') or visual.get('title') or '')[:180])


def _elements(data, scene=4, progress=1):
    visual = _visual(data)
    scene = max(0,min(4,int(scene)))
    result = [('rect',0,0,WIDTH,HEIGHT,BG,0),
              ('text',46,45,'AI R&D LABORATORY · МЕХАНИЗМ ИЗ ОТЧЁТА',18,GREEN,False)]
    for index,line in enumerate(_lines(visual['title'],58,2)):
        result.append(('text',46,98+index*39,line,34,INK,True))
    result.append(('text',46,170,'ВХОД → ТРИ ШАГА МЕХАНИЗМА → РЕЗУЛЬТАТ',19,MUTED,False))
    ys = [245,395,545,695,845]
    for index in range(4):
        active = scene == index+1
        color = GREEN if active else '#3b5269'
        result.append(('line',94,ys[index]+24,94,ys[index+1]-24,color,7 if active else 3))
        result.append(('line',94,ys[index+1]-24,85,ys[index+1]-39,color,3))
        result.append(('line',94,ys[index+1]-24,103,ys[index+1]-39,color,3))
    for index,node in enumerate(visual['graph']['nodes']):
        selected = scene == index
        color = GREEN if selected else BLUE
        result.append(('rect',155,ys[index]-51,1080,114,'#173039' if selected else '#101f30',14))
        result.append(('circle',94,ys[index],23,color if selected else '#172b3e',color,3))
        result.append(('center',94,ys[index]+7,str(index) if index in (1,2,3) else 'В' if index == 0 else 'Р',20,BG if selected else INK,True))
        text = node['label'] if index in (0,4) else visual['steps'][index-1]['text']
        for line_no,line in enumerate(_lines(text,75,3)):
            result.append(('text',179,ys[index]-15+line_no*29,line,24,INK,False))
    if scene:
        p = max(0,min(1,float(progress)))
        y = ys[scene-1]+(ys[scene]-ys[scene-1])*p
        result.append(('circle',94,y,11,'#fff1b6','#ffffff',2))
    result.append(('rect',40,938,1200,117,'#1b2a3c',14))
    for line_no,line in enumerate(_lines(visual['scenes'][scene]['explanation'],100,3)):
        result.append(('text',62,972+line_no*28,line,21,INK,False))
    for line_no,line in enumerate(_lines(CAPTION,115,2)):
        result.append(('text',44,1080+line_no*23,line,17,MUTED,False))
    return result


def render_process_svg(data):
    visual = _visual(data)
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
             '<title>'+html.escape(visual['title'])+'</title><desc>'+html.escape(CAPTION)+'</desc>']
    for item in _elements(data):
        if item[0] == 'rect':
            _,x,y,w,h,color,r=item
            parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{color}"/>')
        elif item[0] == 'line':
            _,x,y,xx,yy,color,w=item
            parts.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{color}" stroke-width="{w}"/>')
        elif item[0] == 'circle':
            _,x,y,r,fill,stroke,w=item
            parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{w}"/>')
        else:
            kind,x,y,text,size,color,bold=item
            parts.append(f'<text x="{x}" y="{y}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}"'+(' text-anchor="middle"' if kind=='center' else '')+'>'+html.escape(str(text))+'</text>')
    return ''.join(parts)+'</svg>'


def _picture(data, scene, progress):
    from PIL import Image, ImageDraw
    from .presentation import _font
    picture=Image.new('RGB',(WIDTH,HEIGHT),BG)
    draw=ImageDraw.Draw(picture)
    fonts={}
    for item in _elements(data,scene,progress):
        if item[0]=='rect':
            _,x,y,w,h,color,r=item
            draw.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=color)
        elif item[0]=='line':
            _,x,y,xx,yy,color,w=item
            draw.line((x,y,xx,yy),fill=color,width=w)
        elif item[0]=='circle':
            _,x,y,r,fill,stroke,w=item
            draw.ellipse((x-r,y-r,x+r,y+r),fill=fill,outline=stroke,width=w)
        else:
            kind,x,y,text,size,color,bold=item
            if (size,bold) not in fonts:fonts[size,bold]=_font(size,bold)
            draw.text((x,y),text,font=fonts[size,bold],fill=color,anchor='ms' if kind=='center' else 'ls')
    return picture


def render_process_png(data):
    try:picture=_picture(data,4,1)
    except ImportError:return None
    output=io.BytesIO()
    picture.save(output,format='PNG',optimize=True)
    return output.getvalue()


def render_process_gif(data):
    try:
        from PIL import Image
        frames=[]
        durations=[]
        for scene in range(5):
            for frame in range(8):
                picture=_picture(data,scene,frame/7).resize((960,840),Image.Resampling.LANCZOS)
                frames.append(picture.convert('P',palette=Image.Palette.ADAPTIVE,colors=128))
                durations.append(1100 if frame==7 else 160)
    except ImportError:return None
    output=io.BytesIO()
    frames[0].save(output,format='GIF',save_all=True,append_images=frames[1:],duration=durations,loop=0,optimize=True,disposal=2)
    return output.getvalue()
