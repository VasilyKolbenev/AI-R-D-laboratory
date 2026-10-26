"""Native 1080px evidence dashboard with illustrative artifact motion.

The graph is supplied by ``motion_story``. Neither geometry nor animation
infers benchmarks, execution time, throughput, or experiment results.
"""
from __future__ import annotations

import html
import io
import math

from .reader_infographic import _clean, _comparisons, _font, _number, _width, _wrap
from . import blackboard

W = 1080
BG, PANEL, SURFACE = '#080d16', '#0e1725', '#121f30'
WHITE, MUTED, LINE, GRID = '#edf5ff', '#a4b4c8', '#294057', '#102031'
CYAN, MAGENTA, AMBER, BASE = '#5ae1ed', '#e795d2', '#edbd73', '#9cafc4'
MOTION_NOTICE = 'Схема · скорость не измерена.'
LAYOUT_VERSION = 'measured-node-height-v2'


def _text(parts, value, x, y, width, size=26, color=WHITE, bold=False, gap=None):
    gap = gap or round(size * 1.26)
    for line in _wrap(value, width, size, bold, blackboard.font if getattr(parts,'hand',False) else None):
        parts.append(('text', x, y, line, size, color, bold))
        y += gap
    return y


def _panel(parts, x, y, width, height, color=PANEL, radius=20):
    parts.extend([('rect', x, y, width, height, color, radius),
                  ('outline_rect', x, y, width, height, LINE, 1, radius)])


def _length(points):
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def _at(points, distance):
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if distance <= length:
            fraction = distance / length if length else 0
            return a[0] + (b[0]-a[0])*fraction, a[1] + (b[1]-a[1])*fraction
        distance -= length
    return points[-1]


def _topological(nodes, edges):
    ids = {n['id'] for n in nodes}
    incoming = {key: 0 for key in ids}
    nexts = {key: [] for key in ids}
    for edge in edges:
        a, b = edge.get('from'), edge.get('to')
        if edge.get('kind') != 'feedback' and a in ids and b in ids and a != b:
            incoming[b] += 1
            nexts[a].append(b)
    queue = [n['id'] for n in nodes if not incoming[n['id']]]
    ordered, ranks = [], {key: 0 for key in ids}
    while queue:
        key = queue.pop(0)
        if key in ordered:
            continue
        ordered.append(key)
        for nxt in nexts[key]:
            ranks[nxt] = max(ranks[nxt], ranks[key]+1)
            incoming[nxt] -= 1
            if incoming[nxt] == 0:
                queue.append(nxt)
    ordered.extend(n['id'] for n in nodes if n['id'] not in ordered)
    return ordered, ranks


def _positions(nodes, edges, kind, y, hand=False):
    """Topology layouts keyed by mechanism class, never by product/node IDs."""
    order, ranks = _topological(nodes, edges)
    boxes = {}
    layers = {}
    font_provider = blackboard.font if hand else None
    node_height = max((len(_wrap(n.get('label', ''), 242, 26, True, font_provider)) * 32 + 20
                       for n in nodes), default=104)
    for key in order:
        layers.setdefault(ranks[key], []).append(key)
    if kind == 'review' and any(len(keys)>1 for keys in layers.values()) and len(layers)<=6:
        # Fan out the source-supported independent searches, then merge the
        # findings. The number of drawn branches is schematic, never measured.
        for rank, keys in layers.items():
            column = rank if rank<3 else 5-rank
            for row,key in enumerate(keys):
                height=max(104,node_height)
                at = y+(row*(height+16) if len(keys)>1 else (height+16)/2) if rank<3 else y+2*(height+26)
                boxes[key]=(82+column*318,at,278,height)
        return boxes,max((b[1]+b[3] for b in boxes.values()),default=y)
    if kind == 'inference':
        top=y
        by_id={node['id']:node for node in nodes}
        for keys in layers.values():
            spacing = 920 / max(1, len(keys))
            width = min(300, spacing-42)
            height=max(84,max(len(_wrap(by_id[key].get('label',''),width-36,26,True,blackboard.font if hand else None))*32+20 for key in keys))
            for col, key in enumerate(keys):
                boxes[key] = (80+spacing*(col+.5)-width/2,top,width,height)
            top+=height+32
        return boxes, max((b[1]+b[3] for b in boxes.values()), default=y)
    if kind == 'feedback':
        # Three stages across the top; memory and next task return below.
        columns = min(3, max(1, len(order)))
        rows = math.ceil(len(order)/columns)
        height=max(112,node_height)
        for index, key in enumerate(order):
            row, col = divmod(index, columns)
            if row % 2:
                col = columns-col-1
            boxes[key] = (82+col*318, y+row*(height+118), 278, height)
        return boxes, y+(rows-1)*(height+118)+height
    columns = min(3, max(1, len(order)))
    rows = math.ceil(len(order)/columns)
    height=max(112,node_height)
    for index, key in enumerate(order):
        row, col = divmod(index, columns)
        if row % 2:
            col = columns-col-1
        boxes[key] = (82+col*318, y+row*(height+90), 278, height)
    return boxes, y+(rows-1)*(height+90)+height


