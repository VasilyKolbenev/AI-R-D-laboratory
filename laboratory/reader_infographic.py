"""Reader infographic from existing report fields; no model or invented data."""
from __future__ import annotations

import html
import io
import math
from functools import lru_cache

W = 1080
PAPER, INK, MUTED = '#f3f2ed', '#142b2a', '#586963'
GREEN, MINT, AMBER = '#087b64', '#cfeedd', '#f1d18b'
WHITE, LINE, BEFORE = '#ffffff', '#d6ded6', '#879b94'
NO_COMPARISON = 'Сопоставимая пара baseline/result не зафиксирована; показана схема метода.'


def _clean(value):
    from .presentation import _clean as clean, _URL, _public_url
    if not isinstance(value, str):return ''
    # Source commit hashes are public provenance, not local record IDs.
    # Validate every URL before protecting it from prose-ID redaction.
    urls=[]
    def protect(match):
        url=_public_url(match.group())
        if not url:return '[приватная ссылка скрыта]'
        urls.append(url)
        return 'PUBLICSOURCEURL'+str(len(urls)-1)+'END'
    result=clean(_URL.sub(protect,value))
    for index,url in enumerate(urls):result=result.replace('PUBLICSOURCEURL'+str(index)+'END',url)
    return result


@lru_cache(maxsize=32)
def _font(size, bold=False):
    from .presentation import _font as font
    return font(size, bold)


def _width(text, size, bold=False, font_factory=None):
    try:
        return (font_factory or _font)(size, bold).getlength(text)
    except ImportError:
        return len(text) * size * .56


def _wrap(text, width, size, bold=False, font_factory=None):
    words = _clean(text).split()
    lines, line = [], ''
    for word in words:
        if _width(word, size, bold, font_factory) > width:
            if line:
                lines.append(line); line = ''
            fragment = ''
            for char in word:
                if fragment and _width(fragment+char, size, bold, font_factory) > width:
                    lines.append(fragment); fragment = ''
                fragment += char
            line = fragment
        elif line and _width(line+' '+word, size, bold, font_factory) > width:
            lines.append(line); line = word
        else:
            line = (line+' '+word).strip()
    if line: lines.append(line)
    return lines


def _text(parts, text, x, y, width, size=24, color=INK, bold=False, gap=None, center=False):
    gap = gap or round(size * 1.32)
    lines = _wrap(text, width, size, bold)
    for line in lines:
        at = x + (width-_width(line, size, bold))/2 if center else x
        parts.append(('text', at, y, line, size, color, bold))
        y += gap
    return y


def _section_items(data, key, fallback=None):
    section = next((s for s in data.get('story', []) if s.get('id') == key), {})
    result = [item for item in section.get('items', []) if isinstance(item, str) and item.strip()]
    if result: return result[:3]
    result = data.get(fallback or key) or []
    if isinstance(result, str): result = [result]
    return [item for item in result[:3] if isinstance(item, str) and item.strip()]


def _rows_height(items, width, size=22):
    return sum(max(1, len(_wrap(item, width, size))) * round(size*1.32) + 16 for item in items)


def _mechanism_steps(data):
    steps = (data.get('visual') or {}).get('steps') or []
    lines = [_clean(step.get('text', '')) for step in steps[:3] if isinstance(step, dict) and step.get('text')]
    return lines or [_clean(item) for item in _section_items(data, 'mechanism')]


def _bullets(parts, items, x, y, width, color=INK, size=22):
    for item in items:
        parts.append(('circle', x+4, y+12, 3, color))
        y = _text(parts, item, x+20, y, width-20, size, color) + 16
    return y


def _number(value):
    if isinstance(value, float) and value.is_integer(): value = int(value)
    return format(value, '.6g').replace('.', ',') if abs(value) >= 1e8 else str(value).replace('.', ',')


def _comparisons(data):
    result = []
    for item in data.get('comparisons', [])[:3]:
        if not isinstance(item, dict): continue
        values = item.get('baseline_value'), item.get('result_value')
        if any(type(v) not in (int, float) or not 0 <= v <= 1e100 or not math.isfinite(v) for v in values): continue
        if not all(isinstance(item.get(k), str) and item[k].strip() for k in ('label','unit','baseline_label','result_label','conditions')): continue
        result.append(item)
    return result


