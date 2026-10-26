"""An explicitly schematic explanation of recorded-tree replay, not a benchmark."""
from __future__ import annotations

import html
import io
import math
import textwrap


WIDTH, HEIGHT = 1280, 940
BG, INK, MUTED = '#0b1420', '#eef4fb', '#92a4ba'
BLUE, GREEN, AMBER, PINK = '#78b8ff', '#69ddbc', '#f2c16c', '#dd91d9'


def replay_visual():
    nodes, edges = [], []
    for prefix, offset in [('fixed',0),('replay',620)]:
        nodes += [
            {'id':prefix+'_root','x':330+offset,'y':180,'label':'Задача','kind':'recorded','panel':prefix},
            {'id':prefix+'_a','x':190+offset,'y':285,'label':'Попытка A','kind':'recorded','panel':prefix},
            {'id':prefix+'_b','x':470+offset,'y':285,'label':'Попытка B','kind':'recorded','panel':prefix},
            {'id':prefix+'_a1','x':120+offset,'y':405,'label':'Известный исход','kind':'recorded','panel':prefix},
            {'id':prefix+'_a2','x':280+offset,'y':405,'label':'Известный исход','kind':'recorded','panel':prefix},
            {'id':prefix+'_b1','x':430+offset,'y':405,'label':'Известный исход','kind':'recorded','panel':prefix},
            {'id':prefix+'_u','x':570+offset,'y':405,'label':'Нет исхода','kind':'unknown','panel':prefix}]
        for parent,child in [('root','a'),('root','b'),('a','a1'),('a','a2'),('b','b1'),('b','u')]:
            edges.append({'id':prefix+'_'+parent+'_'+child,'from':prefix+'_'+parent,'to':prefix+'_'+child,
                          'dashed':child=='u','panel':prefix})
    nodes.append({'id':'replay_new','x':1090,'y':520,'label':'Новый исход','kind':'new','panel':'replay','reveal_scene':4})
    edges.append({'id':'replay_b1_new','from':'replay_b1','to':'replay_new','dashed':False,'panel':'replay','reveal_scene':4})
    scenes = [
        {'title':'1 · Есть только записанные исходы','phase':'history',
         'explanation':'Слева и справа одна и та же условная история. Сплошные ветви уже выполнялись; пунктирная ветвь не известна.',
         'active_edges':[],'active_nodes':[]},
        {'title':'2 · Фиксированная стратегия выбирает маршрут A','phase':'fixed',
         'explanation':'Обычная стратегия идёт по заранее выбранному порядку. Маркер показывает порядок рассмотрения, а не скорость.',
         'active_edges':['fixed_root_a','fixed_a_a1'],'active_nodes':['fixed_root','fixed_a','fixed_a1']},
        {'title':'3 · Кандидат выбирает другой маршрут на той же истории','phase':'replay',
         'explanation':'При replay используются уже записанные результаты. Повторять эти исполнения агента не нужно; новая стратегия не получает несуществующих данных.',
         'active_edges':['fixed_root_a','fixed_a_a1','replay_root_b','replay_b_b1'],
         'active_nodes':['fixed_root','fixed_a','fixed_a1','replay_root','replay_b','replay_b1']},
        {'title':'4 · Replay не открывает неизвестную ветвь','phase':'boundary',
         'explanation':'Неизвестное продолжение остаётся неизвестным. Улучшение оценки на истории не гарантирует результат на новой задаче.',
         'active_edges':['fixed_root_a','fixed_a_a1','replay_root_b','replay_b_b1'],
         'active_nodes':['replay_u']},
        {'title':'5 · Новые исходы появляются при следующем реальном поиске','phase':'online',
         'explanation':'В эксплуатации выбранная стратегия запускается онлайн и добавляет опыт. Здесь показана схема; новых запусков ради этой иллюстрации не было.',
         'active_edges':['replay_root_b','replay_b_b1','replay_b1_new'],
         'active_nodes':['replay_b1','replay_new']}]
    scenes[-1]['active_edges']=['fixed_root_a','fixed_a_a1',*scenes[-1]['active_edges']]
    scenes[-1]['active_nodes']=['fixed_root','fixed_a','fixed_a1',*scenes[-1]['active_nodes']]
    return {'kind':'replay_tree','caption':'Условные маршруты на одной истории. Нет оценок качества, времени или обещанного ускорения.',
            'graph':{'width':1280,'height':580,'nodes':nodes,'edges':edges},
            'scenes':scenes,
            'steps':[{'label':'История','text':'Сохранить дерево попыток и результаты оценивания.'},
                     {'label':'Replay','text':'Сравнить стратегии на доступных записанных ветвях.'},
                     {'label':'Новый поиск','text':'Применить выбранную стратегию и получить новые исходы.'}]}