def _route(a, b, feedback=False, bottom=None):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ac, bc = (ax+aw/2, ay+ah/2), (bx+bw/2, by+bh/2)
    if feedback:
        # A visible return channel is outside the forward flow.
        lower = bottom or max(ay+ah, by+bh)+58
        return [(ac[0], ay+ah), (ac[0], lower), (56, lower),
                (56, by-12), (bc[0],by-12), (bc[0],by)]
    if abs(ac[1]-bc[1]) < 10:
        if abs(ac[0]-bc[0]) > max(aw,bw)*1.5:
            lower=max(ay+ah,by+bh)+30
            return [(ac[0],ay+ah),(ac[0],lower),(bc[0],lower),(bc[0],by+bh)]
        direction = 1 if bc[0] > ac[0] else -1
        return [(ac[0]+direction*aw/2, ac[1]), (bc[0]-direction*bw/2, bc[1])]
    if abs(ac[0]-bc[0]) > max(aw,bw)*.6 and abs(ac[1]-bc[1]) < max(ah,bh)*1.7:
        direction=1 if bc[0]>ac[0] else -1
        start=(ac[0]+direction*aw/2,ac[1])
        end=(bc[0]-direction*bw/2,bc[1])
        middle=(start[0]+end[0])/2
        return [start,(middle,start[1]),(middle,end[1]),end]
    if abs(ac[0]-bc[0]) < 15:
        return [(ac[0], ay+ah), (bc[0], by)] if bc[1] > ac[1] else [(ac[0], ay), (bc[0], by+bh)]
    if bc[1] > ac[1]:
        middle = (ay+ah+by)/2
        return [(ac[0], ay+ah), (ac[0], middle), (bc[0], middle), (bc[0], by)]
    middle = (by+bh+ay)/2
    return [(ac[0], ay), (ac[0], middle), (bc[0], middle), (bc[0], by+bh)]


def _arrow(parts, points, color, width=2):
    for (x, y), (xx, yy) in zip(points, points[1:]):
        parts.append(('line', x, y, xx, yy, color, width))
    if len(points) > 1:
        x, y = points[-1]
        px, py = points[-2]
        angle = math.atan2(y-py, x-px)
        tip = [(x, y), (x-10*math.cos(angle-.48), y-10*math.sin(angle-.48)),
               (x-10*math.cos(angle+.48), y-10*math.sin(angle+.48))]
        parts.append(('polygon', tip, color, color, 1))


def _packet(parts, x, y, color, kind='data'):
    if kind == 'feedback':
        parts.append(('polygon', [(x,y-8),(x+8,y),(x,y+8),(x-8,y)], color, color, 1))
    elif kind == 'control':
        parts.extend([('circle',x,y,7,BG),('outline_circle',x,y,7,color,2)])
    else:
        parts.extend([('rect',x-8,y-10,16,20,color,3),
                      ('line',x-4,y-4,x+4,y-4,BG,1),('line',x-4,y+1,x+4,y+1,BG,1)])


def packet_positions(data, progress):
    """Coordinates for QA; all lanes use the same illustrative px/phase rate."""
    _, _, routes = _diagram(data, 0, float(progress), True, collect=True)
    return routes


