#!/usr/bin/env python3
"""Собирает галерею и контакты в index.html из data/portfolio.json.

Правило: ряд = 1..3 блока одинаковой высоты на всю ширину.
  блок-картинка: ширина ряда ~ w/h
  блок-стопка (2-3 картинки друг над другом): пропорция 1/сумма(h/w),
  высота картинки в стопке ~ h/w.
Доли считаются в процентах с двумя знаками.
"""
import re, json, os, html
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NL = '\r\n'

def pct(x): return ('%.2f' % x).rstrip('0').rstrip('.')

def img_html(it, style, ind):
    if it['src'].startswith('videos/'):   # зацикленное видео без звука, не входит в лайтбокс
        return '%s<div class="vwrap" style="%s"><video src="/%s" autoplay loop muted playsinline preload="auto" disablepictureinpicture></video></div>' % (ind, style, it['src'])
    if it['src'].endswith('-anim.svg'):   # векторная анимация от прокрутки: svg вставляется в страницу, не входит в лайтбокс
        svg = open(os.path.join(ROOT, it['src']), encoding='utf-8').read().strip()
        return '%s<div class="vwrap anim" style="%s">%s</div>' % (ind, style, svg.replace('\n', ''))
    idattr = ' id="%s"' % it['id'] if it.get('id') else ''
    return '%s<a%s rel="fb_group" href="/%s" style="%s"><img class="image" src="/%s"></a>' % (ind, idattr, it['src'], style, it['src'])

def aspect(it):
    if 'stack' in it:
        return 1.0 / sum(i['h'] / i['w'] for i in it['stack'])
    return it['w'] / it['h']

def row_html(items, first):
    tot = sum(aspect(i) for i in items)
    out = ['  <div%s class="container">' % (' id="first"' if first else '')]
    for it in items:
        w = 100.0 if len(items) == 1 else aspect(it) / tot * 100
        ws = 'width:%s%%;max-width:%s%%' % (pct(w), pct(w))
        if 'stack' in it:
            st = it['stack']; t = sum(i['h'] / i['w'] for i in st)
            out.append('    <div class="vcontainer" style="%s">' % ws)
            for i in st:
                h = pct(i['h'] / i['w'] / t * 100)
                out.append(img_html(i, 'height:%s%%;max-height:%s%%' % (h, h), '      '))
            out.append('    </div>')
        else:
            out.append(img_html(it, ws, '    '))
    out.append('  </div>')
    return out

def contacts_html(cs):
    out = []
    for c in cs:
        p = '<p class="contacts">%s</p>' % html.escape(c['text'], quote=False)
        if c.get('href'):
            out += ['      <a href="%s">' % html.escape(c['href']), '        ' + p, '      </a>']
        else:
            out.append('      ' + p)
    return out

def replace_between(s, start, end, lines, fallback):
    block = start + NL + NL.join(lines) + NL + '  ' + end
    if start in s:
        return re.sub(re.escape(start) + r'.*?' + re.escape(end), lambda m: block, s, flags=re.S)
    return fallback(s, block)

def main():
    d = json.load(open(os.path.join(ROOT, 'data/portfolio.json'), encoding='utf-8'))
    path = os.path.join(ROOT, 'index.html')
    s = open(path, encoding='utf-8', newline='').read()
    rows = []
    for n, r in enumerate(d['rows']): rows += row_html(r, n == 0)
    def fb_gallery(s, block):
        a = s.index('<div id="first"'); b = s.index('<div id="other"')
        return s[:a] + block + NL + '  ' + s[b:]
    s = replace_between(s, '<!-- gallery:start -->', '<!-- gallery:end -->', rows, fb_gallery)
    def fb_contacts(s, block):
        m = re.search(r'(<div id="contacts">)(.*?)(\r?\n    </div>\r?\n    <div id="logoblock">)', s, re.S)
        return s[:m.start(2)] + NL + '      ' + block + s[m.start(3):]
    s = replace_between(s, '<!-- contacts:start -->', '<!-- contacts:end -->', contacts_html(d['contacts']), fb_contacts)
    s = re.sub(r'<div id="contacts"[^>]*>', '<div id="contacts" style="--n:%d">' % len(d['contacts']), s, count=1)   # число строк для центрирования группы
    open(path, 'w', encoding='utf-8', newline='').write(s)
    print('built', len(d['rows']), 'rows')

if __name__ == '__main__':
    main()