def _lines(text, width, maximum):
    result=textwrap.wrap(str(text),width=width,break_long_words=True,break_on_hyphens=False)
    if len(result)>maximum:
        result=result[:maximum];result[-1]=result[-1].rstrip(' ,.;:')+'…'
    return result


def _scene(data, index):
    visual=data.get('visual') or replay_visual()
    scenes=visual.get('scenes') or replay_visual()['scenes']
    index=max(0,min(int(index),len(scenes)-1))
    return visual,scenes[index],index


def _elements(data,index=4,progress=1.0):
    visual,scene,index=_scene(data,index)
    graph=visual['graph'];nodes={n['id']:n for n in graph['nodes']}
    edges=graph['edges'];shift=185
    result=[('rect',0,0,WIDTH,HEIGHT,BG,0),
            ('text',46,45,'AI R&D LABORATORY · МЕХАНИЗМ ПО СОХРАНЁННОМУ ОТЧЁТУ',18,GREEN,False),
            ('rect',40,175,586,600,'#101f30',18),('rect',650,175,590,600,'#101f30',18),
            ('text',66,211,'ФИКСИРОВАННАЯ СТРАТЕГИЯ',21,BLUE,True),
            ('text',676,211,'КАНДИДАТ СТРАТЕГИИ / REPLAY',21,GREEN,True),
            ('text',66,243,'Выбор маршрута A',18,MUTED,False),
            ('text',676,243,'Другая последовательность на тех же данных',18,MUTED,False)]
    heading=_lines(str(data.get('title') or 'Как стратегия использует историю попыток'),58,2)
    for line_no,line in enumerate(heading):result.append(('text',46,95+line_no*37,line,34,INK,True))
    result.append(('text',46,136 if len(heading)==1 else 164,
                   'Одна история попыток → другой порядок поиска → новые данные только онлайн',20,MUTED,False))
    active=set(scene['active_edges'])
    for edge in edges:
        if edge.get('reveal_scene',0)>index:continue
        start,end=nodes[edge['from']],nodes[edge['to']]
        color=PINK if edge['to']=='replay_new' else BLUE if edge['panel']=='fixed' else GREEN
        if edge['id'] not in active:color='#3b4d63'
        result.append(('line',start['x'],start['y']+shift,end['x'],end['y']+shift,color,5 if edge['id'] in active else 2,edge['dashed']))
    for node in nodes.values():
        if node.get('reveal_scene',0)>index:continue
        kind=node['kind']
        color=AMBER if kind=='unknown' else PINK if kind=='new' else BLUE if node['panel']=='fixed' else GREEN
        highlighted=node['id'] in scene['active_nodes']
        result.append(('circle',node['x'],node['y']+shift,17 if kind!='unknown' else 16,
                       color if highlighted else '#13253a',color,4 if highlighted else 2))
        if kind=='unknown':result.append(('text',node['x']-6,node['y']+shift+6,'?',20,AMBER,True))
        for line_no,line in enumerate(_lines(node['label'],18,2)):
            result.append(('center',node['x'],node['y']+shift+42+line_no*20,line,17,color if highlighted else MUTED,False))
    # An actual moving marker, rather than alternating paragraph highlights.
    route = ['fixed_root_a','fixed_a_a1'] if index==1 else ['replay_root_b','replay_b_b1'] if index==2 else ['replay_b1_new'] if index==4 else []
    if route:
        p=max(0,min(progress,.999999))*len(route)
        edge=next(e for e in edges if e['id']==route[int(p)])
        a,c=nodes[edge['from']],nodes[edge['to']];f=p-int(p)
        x=a['x']+(c['x']-a['x'])*f;y=a['y']+(c['y']-a['y'])*f+shift
        result.append(('circle',x,y,9,PINK if index==4 else BLUE if index==1 else GREEN,'#ffffff',2))
    result.append(('rect',40,795,1200,111,'#17323a',14))
    result.append(('text',62,828,scene['title'],24,INK,True))
    for line_no,line in enumerate(_lines(scene['explanation'],105,2)):
        result.append(('text',62,860+line_no*25,line,20,'#d5e6ed',False))
    result.append(('text',44,932,'СХЕМА, НЕ БЕНЧМАРК · Маршруты и узлы условные; числа не изображают эксперимент.',16,MUTED,False))
    return result