def _icon(parts, kind, x, y, color):
    if kind == 'target':
        for radius in (15, 9): parts.append(('outline_circle', x, y, radius, color, 2))
        parts.append(('circle', x, y, 3, color))
    elif kind == 'limit':
        parts.append(('polygon', [(x,y-16),(x+16,y-10),(x+13,y+8),(x,y+18),(x-13,y+8),(x-16,y-10)], None, color, 2))
        parts.extend([('line',x,y-7,x,y+4,color,3),('circle',x,y+10,2,color)])
    elif kind == 'stack':
        for row in range(3): parts.append(('outline_rect',x-15,y-13+row*10,30,7,color,2,2))
    else:
        parts.extend([('line',x-14,y,x+14,y,color,3),('line',x+6,y-8,x+14,y,color,3),('line',x+6,y+8,x+14,y,color,3)])


def _metric(parts, item, y, progress, index):
    x, width = 40, 1000
    title_lines = _wrap(item['label'], 906, 30, True)
    title_height = len(title_lines) * 39
    label_height = max(len(_wrap(item[k], 370, 23, True)) for k in ('baseline_label','result_label'))*30
    conditions_height = len(_wrap(item['conditions'], 900, 21))*28
    caveats = list(dict.fromkeys(e.get('limitations','') for e in item.get('evidence', []) if e.get('limitations')))
    caveat = ' '.join(caveats)
    caveat_height = len(_wrap(caveat, 900, 21))*28 if caveat else 0
    height = 80 + title_height + 214 + label_height + conditions_height + caveat_height + 65
    parts.append(('rect', x, y, width, height, WHITE, 30))
    parts.append(('text', 76, y+24, 'СРАВНЕНИЕ '+str(index+1), 16, GREEN, True))
    _text(parts, item['label'], 76, y+57, 906, 30, INK, True)
    top = y+68+title_height
    a, b = item['baseline_value'], item['result_value']
    percent = item['unit'].strip().casefold() in {'%', 'процент', 'процентов', 'проценты'} and max(a,b)<=100
    if percent:
        for center, value, color, reveal in ((294,a,BEFORE,1),(786,b,GREEN,progress)):
            parts.append(('ring', center, top+92, 83, 14, value/100*reveal, color, '#e6ece7'))
            text = _number(value)+'%'
            size = 62 if len(text)<6 else 44
            _text(parts, text, center-116, top+47, 232, size, INK, True, center=True)
        parts.append(('text', 244, top+189, 'шкала 0–100%', 16, MUTED, False))
        parts.append(('text', 736, top+189, 'шкала 0–100%', 16, MUTED, False))
    else:
        maximum = max(a,b) or 1
        for col, value, color, reveal in ((108,a,BEFORE,1),(600,b,GREEN,progress)):
            _text(parts, _number(value), col, top+24, 372, 58, INK, True, center=True)
            _text(parts, item['unit'], col, top+99, 372, 22, MUTED, center=True)
            parts.append(('rect', col, top+150, 372, 20, '#e6ece7', 10))
            if value: parts.append(('rect', col, top+150, 372*(value/maximum)*reveal, 20, color, 10))
        _text(parts, '0 → '+_number(maximum)+' '+item['unit'], 108, top+184, 864, 16, MUTED, center=True)
    _icon(parts, 'arrow', 540, top+91, GREEN)
    labels_y = top+222
    _text(parts, item['baseline_label'], 109, labels_y, 370, 23, MUTED, True, center=True)
    _text(parts, item['result_label'], 601, labels_y, 370, 23, GREEN, True, center=True)
    at = labels_y+label_height+28
    at = _text(parts, item['conditions'], 90, at, 900, 21, MUTED, gap=28)
    if caveat:
        at = _text(parts, caveat, 90, at+7, 900, 21, INK, True, gap=28)
    return y+height+22


