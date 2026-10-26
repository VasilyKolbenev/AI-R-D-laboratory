"""Pure blackboard skin for evidence diagrams, inspired by a supplied deck.

No source slide pixels/content are copied. Hand strokes are deterministic and
fixed across frames; graph structure, packet routes and claims are unchanged.
"""
from functools import lru_cache
import math
from pathlib import Path

PALETTE = {
    '#080d16':'#000000', '#0e1725':'#000000', '#121f30':'#000000',
    '#191c24':'#000000', '#101d2b':'#000000',
    '#edf5ff':'#f3f3f3', '#a4b4c8':'#aeaeae', '#294057':'#858585',
    '#5ae1ed':'#38d5f5', '#e795d2':'#ff83c2', '#edbd73':'#f5ec49',
    '#9cafc4':'#b9b9b9',
}


def selected(data):
    skin = data.get('visual_skin') or {}
    return isinstance(skin,dict) and skin.get('version') == 'skins-v1' and skin.get('id') == 'blackboard'


class Parts(list):
    def __init__(self, hand=False):
        super().__init__()
        self.hand = hand


@lru_cache(maxsize=48)
def font(size, bold=False):
    from .reader_infographic import _font
    if size < 23 or size in {24,28,36}:
        # Numeric charts retain the measured UI typography in both skins.
        # Their values/row labels must not acquire extra lines from handwriting.
        return _font(size,bold)
    from PIL import ImageFont
    paths = [Path('C:/Windows/Fonts')/('segoeprb.ttf' if bold else 'segoepr.ttf'),
             Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
    for path in paths:
        if path.is_file():
            return ImageFont.truetype(str(path),size)
    return _font(size,bold)


def family(size):
    return 'Segoe Print,Comic Sans MS,Segoe UI,sans-serif' if size >= 23 and size not in {24,28,36} else 'Segoe UI,Arial,sans-serif'


def color(value):
    return PALETTE.get(value,value)


@lru_cache(maxsize=2048)
def _stroke(x,y,xx,yy):
    distance = math.hypot(xx-x,yy-y)
    if distance < 25:
        return ((x,y),(xx,yy))
    count = max(3,math.ceil(distance/9))
    nx,ny = -(yy-y)/distance,(xx-x)/distance
    phase = (x*.13+y*.19+xx*.07+yy*.11)
    return tuple((x+(xx-x)*t+nx*wave,y+(yy-y)*t+ny*wave)
                 for t in (i/count for i in range(count+1))
                 for wave in [math.sin(t*math.pi)*math.sin(t*distance/15+phase)*1.15])


@lru_cache(maxsize=512)
def _outline(x,y,w,h,r):
    r = min(r,w/4,h/4)
    points=[]
    for cx,cy,start in ((x+w-r,y+r,-90),(x+w-r,y+h-r,0),
                         (x+r,y+h-r,90),(x+r,y+r,180)):
        corner=[(cx+r*math.cos(math.radians(start+i*15)),
                 cy+r*math.sin(math.radians(start+i*15))) for i in range(7)]
        if points:
            points.extend(_stroke(*points[-1],*corner[0])[1:])
        points.extend(corner)
    points.extend(_stroke(*points[-1],*points[0])[1:])
    return tuple(points)


def transform(parts):
    """Restyle primitives without mutating caller data or moving graph anchors."""
    result=[]
    for item in parts:
        kind=item[0]
        if kind=='line':
            _,x,y,xx,yy,c,width=item
            if c=='#102031':
                continue  # quiet graph paper belongs to the dashboard only
            if math.hypot(xx-x,yy-y)>=25:
                result.append(('polyline',_stroke(x,y,xx,yy),color(c),max(2,width)))
            else:
                result.append(('line',x,y,xx,yy,color(c),width))
        elif kind=='outline_rect':
            _,x,y,w,h,c,width,r=item
            result.append(('polyline',_outline(x,y,w,h,r),color(c),max(2,width)))
        elif kind=='rect':
            _,x,y,w,h,c,r=item
            result.append(('rect',x,y,w,h,color(c),r))
        elif kind=='text':
            _,x,y,value,size,c,bold=item
            result.append(('text',x,y,value,size,color(c),bold))
        elif kind=='circle':
            _,x,y,r,c=item
            result.append(('circle',x,y,r,color(c)))
        elif kind=='outline_circle':
            _,x,y,r,c,width=item
            result.append(('outline_circle',x,y,r,color(c),width))
        elif kind=='polygon':
            _,points,fill,c,width=item
            result.append(('polygon',points,color(fill),color(c),width))
        else:
            result.append(item)
    return result