def _node(parts, node, box, color, progress=1, animation=False):
    x, y, w, h = box
    role = node.get('role','compute')
    hand=getattr(parts,'hand',False)
    if hand:
        color={'input':CYAN,'memory':'#b7a1ff','decision':AMBER,
               'output':'#74df8b'}.get(role,WHITE)
        parts.extend([('rect',x,y,w,h,BG,14),('outline_rect',x,y,w,h,color,2,14)])
    else:
        _panel(parts,x,y,w,h,SURFACE,14)
        parts.append(('rect',x,y+15,3,h-30,color,1))
    sx, sy = x+w-15, y+11
    if role == 'memory':
        for index in range(3):
            parts.append(('outline_rect',sx-13,sy-8+index*7,20,5,color,1,1))
    elif role == 'decision':
        parts.append(('polygon',[(sx,sy-8),(sx+8,sy),(sx,sy+8),(sx-8,sy)],None,color,1))
    else:
        parts.append(('outline_rect',sx-7,sy-8,14,16,color,1,2))
    label = node.get('label') or node.get('id','')
    size = 26
    lines = _wrap(label,w-36,size,True,blackboard.font if hand else None)
    # Bounded graph labels are wrapped completely; boxes grow when necessary.
    top = y+(h-len(lines)*32)/2
    _text(parts,label,x+18,top,w-36,size,WHITE,True,gap=32)


def _parallel_insets(parts, story, y, progress, animation, packet_points):
    """Disconnected operation insets make no dependency/hardware claim."""
    notes=' '.join(story.get('notes') or []).casefold()
    groups=[]
    if 'вниман' in notes and 'эксперт' in notes:
        groups.append((72,'Параллелизм операций',('Внимание','Эксперты')))
    if 'подготов' in notes and 'вычислен' in notes:
        groups.append((728,'Совмещение работы',('Подготовка пакетов','Вычисления')))
    for x,title,labels in groups:
        _panel(parts,x,y+110,280,350,'#101d2b',14)
        at=_text(parts,title,x+18,y+129,244,23,CYAN,True,gap=29)+24
        for index,label in enumerate(labels):
            at=_text(parts,label,x+18,at,244,23,WHITE,gap=29)+16
            points=[(x+22,at),(x+258,at)]
            _arrow(parts,points,LINE)
            distance=(progress*1100+index*80)%236 if animation else 118
            p=_at(points,distance)
            _packet(parts,*p,CYAN)
            if animation:
                packet_points.append(('inset_'+str(x)+'_'+str(index),*p))
            at+=35
        _text(parts,'Схематично',x+18,y+383,244,19,MUTED,gap=24)