def layout(data, progress=1):
    """Data-driven editorial hierarchy; the report and its wording remain unchanged."""
    from .adaptive_visual import profile_mode, layout as adaptive_layout
    if profile_mode(data) in {'mechanism','infrastructure','applicability'}:
        return adaptive_layout(data)
    progress = max(0,min(1,float(progress)))
    parts = []
    parts.append(('text', 54, 33, 'VV FRONTIER', 17, GREEN, True))
    parts.append(('text', 691, 33, 'СРАВНЕНИЕ / ПРИМЕНЕНИЕ / ГРАНИЦЫ', 13, MUTED, True))
    y = _text(parts, data.get('title') or 'Прикладной разбор технологии', 52, 80, 976, 47, INK, True, gap=58)+26
    problem = data.get('problem') or data.get('summary')
    if problem: y = _text(parts, problem, 54, y, 970, 25, MUTED, gap=33)+28
    comparisons = _comparisons(data)
    for index, item in enumerate(comparisons): y = _metric(parts,item,y,progress,index)
    if not comparisons:
        lines = _mechanism_steps(data)
        note_height = len(_wrap(NO_COMPARISON, 900, 21))*28
        height = 130+note_height+_rows_height(lines, 870, 23)
        parts.append(('rect',40,y,1000,height,WHITE,30))
        _text(parts,'Механизм по шагам',76,y+28,900,30,INK,True)
        at = _text(parts,NO_COMPARISON,76,y+76,900,21,MUTED,gap=28)+22
        _bullets(parts,lines or ['Данных недостаточно; ограничения и следующий шаг указаны ниже.'],80,at,900,size=23)
        y += height+22
    audience = [data.get('audience') or '',data.get('use_case') or '']
    audience = [text for text in audience if text] or _section_items(data,'audience','applicability')
    limits = (_section_items(data,'limitations','cons') or ['Границы применимости в отчёте не определены.'])[:2]
    body_height = 105+max(_rows_height(audience,413),_rows_height(limits,413))
    parts.extend([('rect',40,y,490,body_height,MINT,28),('rect',550,y,490,body_height,'#fae8bc',28)])
    _icon(parts,'target',79,y+38,GREEN);_text(parts,'ГДЕ ПОЛЕЗНО',109,y+25,373,23,GREEN,True)
    _icon(parts,'limit',589,y+38,'#8b5b17');_text(parts,'ГДЕ ГРАНИЦЫ',619,y+25,373,23,'#785217',True)
    _bullets(parts,audience,72,y+89,426)
    _bullets(parts,limits,582,y+89,426)
    y += body_height+22
    resources = (_section_items(data,'resources','infrastructure') or ['Ресурсы и полная стоимость пока неизвестны.'])[:2]
    height = 90+_rows_height(resources,900,22)
    parts.append(('rect',40,y,1000,height,WHITE,28))
    _icon(parts,'stack',79,y+38,GREEN);_text(parts,'ЧТО ПОТРЕБУЕТСЯ',110,y+23,870,24,INK,True)
    _bullets(parts,resources,76,y+84,924)
    y += height+22
    next_step = data.get('next_step') or 'Уточнить рабочую задачу, baseline и проверяемые критерии.'
    height = 100+len(_wrap(next_step,900,25,True))*34
    parts.append(('rect',40,y,1000,height,INK,28))
    _icon(parts,'arrow',79,y+35,MINT);_text(parts,'ПЕРЕД ПИЛОТОМ',111,y+23,870,19,MINT,True)
    _text(parts,next_step,78,y+73,900,25,WHITE,True,gap=34)
    y += height+28
    y = _text(parts,'Авторские данные · собственных замеров нет · полные условия — в разборе',54,y,976,18,MUTED)+8
    urls=[]
    chart_sources=[row for comparison in comparisons for row in comparison.get('evidence',[])]
    for source in (chart_sources or data.get('evidence') or data.get('publication_sources') or data.get('sources') or [])[:4]:
        from .presentation import _public_url
        url=_public_url(source.get('source_url') or source.get('url','')) if isinstance(source,dict) else ''
        if url and url not in urls:urls.append(url)
    for url in urls:
        y = _text(parts,'Источник чисел: '+url if comparisons else 'Источник: '+url,54,y+5,976,15,MUTED,gap=21)
    y += 26
    if y>9000:raise ValueError('Инфографика слишком длинная; сократите редакционные поля.')
    parts.insert(0,('rect',0,0,W,y,PAPER,0))
    return int(y),parts


