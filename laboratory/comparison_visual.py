"""Separate zero-based charts from reviewed numeric comparisons; never infer values."""
from __future__ import annotations

import html
import io
import math
import textwrap

WIDTH=1200
BG,PANEL,INK,MUTED='#0b1420','#112033','#f0f5fb','#9aacbf'
BLUE,GREEN='#80baff','#6cddbc'


def _lines(value,width=95,limit=2):
    lines=textwrap.wrap(str(value),width=width,break_long_words=True,break_on_hyphens=False)
    if len(lines)>limit:
        lines=lines[:limit];lines[-1]=lines[-1].rstrip(' ,.;:')+'…'
    return lines


def _number(value):
    return str(value).replace('.',',')


def _axis(values):
    maximum=max(values)
    if not maximum:return 1,[0,.25,.5,.75,1]
    rough=maximum/4
    if not rough:return maximum,[0,maximum]
    scale=10.0**math.floor(math.log10(rough))
    if not scale:return maximum,[0,maximum]
    step=next(number*scale for number in (1,2,2.5,5,10) if number*scale>=rough)
    limit=math.ceil(maximum/step)*step
    if not math.isfinite(limit):return maximum,[0,maximum/2,maximum]
    precision=max(0,2-math.floor(math.log10(step)))
    return limit,[round(index*step,precision) for index in range(round(limit/step)+1)]


def _origin(chart):
    basis={item.get('basis') for item in chart.get('evidence',[])}
    if basis=={'saved_report'}:
        return 'По сохранённому отчёту: авторские данные; собственных замеров нет.'
    labels={'saved_report':'сохранённый отчёт','local_record':'локальная запись',
            'editor_assessment':'редакторская оценка','missing':'недостающие данные'}
    origins=[label for key,label in labels.items() if key in basis]
    return 'Основание: '+(', '.join(origins) or 'см. журнал доказательств')+'. Новых измерений не было.'


def _layout(data):
    charts=data.get('comparisons',[])[:3]
    parts=[('text',42,42,'AI R&D LABORATORY · ДАННЫЕ СОХРАНЁННОГО РАЗБОРА',17,GREEN,False)]
    for index,line in enumerate(_lines(data.get('title') or 'Сравнение результатов',59,2)):
        parts.append(('text',42,92+index*36,line,33,INK,True))
    parts.append(('text',42,157,'Показатели показаны отдельно. Шкалы начинаются с нуля; условия — под каждым графиком.',18,MUTED,False))
    top=180
    for chart in charts:
        title_lines=_lines(chart['label'],77,4)
        label_lines=[_lines(chart[key],25,8) for key in ('baseline_label','result_label')]
        row_height=max(58,max(map(len,label_lines))*20+12)
        start=top+38+len(title_lines)*27
        conditions=_lines('Условия: '+chart['conditions'],111,40)
        origin=_lines(_origin(chart),111,4)
        conditions_y=start+row_height*2+30
        panel_height=conditions_y-top+len(conditions)*23+len(origin)*23+21
        parts.append(('rect',38,top,1124,panel_height,PANEL,18))
        for line_index,line in enumerate(title_lines):
            parts.append(('text',62,top+34+line_index*27,line,24,INK,True))
        values=chart['baseline_value'],chart['result_value']
        maximum,ticks=_axis(values)
        x,width=330,585
        unit='Единица: '+chart['unit']
        parts.append(('text',x,start-10,unit,16,MUTED,False))
        for tick in ticks:
            at=x+width*(tick/maximum)
            parts.append(('line',at,start+3,at,start+row_height+35,'#30445b',1))
            label=(format(tick,'.5g').replace('.',',') if abs(tick)>=1e7 or 0<abs(tick)<.001
                   else _number(int(tick) if float(tick).is_integer() else tick))
            parts.append(('text',at-4,start+row_height*2+10,label,15,MUTED,False))
        for row,(label,value,color) in enumerate(zip((chart['baseline_label'],chart['result_label']),values,(BLUE,GREEN))):
            y=start+row*row_height
            for line_index,line in enumerate(label_lines[row]):
                parts.append(('text',62,y+18+line_index*19,line,18,INK,row==1))
            length=width*(value/maximum)
            parts.append(('rect',x,y,length,35,color,4))
            parts.append(('text',x+length+12,y+25,_number(value),22,color,True))
        for line_index,line in enumerate(conditions+origin):
            parts.append(('text',62,conditions_y+line_index*23,line,17,MUTED,False))
        top+=panel_height+20
    footer=top+14
    parts.extend([('text',42,footer,'Значения и условия перенесены из редакторского разбора; основания — в журнале доказательств.',18,INK,False),
                  ('text',42,footer+29,'Вызовы агента сами по себе не равны полной стоимости; результат не переносится на другие задачи автоматически.',17,MUTED,False)])
    links=[]
    for chart in charts:
        for evidence in chart.get('evidence',[]):
            url=evidence.get('source_url')
            if isinstance(url,str) and url.startswith(('http://','https://')) and url not in links:links.append(url)
    for index,url in enumerate(links[:2]):
        for line_no,line in enumerate(_lines('Источник: '+url,125,1)):
            parts.append(('text',42,footer+59+index*23,line,15,MUTED,False))
    height=footer+125
    parts.insert(0,('rect',0,0,WIDTH,height,BG,0))
    return height,parts


def render_comparison_svg(data):
    height,parts=_layout(data)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" viewBox="0 0 {WIDTH} {height}" role="img">',
         '<title>'+html.escape(str(data.get('title') or 'Сравнения по сохранённому отчёту'))+'</title>',
         '<desc>Каждый показатель имеет отдельную шкалу с нулём. Условия подписаны. Это не новые измерения лаборатории.</desc>']
    for item in parts:
        if item[0]=='rect':
            _,x,y,w,h,color,r=item;out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{color}"/>')
        elif item[0]=='line':
            _,x,y,xx,yy,color,width=item;out.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{color}" stroke-width="{width}"/>')
        else:
            _,x,y,text,size,color,bold=item;out.append(f'<text x="{x}" y="{y}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{html.escape(text)}</text>')
    return ''.join(out)+'</svg>'


def render_comparison_png(data):
    try:
        from PIL import Image,ImageDraw
        from .presentation import _font
    except ImportError:return None
    height,parts=_layout(data);picture=Image.new('RGB',(WIDTH,height),BG);draw=ImageDraw.Draw(picture);fonts={}
    for item in parts:
        if item[0]=='rect':
            _,x,y,w,h,color,r=item;draw.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=color)
        elif item[0]=='line':
            _,x,y,xx,yy,color,width=item;draw.line((x,y,xx,yy),fill=color,width=width)
        else:
            _,x,y,text,size,color,bold=item
            if (size,bold) not in fonts:fonts[size,bold]=_font(size,bold)
            draw.text((x,y),text,font=fonts[size,bold],fill=color,anchor='ls')
    output=io.BytesIO();picture.save(output,format='PNG',optimize=True);return output.getvalue()