def _diagram(data, y, progress, animation, collect=False):
    story = data.get('motion_story') or {}
    nodes = [n for n in story.get('nodes',[]) if isinstance(n,dict) and n.get('id')]
    edges = [e for e in story.get('edges',[]) if isinstance(e,dict)]
    baseline = story.get('baseline') or {'status':'unknown','label':'Baseline не определён','note':'Сопоставимый процесс не описан.'}
    base_nodes = [n for n in nodes if n.get('lane') == 'baseline']
    tech_nodes = [n for n in nodes if n.get('lane') != 'baseline']
    parts, packet_points = blackboard.Parts(blackboard.selected(data)), []
    _text(parts,'ПОТОК ДАННЫХ',64,y+25,900,20,CYAN,True)
    _packet(parts,742,y+36,CYAN)
    _text(parts,'Данные',758,y+25,112,18,MUTED)
    if any(e.get('kind')=='feedback' for e in edges):
        _packet(parts,884,y+36,MAGENTA,'feedback')
        _text(parts,'Опыт',900,y+25,112,18,MAGENTA)
    top = y+67
    status = baseline.get('status','unknown')
    label = baseline.get('label') or 'Исходный процесс'
    _text(parts,label,66,top,948,26,AMBER if status=='unknown' else BASE,True)
    top += 39
    if status == 'unknown' or not base_nodes:
        _panel(parts,64,top,952,62,'#191c24',14)
        parts.extend([('outline_circle',91,top+27,10,AMBER,2),('line',91,top+21,91,top+29,AMBER,2),('circle',91,top+34,1.5,AMBER)])
        _text(parts,'Нет данных для сопоставления.',114,top+16,876,24,AMBER,gap=30)
        top += 82
    else:
        order, _ = _topological(base_nodes,edges)
        by_id = {n['id']:n for n in base_nodes}
        spacing = 952/max(1,len(order))
        base_height=max(94,max(len(_wrap(by_id[key].get('label',''),spacing-62,26,True,blackboard.font if parts.hand else None))*32+20 for key in order))
        base_boxes = {key:(64+index*spacing,top,spacing-26,base_height) for index,key in enumerate(order)}
        for edge in edges:
            if edge.get('from') in base_boxes and edge.get('to') in base_boxes:
                route = _route(base_boxes[edge['from']],base_boxes[edge['to']])
                _arrow(parts,route,BASE)
                if animation:
                    length = _length(route)
                    p = _at(route,(progress*1100) % max(1,length))
                    _packet(parts,*p,BASE,edge.get('kind','data'))
                    packet_points.append((edge.get('id'),*p))
        for key in order:
            _node(parts,by_id[key],base_boxes[key],BASE,progress,animation)
        top += base_height+10
        note = 'Схематическое сравнение' if status == 'conceptual' else 'Baseline из отчёта'
        top = _text(parts,note,66,top,948,22,MUTED,gap=28)+10
    _text(parts,'С ТЕХНОЛОГИЕЙ',66,top,948,20,CYAN,True)
    if story.get('kind')=='feedback':
        _text(parts,'ВЕСА МОДЕЛИ ФИКСИРОВАНЫ',658,top,358,16,BASE,True)
    top += 40
    boxes, graph_bottom = _positions(tech_nodes,edges,story.get('kind','process'),top,parts.hand)
    if story.get('kind')=='inference':
        _parallel_insets(parts,story,top,progress,animation,packet_points)
    by_id = {n['id']:n for n in tech_nodes}
    edge_labels = []
    for index, edge in enumerate(edges):
        a, b = edge.get('from'), edge.get('to')
        if a not in boxes or b not in boxes:
            continue
        feedback = edge.get('kind') == 'feedback'
        route = _route(boxes[a],boxes[b],feedback,graph_bottom+48)
        color = MAGENTA if feedback else CYAN
        _arrow(parts,route,MAGENTA if feedback else LINE,2)
        length = _length(route)
        if animation:
            # Constant arc-length rate shared by baseline and technology lanes.
            distance = progress*1100
            for offset in (0,310):
                local = (distance+offset) % max(1,length+110)
                if local <= length:
                    p = _at(route,local)
                    _packet(parts,*p,color,edge.get('kind','data'))
                    packet_points.append((edge.get('id'),*p))
        else:
            p = _at(route,length*.5)
            _packet(parts,*p,color,edge.get('kind','data'))
        label = _clean(edge.get('label',''))
        if label and feedback:
            edge_labels.append((label,MAGENTA if feedback else MUTED))
    for node in tech_nodes:
        _node(parts,node,boxes[node['id']],CYAN,progress,animation)
    bottom = graph_bottom+78 if any(e.get('kind')=='feedback' for e in edges) else graph_bottom+24
    # Keep the feedback scope visible; forward arrows already connect labelled
    # operations. Full edge annotations remain in accessible SVG metadata.
    unique = list(dict.fromkeys(edge_labels))
    if unique:
        for index in range(0,len(unique),2):
            row_bottom=bottom
            for col,(label,color) in enumerate(unique[index:index+2]):
                row_bottom=max(row_bottom,_text(parts,'→ '+label,70+col*486,bottom,460,24,color,gap=30))
            bottom=row_bottom+5
        bottom+=12
    if not tech_nodes:
        bottom = _text(parts,'Недостаточно данных для схемы механизма.',66,top,948,28,AMBER)+48
    return bottom+10,parts,packet_points


