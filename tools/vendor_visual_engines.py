"""Vendor fixed upstream browser bundles; never run npm/install scripts.

Default is verification only. --fetch explicitly obtains fixed tarballs from
the npm registry, verifies their published SHA-512, then copies allowlisted files.
"""
from pathlib import Path
from urllib.request import urlopen
import argparse
import base64
import hashlib
import io
import json
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'laboratory/web/vendor'
PACKAGES = (
    {'name': '@antv/infographic', 'version': '0.2.20', 'slug': 'infographic',
     'integrity': 'sha512-XC1YXpQu6lJ3ZODUS7qBtai5cA8rUrzpegiOHjeCLElzJ6fki+N3yeosIKoYCUNcRCCUovgeSyMMIzzf2ndN2w==',
     'member': 'package/dist/infographic.min.js', 'file': 'antv-infographic.min.js',
     'global': 'AntVInfographic', 'repository': 'https://github.com/antvis/Infographic'},
    {'name': '@antv/g2', 'version': '5.4.8', 'slug': 'g2',
     'integrity': 'sha512-IvgIpwmT4M5/QAd3Mn2WiHIDeBqFJ4WA2gcZhRRSZuZ2KmgCqZWZwwIT0hc+kIGxwYeDoCQqf//t6FMVu3ryBg==',
     'member': 'package/dist/g2.min.js', 'file': 'antv-g2.min.js',
     'global': 'G2', 'repository': 'https://github.com/antvis/G2'},
)


def checked_payload(package, cache):
    name = package['slug'] + '-' + package['version'] + '.tgz'
    url = f'https://registry.npmjs.org/@antv/{package["slug"]}/-/{name}'
    cached = cache / name if cache else None
    if cached and cached.is_file():
        payload = cached.read_bytes()
    else:
        with urlopen(url, timeout=45) as response:
            if response.url != url:
                raise ValueError('Unexpected registry redirect')
            payload = response.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError('Package exceeds bound')
    expected = package['integrity'].removeprefix('sha512-')
    if base64.b64encode(hashlib.sha512(payload).digest()).decode() != expected:
        raise ValueError('Tarball integrity mismatch')
    return payload, url


def vendor(cache=None):
    if not DEST.resolve().is_relative_to(ROOT.resolve()):
        raise ValueError('Invalid vendor target')
    DEST.mkdir(parents=True, exist_ok=True)
    packages = []
    for package in PACKAGES:
        payload, url = checked_payload(package, cache)
        files = []
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
            for member, filename in ((package['member'], package['file']),
                                     ('package/LICENSE', package['slug'] + '.LICENSE.txt')):
                info = archive.getmember(member)
                if not info.isfile() or info.size > 5 * 1024 * 1024:
                    raise ValueError('Unexpected distribution file')
                content = archive.extractfile(info).read()
                target = DEST / filename
                if target.is_symlink():
                    raise ValueError('Symlink vendor target')
                target.write_bytes(content)
                files.append({'file': filename, 'source_member': member, 'bytes': len(content),
                              'sha256': hashlib.sha256(content).hexdigest()})
        packages.append({**package, 'tarball': url, 'license': 'MIT', 'files': files})
    (DEST / 'manifest.json').write_text(json.dumps({'format': 'visual-vendor-v1',
        'packages': packages}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return verify()


def verify():
    manifest = json.loads((DEST / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'visual-vendor-v1' or len(manifest.get('packages', [])) != 2:
        raise ValueError('Invalid vendor manifest')
    for expected, package in zip(PACKAGES, manifest['packages']):
        for key, value in expected.items():
            if package.get(key) != value:
                raise ValueError('Unexpected vendor identity')
        names = [expected['file'], expected['slug'] + '.LICENSE.txt']
        if [item['file'] for item in package['files']] != names:
            raise ValueError('Unexpected vendor files')
        for item in package['files']:
            content = (DEST / item['file']).read_bytes()
            if len(content) != item['bytes'] or hashlib.sha256(content).hexdigest() != item['sha256']:
                raise ValueError('Vendor bytes changed')
    return {'verified': True, 'packages': [{'name': p['name'], 'version': p['version'],
             'bytes': p['files'][0]['bytes']} for p in manifest['packages']]}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch', action='store_true')
    parser.add_argument('--cache', type=Path)
    args = parser.parse_args()
    print(json.dumps(vendor(args.cache) if args.fetch else verify(), ensure_ascii=False))
