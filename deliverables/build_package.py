from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'rnd-laboratory-package.zip'
excluded={'architecture.html.txt','implementation-plan.html.txt','static-review.txt','constell-v2-first-layout.png'}
files=[p for p in ROOT.rglob('*') if p.is_file() and p.suffix!='.zip' and p.name not in excluded and not {'__pycache__','node_modules','test-results','playwright-report'}.intersection(p.parts)]
with ZipFile(OUT,'w',compression=ZIP_DEFLATED,compresslevel=9) as archive:
    for path in sorted(files):
        rel=path.relative_to(ROOT)
        name='rnd-laboratory/'+rel.as_posix()
        if rel.as_posix()=='index.html':
            source=path.read_text(encoding='utf-8')
            source=source.replace('<a class="button" href="rnd-laboratory-package.zip" download>Скачать весь пакет ↓</a>', '<a class="button" href="README.txt">Как открыть пакет ↗</a>')
            archive.writestr(name,source)
        else:
            archive.write(path,name)
with ZipFile(OUT) as archive:
    assert archive.testzip() is None
    print(f'{len(archive.namelist())} files, {OUT.stat().st_size:,} bytes, archive integrity OK')