def _metric(parts, item, y, index):
    top = y
    _text(parts,'АВТОРСКИЕ ДАННЫЕ / '+str(index+1),66,top,900,20,MUTED,True)
    top = _text(parts,item['label'],66,top+36,948,28,WHITE,True,gap=35)+15
    percent = item['unit'].strip().casefold() in {'%','процент','процентов','проценты'} and max(item['baseline_value'],item['result_value'])<=100
    maximum = 100 if percent else max(item['baseline_value'],item['result_value']) or 1
    _text(parts,'0',370,top-17,80,14,MUTED)
    _text(parts,'100%' if percent else _number(maximum)+' '+item['unit'],780,top-17,100,14,MUTED)
    for row,(value,label,color) in enumerate(((item['baseline_value'],item['baseline_label'],BASE),(item['result_value'],item['result_label'],CYAN))):
        at=top+row*48
        number = _number(value)+('%' if percent else ' '+item['unit'])
        _text(parts,label,66,at+3,300,24,MUTED)
        parts.append(('rect',370,at+10,480,13,LINE,6))
        if value:
            parts.append(('rect',370,at+10,480*value/maximum,13,color,6))
        _text(parts,number,870,at-6,152,36,color,True)
    top += 96
    conditions = item['conditions']
    caveats = list(dict.fromkeys(e.get('limitations','') for e in item.get('evidence',[]) if e.get('limitations')))
    top = _text(parts,conditions,66,top,948,22,MUTED,gap=26)
    for caveat in caveats:
        top = _text(parts,caveat,66,top+8,948,22,AMBER,gap=26)
    parts.append(('line',64,top+20,1016,top+20,LINE,1))
    return top+32


def _applied_rows(data):
    analysis=data.get('applied_analysis') or {}
    if not isinstance(analysis,dict) or analysis.get('version')!='applied-comparison-v1':
        return []
    return [row for row in analysis.get('rows',[]) if isinstance(row,dict)
            and isinstance(row.get('baseline'),dict) and isinstance(row.get('candidate'),dict)][:3]


def _row_key(row):
    return (row.get('metric'),row.get('unit'),row['baseline'].get('label'),
            row['baseline'].get('value'),row['candidate'].get('label'),row['candidate'].get('value'))


def _chart_key(row):
    return tuple(row.get(key) for key in ('label','unit','baseline_label','baseline_value','result_label','result_value'))


def _applied_table(parts,row,y):
    """Unpaired/incompatible observations get a labelled table, never bars."""
    y=_text(parts,row.get('metric') or 'Показатель',66,y+8,948,26,WHITE,True,gap=33)+12
    bottom=y
    bases={'author_claim':'Данные авторов','external_measurement':'Внешние замеры',
           'estimate':'Оценка','hypothesis':'Гипотеза','unknown':'Нет данных'}
    for side,x,color in (('baseline',66,BASE),('candidate',552,CYAN)):
        value=row[side]
        at=_text(parts,value.get('label') or ('Baseline' if side=='baseline' else 'Кандидат'),x,y,444,24,MUTED,True,gap=30)+5
        number=value.get('value')
        known=type(number) in {int,float} and math.isfinite(number)
        prefix='≈ ' if value.get('basis') in {'estimate','hypothesis'} else ''
        number_text=prefix+_number(number)+' '+str(row.get('unit') or '') if known else 'н/д'
        at=_text(parts,number_text,x,at,444,36,color if known else AMBER,True,gap=44)+4
        at=_text(parts,bases.get(value.get('basis'),'Нет данных'),x,at,444,20,MUTED,gap=25)
        bottom=max(bottom,at)
    status={'not_comparable':'Разные условия — прямого сравнения нет.',
            'unknown':'Сопоставимость не установлена.',
            'comparable':'Оценка требует проверки; измеренный эффект не установлен.'}
    y=_text(parts,status.get(row.get('comparability'),status['unknown']),66,bottom+12,948,22,AMBER,gap=27)
    for note in dict.fromkeys(str(row.get(key) or '') for key in ('conditions','comparability_reason')):
        if note:
            y=_text(parts,note,66,y+7,948,22,MUTED,gap=27)
    parts.append(('line',64,y+18,1016,y+18,LINE,1))
    return y+30


def _visual_metrics(data):
    rows=_applied_rows(data)
    charts=_comparisons(data)
    if not rows:
        return charts,[],0
    # At most two observations on the image. The full matrix stays in the
    # report/UI. Prefer grounded comparable charts; never duplicate one as a table.
    charts=charts[:2]
    drawn={_chart_key(row) for row in charts}
    tables=[row for row in rows if _row_key(row) not in drawn][:max(0,2-len(charts))]
    return charts,tables,len(rows)