def render_infographic_svg(data):
    if isinstance(data.get('motion_story'), dict) and data['motion_story'].get('version') == 'dataflow-v1':
        from .motion_dashboard import render_svg
        return render_svg(data)
    height,parts=layout(data)
    from .adaptive_visual import profile_mode
    description = ('Выбранные формулировки, условия и границы из сохранённого отчёта. Собственных замеров нет.'
                   if profile_mode(data) in {'mechanism','infrastructure','applicability'} else
                   'Сравнение авторских данных, применение и ограничения из сохранённого отчёта. Новых измерений нет.'+(' Шкалы начинаются с нуля.' if _comparisons(data) else ''))
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height}" viewBox="0 0 {W} {height}" role="img">',
         '<title>'+html.escape(_clean(data.get('title','Прикладная инфографика')))+'</title>',
         '<desc>'+description+'</desc>']
    for item in parts:
        kind=item[0]
        if kind=='rect':
            _,x,y,w,h,color,r=item;out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{color}"/>')
        elif kind=='text':
            _,x,y,text,size,color,bold=item;out.append(f'<text x="{x}" y="{y}" dominant-baseline="text-before-edge" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{html.escape(text)}</text>')
        elif kind=='ring':
            _,x,y,r,width,fraction,color,bg=item;circumference=math.tau*r
            out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{bg}" stroke-width="{width}"/>')
            if fraction:out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-dasharray="{circumference*fraction} {circumference}" transform="rotate(-90 {x} {y})"/>')
        elif kind in {'circle','outline_circle'}:
            if kind=='circle':_,x,y,r,color=item;out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
            else:_,x,y,r,color,width=item;out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{color}" stroke-width="{width}"/>')
        elif kind=='outline_rect':
            _,x,y,w,h,color,width,r=item;out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="none" rx="{r}" stroke="{color}" stroke-width="{width}"/>')
        elif kind=='line':
            _,x,y,xx,yy,color,width=item;out.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{color}" stroke-width="{width}"/>')
        elif kind=='polygon':
            _,points,fill,color,width=item;out.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="{fill or "none"}" stroke="{color}" stroke-width="{width}"/>')
    return ''.join(out)+'</svg>'


def _raster(data,progress=1):
    height,parts=layout(data,progress)
    return _raster_parts(height,parts)


def _raster_parts(height,parts,font_factory=None):
    """Shared native-size rasterizer for static and adaptive animation panels."""
    from PIL import Image,ImageDraw
    picture=Image.new('RGB',(W,height),PAPER);draw=ImageDraw.Draw(picture)
    for item in parts:
        kind=item[0]
        if kind=='rect':
            _,x,y,w,h,color,r=item;draw.rounded_rectangle((x,y,x+w,y+h),r,fill=color)
        elif kind=='text':
            _,x,y,text,size,color,bold=item;draw.text((x,y),text,font=(font_factory or _font)(size,bold),fill=color,anchor='lt')
        elif kind=='polyline':
            _,points,color,width=item;draw.line(points,fill=color,width=max(1,round(width)),joint='curve')
        elif kind=='ring':
            _,x,y,r,width,fraction,color,bg=item;box=(x-r,y-r,x+r,y+r)
            draw.arc(box,0,360,fill=bg,width=width)
            if fraction:draw.arc(box,-90,-90+fraction*360,fill=color,width=width)
        elif kind in {'circle','outline_circle'}:
            if kind=='circle':_,x,y,r,color=item;draw.ellipse((x-r,y-r,x+r,y+r),fill=color)
            else:_,x,y,r,color,width=item;draw.ellipse((x-r,y-r,x+r,y+r),outline=color,width=width)
        elif kind=='outline_rect':
            _,x,y,w,h,color,width,r=item;draw.rounded_rectangle((x,y,x+w,y+h),r,outline=color,width=width)
        elif kind=='line':
            _,x,y,xx,yy,color,width=item;draw.line((x,y,xx,yy),fill=color,width=width)
        elif kind=='polygon':
            _,points,fill,color,width=item;draw.polygon(points,fill=fill);draw.line(points+[points[0]],fill=color,width=width)
    return picture


def render_infographic_png(data):
    if isinstance(data.get('motion_story'), dict) and data['motion_story'].get('version') == 'dataflow-v1':
        from .motion_dashboard import render_png
        return render_png(data)
    try:picture=_raster(data)
    except ImportError:return None
    output=io.BytesIO();picture.save(output,format='PNG',optimize=True);return output.getvalue()


def render_infographic_gif(data):
    """Reveal saved values without inventing intermediate measurements or speed."""
    if not _comparisons(data):return None
    try:
        from PIL import Image
    except ImportError:return None
    frames=[]
    # Reveal the recorded comparison; numerical labels and conditions stay fixed.
    for index in range(13):
        progress=1-(1-index/12)**3
        picture=_raster(data,progress)
        frames.append(picture.convert('P',palette=Image.Palette.ADAPTIVE,colors=256))
    output=io.BytesIO()
    frames[0].save(output,format='GIF',save_all=True,append_images=frames[1:],duration=[100]*12+[1800],loop=0,optimize=True)
    return output.getvalue()
