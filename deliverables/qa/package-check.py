from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
import json
import sys
import jsonschema
import hashlib

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {'node_modules', '__pycache__', 'test-results', 'playwright-report'}

def project_files(pattern):
    return [path for path in ROOT.rglob(pattern) if not EXCLUDED_DIRS.intersection(path.relative_to(ROOT).parts)]

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids=[]
        self.links=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if 'id' in attrs:
            self.ids.append(attrs['id'])
        if tag=='a' and 'href' in attrs:
            self.links.append(attrs['href'])
        if tag in ('img','script') and attrs.get('src'):
            self.links.append(attrs['src'])
        if tag=='link' and attrs.get('href'):
            self.links.append(attrs['href'])

pages={}
errors=[]
checks=0
for path in project_files('*.html'):
    parser=Page()
    parser.feed(path.read_text(encoding='utf-8'))
    pages[path.resolve()]=parser
    if len(parser.ids)!=len(set(parser.ids)):
        errors.append(f'duplicate IDs: {path.relative_to(ROOT)}')
for path,parser in pages.items():
    for link in parser.links:
        parsed=urlsplit(link)
        if parsed.scheme or parsed.netloc:
            continue
        target=(path.parent/unquote(parsed.path)).resolve() if parsed.path else path
        checks+=1
        if not target.exists() and target != ROOT/'qa/package-results.json':
            errors.append(f'missing target: {path.relative_to(ROOT)} -> {link}')
        elif parsed.fragment and target in pages and unquote(parsed.fragment) not in pages[target].ids:
            errors.append(f'missing anchor: {path.relative_to(ROOT)} -> {link}')
schema=json.loads((ROOT/'architecture/experiment-plan.schema.json').read_text(encoding='utf-8'))
example=json.loads((ROOT/'architecture/example-plan.json').read_text(encoding='utf-8'))
Validator=jsonschema.validators.validator_for(schema)
Validator.check_schema(schema)
validation_errors=list(Validator(schema).iter_errors(example))
errors.extend('schema example: '+e.message for e in validation_errors)
json_files=project_files('*.json')
for path in json_files:
    json.loads(path.read_text(encoding='utf-8'))
result={'html_pages':len(pages),'local_references_checked':checks,'json_files_parsed':len(json_files),'plan_schema_and_example_valid':not validation_errors,'errors':errors}
v2_path=ROOT/'qa/constellation-v2-results.json'
if v2_path.exists():
    v2=json.loads(v2_path.read_text(encoding='utf-8'))
    current_hash=hashlib.sha256((ROOT/'ui/03-constellation.html').read_bytes()).hexdigest()
    revision_matches=v2.get('appRevisionSha256')==current_hash
    passed=bool(v2.get('results')) and all(r['status']=='pass' for r in v2['results'])
    result['constellation_v2']={'tested_revision_matches':revision_matches,'all_checks_passed':passed}
    if not revision_matches: errors.append('Constellation v2 changed after its last browser test')
    if not passed: errors.append('Constellation v2 checks are incomplete or failing')
alpha_qa_path=ROOT/'qa/alpha-plan-results.json'
if alpha_qa_path.exists():
    alpha_qa=json.loads(alpha_qa_path.read_text(encoding='utf-8'))
    revisions_match=all(hashlib.sha256((ROOT/'docs'/f'{name}.html').read_bytes()).hexdigest()==digest for name,digest in alpha_qa['revisions'].items())
    passed=bool(alpha_qa.get('results')) and all(row['status']=='pass' for row in alpha_qa['results'])
    result['alpha_documents']={'tested_revisions_match':revisions_match,'all_checks_passed':passed}
    if not revisions_match: errors.append('Alpha documents changed after their browser test')
    if not passed: errors.append('Alpha document checks are incomplete or failing')
(ROOT/'qa/package-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(bool(errors))