def _sources(data):
    from .presentation import _public_url
    story = data.get('motion_story') or {}
    rows = list(story.get('sources') or [])
    rows += [e for c in _comparisons(data) for e in c.get('evidence',[])]
    refs={ref for row in _applied_rows(data) for side in ('baseline','candidate')
          for ref in row[side].get('evidence_ids',[])}
    rows += [e for e in data.get('evidence',[]) if isinstance(e,dict) and e.get('id') in refs]
    if not rows:
        rows = data.get('publication_sources') or data.get('sources') or []
    result = []
    for source in rows:
        url = _public_url(source.get('url') or source.get('source_url','')) if isinstance(source,dict) else ''
        if url and url not in result:
            result.append(url)
    return result


def _visible_sources(data):
    """One primary reference plus every numeric claim's evidence reference."""
    from .presentation import _public_url
    result = _sources(data)[:1]
    for item in _comparisons(data):
        for evidence in item.get('evidence',[]):
            url = _public_url(evidence.get('source_url') or evidence.get('url',''))
            if url and url not in result:
                result.append(url)
    refs={ref for row in _applied_rows(data) for side in ('baseline','candidate')
          for ref in row[side].get('evidence_ids',[])}
    for evidence in data.get('evidence',[]):
        if isinstance(evidence,dict) and evidence.get('id') in refs:
            url=_public_url(evidence.get('source_url') or evidence.get('url',''))
            if url and url not in result:
                result.append(url)
    return result


def _scope(story):
    return {
        'review': 'Решение об одобрении — у человека.',
        'feedback': 'Перенос опыта ≠ доказанный выигрыш.',
        'inference': 'Топология не установлена.',
    }.get(story.get('kind'), 'Порядок операций, без оценки эффекта.')


def _evidence_focus(data):
    from .research_public import _story
    return _story(data.get('evidence_story'), set(_sources(data)))


def _evidence_panel(parts, story, y):
    if not story:
        return y
    labels = {
        'comparison': 'ЧТО ПОКАЗЫВАЮТ ЧИСЛА',
        'mechanism': 'МЕХАНИЗМ И ЕГО ОСНОВАНИЯ',
        'applicability': 'УСЛОВИЯ ПРИМЕНЕНИЯ',
        'disagreement': 'ГДЕ ИСТОЧНИКИ РАСХОДЯТСЯ',
    }
    color = AMBER if story['focus'] == 'disagreement' else CYAN
    y = _text(parts, labels[story['focus']], 66, y, 948, 20, color, True) + 10
    y = _text(parts, story['summary'][:280], 66, y, 948, 25, WHITE, True) + 10
    for note in story['limitations'][:2]:
        y = _text(parts, note[:160], 66, y, 948, 21, MUTED, gap=27) + 6
    parts.append(('line', 64, y + 8, 1016, y + 8, LINE, 1))
    return y + 25


def layout(data, progress=1.0, animation=False):
    """Return height and renderer-compatible primitives; never mutate input."""
    progress = max(0,min(1,float(progress)))
    story = data.get('motion_story') or {}
    hand=blackboard.selected(data)
    parts = blackboard.Parts(hand)
    _text(parts,'VV FRONTIER',54,35,600,20,CYAN,True)
    parts.append(('line',54,76,1026,76,LINE,1))
    y = _text(parts,data.get('title') or 'Как работает технология',54,98,972,43,WHITE,True,gap=52)+18
    if hand:
        parts.append(('line',56,y-6,352,y-6,AMBER,3))
        y+=15
    y = _evidence_panel(parts, _evidence_focus(data), y)
    charts,tables,metric_count=_visual_metrics(data)
    if tables:
        y=_text(parts,'ПРИКЛАДНОЕ СРАВНЕНИЕ',66,y,948,20,CYAN,True)+9
    for index,item in enumerate(charts):
        y = _metric(parts,item,y,index)
    for row in tables:
        y=_applied_table(parts,row,y)
    if metric_count>len(charts)+len(tables):
        y=_text(parts,'На визуале '+str(len(charts)+len(tables))+' из '+str(metric_count)+' показателей · полная матрица в разборе',66,y,948,19,MUTED)+16
    graph_top = y
    y, diagram, _ = _diagram(data,y,progress,animation)
    # Put the spacious graph panel behind the graph primitives.
    _panel(parts,40,graph_top,1000,y-graph_top,PANEL,22)
    parts.extend(diagram)
    y += 20
    y = _text(parts,MOTION_NOTICE,58,y,964,21,MUTED,gap=27)+18
    y = _text(parts,_scope(story),58,y,964,23,AMBER,gap=29)+10
    y += 7
    parts.append(('line',54,y,1026,y,LINE,1))
    y = _text(parts,'Собственных замеров нет · подробности в разборе',56,y+20,968,19,MUTED,gap=25)+10
    for index,url in enumerate(_visible_sources(data),1):
        y = _text(parts,str(index).zfill(2)+'  '+url,56,y,968,16,MUTED,gap=21)+4
    height = max(1080,int(y+20))
    height += height % 2  # Pad, never rescale, for native H.264 yuv420 frames.
    if height > 3000:
        raise ValueError('Слишком много текста для dashboard; сократите редакционные поля.')
    background=[('rect',0,0,W,height,BG,0)]
    # Fine quiet grid: structure without decoration competing with the data.
    for gx in range(24,W,48):
        background.append(('line',gx,0,gx,height,GRID,1))
    for gy in range(20,height,48):
        background.append(('line',0,gy,W,gy,GRID,1))
    combined=background+parts
    return height,blackboard.transform(combined) if hand else combined


