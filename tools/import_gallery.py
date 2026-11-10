#!/usr/bin/env python3
"""Разовый импорт: читает галерею и контакты из index.html и пишет data/portfolio.json."""
import re, json, subprocess, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
s = open(os.path.join(ROOT, 'index.html'), encoding='utf-8', newline='').read()

def dim(src):
    p = os.path.join(ROOT, src.lstrip('/'))
    o = subprocess.run(['sips', '-g', 'pixelWidth', '-g', 'pixelHeight', p], capture_output=True, text=True).stdout
    return int(re.search(r'pixelWidth: (\d+)', o).group(1)), int(re.search(r'pixelHeight: (\d+)', o).group(1))

A = re.compile(r'<a id="([^"]+)" rel="fb_group" href="([^"]+)"><img class="image"(?: width="[^"]*")? src="([^"]+)"></a>')
def img(m, seen):
    id_, href, src = m.groups()
    assert href == src, (href, src)
    w, h = dim(src)
    d = {'src': src.lstrip('/'), 'w': w, 'h': h}
    if id_ not in seen:  # дубли id (palto, loive) оставляем только у первого
        d['id'] = id_; seen.add(id_)
    return d

body = s[s.index('<div id="first"'):s.index('<div id="other"')]
body = re.sub(r'<!--.*?-->', '', body, flags=re.S)  # закомментированные ряды не берём
rows = []; seen = set()
for r in re.split(r'<div (?:id="first" )?class="container">', body)[1:]:
    items = []
    pos = 0
    tok = re.compile(r'<div id="[^"]+" class="vcontainer">(.*?)</div>|' + A.pattern, re.S)
    for m in tok.finditer(r):
        if m.group(1) is not None:
            items.append({'stack': [img(x, seen) for x in A.finditer(m.group(1))]})
        else:
            items.append(img(re.match(A, m.group(0)), seen))
    rows.append(items)

contacts = []
blk = re.search(r'<div id="contacts">(.*?)</div>', s, re.S).group(1)
for m in re.finditer(r'(?:<a href="([^"]+)">\s*)?<p class="contacts">([^<]*)</p>', blk):
    contacts.append({'text': m.group(2), 'href': m.group(1) or ''})

out = {'contacts': contacts, 'rows': rows}
os.makedirs(os.path.join(ROOT, 'data'), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, 'data/portfolio.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print('rows', len(rows), 'images', sum(len(i['stack']) if 'stack' in i else 1 for r in rows for i in r), 'contacts', len(contacts))
