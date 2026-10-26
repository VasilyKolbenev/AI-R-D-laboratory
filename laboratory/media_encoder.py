"""Local native-resolution H.264 animation. Never calls a provider or the network."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'.lab-tools/media'
FPS=15
MAX_BYTES=8*1024*1024
MOTION_SECONDS=16
MECHANISM_CAPTION='Схема метода; собственных замеров нет. Анимация показывает порядок, не скорость.'

@lru_cache(maxsize=4)
def _verified(path,size,mtime,digest):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()==digest

def encoder_path():
    try:
        path=TOOLS/'ffmpeg.exe'
        manifest=json.loads((TOOLS/'encoder.json').read_text(encoding='utf-8-sig'))
        stat=path.stat()
        if _verified(str(path),stat.st_size,stat.st_mtime_ns,manifest['sha256']):return path
    except (OSError,ValueError,KeyError):pass
    return None

def available():
    return encoder_path() is not None

def _comparison_frame(data,item,progress):
    from PIL import Image,ImageDraw
    from .reader_infographic import layout,_raster,_font,W,PAPER,MUTED,_wrap
    single={**data,'comparisons':[item]}
    _,parts=layout(single,progress)
    # Stop before the application cards: the animated panel keeps one metric,
    # its definition, full conditions and provenance at their original size.
    lower=next(p[2] for p in parts if p[0]=='rect' and p[1]==40 and p[3]==490)
    urls=list(dict.fromkeys(e.get('source_url','') for e in item.get('evidence',[]) if e.get('source_url')))
    lines=['Данные авторов; собственных замеров нет.']
    for url in urls:lines.extend(_wrap(url,970,17))
    height=lower+28+len(lines)*24
    height+=height%2
    if height>1920:raise ValueError('Условия сравнения не помещаются в читаемый анимационный кадр.')
    picture=Image.new('RGB',(W,height),PAPER)
    picture.paste(_raster(single,progress).crop((0,0,W,lower)),(0,0))
    draw=ImageDraw.Draw(picture)
    for index,line in enumerate(lines):draw.text((54,lower+12+index*24),line,font=_font(17),fill=MUTED,anchor='lt')
    return picture


def _mechanism_layout(data, active):
    from .adaptive_visual import profile_mode,layout as adaptive_layout
    if profile_mode(data)=='mechanism':
        if active not in range(3):raise ValueError('Недопустимый шаг механизма.')
        return adaptive_layout(data,active,animation=True)
    from .reader_infographic import _mechanism_steps,_text,W,PAPER,INK,MUTED,GREEN,MINT,WHITE,LINE,NO_COMPARISON
    from .presentation import _public_url
    steps=_mechanism_steps(data)
    if len(steps)!=3 or any(not step for step in steps):
        raise ValueError('Для пошаговой анимации нужны ровно три полных шага механизма.')
    if active not in range(3):raise ValueError('Недопустимый шаг механизма.')
    parts=[('text',54,30,'VV FRONTIER · МЕХАНИЗМ',17,GREEN,True)]
    y=_text(parts,data.get('title') or 'Механизм по шагам',54,78,972,42,INK,True,gap=54)+24
    y=_text(parts,'Механизм по шагам',54,y,972,27,INK,True,gap=36)+14
    y=_text(parts,NO_COMPARISON,54,y,972,21,MUTED,gap=28)+26
    for index,step in enumerate(steps):
        top=y
        card_index=len(parts)
        label='ШАГ '+str(index+1)+(' · СЕЙЧАС В СХЕМЕ' if index==active else '')
        parts.append(('text',80,top+22,label,18,GREEN if index==active else MUTED,True))
        end=_text(parts,step,80,top+58,920,27,INK,False,gap=36)
        height=end-top+24
        # Insert the card before its text; highlight is explanatory, not a new result.
        parts.insert(card_index,('rect',40,top,1000,height,MINT if index==active else WHITE,24))
        parts.insert(card_index+1,('rect',52,top+18,6,height-36,GREEN if index==active else LINE,3))
        y=top+height+18
    y=_text(parts,MECHANISM_CAPTION,54,y+4,972,21,MUTED,gap=28)+12
    urls=[]
    for source in (data.get('publication_sources') or data.get('sources') or data.get('evidence') or [])[:4]:
        if not isinstance(source,dict):continue
        url=_public_url(source.get('url') or source.get('source_url',''))
        if url and url not in urls:urls.append(url)
    for url in urls:y=_text(parts,url,54,y+5,972,18,MUTED,gap=25)
    y+=28
    height=int(y)+(int(y)%2)
    if height>1920:raise ValueError('Три полных шага и источник не помещаются в читаемый кадр.')
    parts.insert(0,('rect',0,0,W,height,PAPER,0))
    return height,parts


def _mechanism_frame(data, active):
    from .reader_infographic import _raster_parts
    height,parts=_mechanism_layout(data,active)
    return _raster_parts(height,parts)

def _frames(data):
    from PIL import Image
    from .adaptive_visual import profile_mode,phases,frame as adaptive_frame
    if isinstance(data.get('motion_story'), dict) and data['motion_story'].get('version') == 'dataflow-v1':
        from .motion_dashboard import frame
        for index in range(FPS*MOTION_SECONDS):
            yield frame(data,index/(FPS*MOTION_SECONDS))
    elif profile_mode(data) in {'mechanism','infrastructure','applicability'}:
        # Native reading panels: retain all text and sources in every phase.
        # A step/layer/paragraph highlight conveys focus, never measured speed.
        for active in phases(data):
            picture=adaptive_frame(data,active)
            for _ in range(FPS*3):yield picture
    elif data.get('comparisons'):
        from .reader_infographic import _comparisons
        items=_comparisons(data)
        if not items:return
        # Pad all panels to one canvas; never resize text or crop conditions.
        sizes=[_comparison_frame(data,item,1).size for item in items]
        width=max(s[0] for s in sizes);height=max(s[1] for s in sizes)
        for item in items:
            for index in range(FPS*5):
                progress=1-(1-min(1,index/(FPS*1.1)))**3
                picture=_comparison_frame(data,item,progress)
                frame=Image.new('RGB',(width,height),'#f3f2ed');frame.paste(picture,(0,0))
                yield frame
    elif (data.get('visual') or {}).get('kind')=='process_flow':
        for active in range(3):
            picture=_mechanism_frame(data,active)
            for _ in range(FPS*3):yield picture

@lru_cache(maxsize=3)
def _render(serialized,binary):
    data=json.loads(serialized)
    frames=iter(_frames(data))
    try:first=next(frames)
    except StopIteration:return None
    with tempfile.TemporaryDirectory(prefix='lab-animation-') as directory:
        target=Path(directory)/'animation.mp4'
        error_path=Path(directory)/'encoder.log'
        command=[binary,'-hide_banner','-loglevel','error','-y','-f','rawvideo','-vcodec','rawvideo',
                 '-pix_fmt','rgb24','-s',f'{first.width}x{first.height}','-r',str(FPS),'-i','pipe:0',
                 '-an','-c:v','libx264','-preset','veryfast','-crf','14','-pix_fmt','yuv420p',
                 '-movflags','+faststart','-threads','2',str(target)]
        with error_path.open('wb') as error:
            process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=error,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                process.stdin.write(first.tobytes())
                for frame in frames:
                    if frame.size!=first.size:raise ValueError('Размер анимационного кадра изменился.')
                    process.stdin.write(frame.tobytes())
                process.stdin.close()
                if process.wait(timeout=45)!=0:return None
            except Exception:
                if process.poll() is None:process.kill()
                process.wait(timeout=5)
                return None
        size=target.stat().st_size
        return target.read_bytes() if 0<size<=MAX_BYTES else None

def render_mp4(data):
    binary=encoder_path()
    if binary is None:return None
    try:
        return _render(json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False),str(binary))
    except (ImportError,OSError,ValueError,TypeError):
        return None