def frame(data, progress):
    """An RGB PIL image at native publication width (no reduced motion proxy)."""
    from .reader_infographic import _raster_parts
    height,parts=layout(data,progress,animation=True)
    return _raster_parts(height,parts,blackboard.font if blackboard.selected(data) else None)


def render_png(data):
    from .reader_infographic import _raster_parts
    height,parts=layout(data)
    picture=_raster_parts(height,parts,blackboard.font if blackboard.selected(data) else None)
    output=io.BytesIO()
    picture.save(output,format='PNG',optimize=True)
    return output.getvalue()


def render_svg(data):
    height,parts=layout(data)
    story = data.get('motion_story') or {}
    # Preserve original context without repeating the post on the image. This
    # metadata is accessible to SVG readers and does not enter PNG/video text.
    context = ' '.join(str(value) for value in [
        data.get('problem') or data.get('summary') or '',
        (story.get('baseline') or {}).get('note',''),
        *(story.get('notes') or []), data.get('numeric_note') or '',
        *(edge.get('label','') for edge in story.get('edges',[]) if isinstance(edge,dict)),
        *_sources(data),
    ] if value)
    out=[f'<svg xmlns="http://www.w3.org/2000/svg" width="1080" height="{height}" viewBox="0 0 1080 {height}" role="img">',
         '<title>'+html.escape(_clean(data.get('title','Механизм технологии')))+'</title>',
         '<desc>Схема объясняет идею, не замер скорости. '+MOTION_NOTICE+
         ' Авторские данные и границы из сохранённого отчёта; собственных замеров нет.'+
         (' Шкалы начинаются с нуля.' if _comparisons(data) else '')+
         ' '+html.escape(context)+'</desc>']
    for item in parts:
        kind=item[0]
        if kind=='rect':
            _,x,y,w,h,color,r=item
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{color}"/>')
        elif kind=='outline_rect':
            _,x,y,w,h,color,width,r=item
            out.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="none" stroke="{color}" stroke-width="{width}"/>')
        elif kind=='text':
            _,x,y,value,size,color,bold=item
            family=blackboard.family(size) if blackboard.selected(data) else 'Segoe UI,Arial,sans-serif'
            out.append(f'<text x="{x}" y="{y}" dominant-baseline="text-before-edge" font-family="{family}" font-size="{size}" font-weight="{700 if bold else 400}" fill="{color}">{html.escape(value)}</text>')
        elif kind=='polyline':
            _,points,color,width=item
            out.append('<polyline points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
        elif kind=='line':
            _,x,y,xx,yy,color,width=item
            out.append(f'<line x1="{x}" y1="{y}" x2="{xx}" y2="{yy}" stroke="{color}" stroke-width="{width}"/>')
        elif kind=='circle':
            _,x,y,r,color=item
            out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{color}"/>')
        elif kind=='outline_circle':
            _,x,y,r,color,width=item
            out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="none" stroke="{color}" stroke-width="{width}"/>')
        elif kind=='polygon':
            _,points,fill,color,width=item
            out.append('<polygon points="'+' '.join(f'{x},{y}' for x,y in points)+f'" fill="{fill or "none"}" stroke="{color}" stroke-width="{width}"/>')
    return ''.join(out)+'</svg>'