def render_replay_svg(data):
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img">',
           '<title>'+html.escape(str(data.get('title') or 'Стратегия поиска по истории'))+'</title>',
           '<desc>Условная схема механизма, не является измерением. Пунктирная ветвь не имеет записанного исхода.</desc>']
    for item in _elements(data):
        if item[0]=='rect':
            _,x,y,w,h,color,r=item;parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{color}"/>')
        elif item[0]=='line':
            _,x,y,xx,yy,color,w,dash=item;parts.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{color}" stroke-width="{w}"'+(' stroke-dasharray="8 7"' if dash else '')+'/>')
        elif item[0]=='circle':
            _,x,y,r,fill,stroke,w=item;parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{w}"/>')
        else:
            kind,x,y,text,size,color,bold=item;parts.append(f'<text x="{x}" y="{y}" font-family="Segoe UI,Arial,sans-serif" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}"'+(' text-anchor="middle"' if kind=='center' else '')+'>'+html.escape(str(text))+'</text>')
    return ''.join(parts)+'</svg>'


def _picture(data,index,progress):
    from PIL import Image,ImageDraw
    from .presentation import _font
    picture=Image.new('RGB',(WIDTH,HEIGHT),BG);draw=ImageDraw.Draw(picture);fonts={}
    for item in _elements(data,index,progress):
        if item[0]=='rect':
            _,x,y,w,h,color,r=item;draw.rounded_rectangle((x,y,x+w,y+h),radius=r,fill=color)
        elif item[0]=='line':
            _,x,y,xx,yy,color,w,dash=item
            if dash:
                distance=math.hypot(xx-x,yy-y)
                for start in range(0,max(1,int(distance)),16):
                    a=start/max(1,distance);b=min(start+8,distance)/max(1,distance)
                    draw.line((x+(xx-x)*a,y+(yy-y)*a,x+(xx-x)*b,y+(yy-y)*b),fill=color,width=w)
            else:draw.line((x,y,xx,yy),fill=color,width=w)
        elif item[0]=='circle':
            _,x,y,r,fill,stroke,w=item;draw.ellipse((x-r,y-r,x+r,y+r),fill=fill,outline=stroke,width=w)
        else:
            kind,x,y,text,size,color,bold=item
            if (size,bold) not in fonts:fonts[size,bold]=_font(size,bold)
            draw.text((x,y),text,font=fonts[size,bold],fill=color,anchor='ms' if kind=='center' else 'ls')
    return picture


def render_replay_png(data):
    try:picture=_picture(data,4,1)
    except ImportError:return None
    output=io.BytesIO();picture.save(output,format='PNG',optimize=True);return output.getvalue()


def render_replay_gif(data):
    try:
        from PIL import Image
        frames=[];durations=[]
        for scene in range(5):
            steps=8 if scene in (1,2,4) else 4
            for frame in range(steps):
                picture=_picture(data,scene,frame/max(1,steps-1)).resize((960,705),Image.Resampling.LANCZOS)
                frames.append(picture.convert('P',palette=Image.Palette.ADAPTIVE,colors=128))
                durations.append(230 if frame<steps-1 else 1250)
    except ImportError:return None
    output=io.BytesIO();frames[0].save(output,format='GIF',save_all=True,append_images=frames[1:],
                                    duration=durations,loop=0,optimize=True,disposal=2)
    return output.getvalue()
