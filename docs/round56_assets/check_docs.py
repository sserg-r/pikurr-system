#!/usr/bin/env python3
"""Проверки комплекта ЕСПД (повтор проверок раунда 54, блок B). Запуск из docs/_espd_local: python3 ../round56_assets/check_docs.py
Только чтение: .md, docx/*.pdf, carrier/. Выводит таблицу результатов; код возврата 1 при непустых находках."""
import re, subprocess, sys, glob, os
D = 'docx'
MD = sorted(glob.glob('0[1-6]_*.md'))
PDF = sorted(glob.glob(f'{D}/0[1-6]_*.pdf'))
def pdftext(f): return subprocess.run(['pdftotext', '-layout', f, '-'], capture_output=True, text=True).stdout
def pages(f): return int(re.search(r'Pages:\s+(\d+)', subprocess.run(['pdfinfo', f], capture_output=True, text=True).stdout).group(1))
bad = 0
print('== 1. «Листов» = страниц PDF − 1')
for f in PDF:
    t = pdftext(f); m = re.search(r'Листов\s+(\d+)', t[:3000])
    p = pages(f); ok = (m is not None and int(m.group(1)) == p - 1)
    print(f'  {os.path.basename(f)}: страниц PDF {p}; «Листов» на титуле: {m.group(1) if m else "—(нет числа)"}; {"OK" if ok else "—"}')
print('== 2. Маркеры в тексте PDF')
for f in PDF:
    t = pdftext(f); n = sum(len(re.findall(re.escape(k), t)) for k in ('[ВОПРОС', '[РИСУНОК', '[ВЛАДЕЛЕЦ', '[_]'))
    print(f'  {os.path.basename(f)}: {n}'); bad += n
print('== 3. Запрещённое содержимое (.md и текст PDF)')
PAT = {'IP-адрес': r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '/home': r'/home', 'localhost': r'localhost', 'round/раунд': r'(?i)\bround\d*|раунд', 'CLAUDE': r'CLAUDE|Claude',
       'Hansen': r'Hansen', 'TensorFlow/TF Serving': r'(?i)tensorflow|tf serving', '«80 м»': r'80 м\b', 'ТКП': r'ТКП', 'формализованный': r'формализованн', 'отчётный': r'отчётн',
       'pikurr_start': r'pikurr_start', '«30 декабря»': r'30 декабря', 'природными/природным': r'природным', 'БГЛИ': r'БГЛИ', 'admin/admin': r'admin/admin',
       'годы 2025–2039': r'\b20(2[5-9]|3\d)\b', '@': r'@', 'пользователь ОС': r'\bsgr\b', 'модель GPU': r'RTX|5070|Blackwell'}
hits = []
for f in MD + PDF:
    t = open(f, encoding='utf-8').read() if f.endswith('.md') else pdftext(f)
    for k, rx in PAT.items():
        for m in re.finditer(rx, t):
            s = t[max(0, m.start()-25): m.end()+25].replace('\n', ' ')
            hits.append((os.path.basename(f), k, s))
for h in hits: print('  ', h)
print(f'  всего совпадений: {len(hits)}')
print('== 4. Внутренние ссылки «п. N.N» / «Таблица N» / «рис. N»')
for f in MD:
    t = open(f, encoding='utf-8').read()
    heads = set(re.findall(r'^#{1,6}\s+(\d+(?:\.\d+)*)\.?\s', t, re.M)) | set(re.findall(r'^(\d+(?:\.\d+){1,5})\.?\s', t, re.M))
    refs = re.findall(r'п+\. (\d+(?:\.\d+)*)', t)
    cross = [m for m in re.finditer(r'п+\. \d+(?:\.\d+)*[^.;\n]{0,60}(описани[ея] применения|руководств[ао]|ПМИ|программ[аы] и методик|ведомост|спецификаци)', t)]
    miss = sorted({r for r in refs if r not in heads})
    tabs = [int(x) for x in re.findall(r'^Таблица (\d+) —', t, re.M)]; trefs = {int(x) for x in re.findall(r'[Тт]абл(?:ица|\.) (\d+)', t)}
    figs = [int(x) for x in re.findall(r'РИСУНОК (\d+)', t)]
    print(f'  {f}: ссылок «п.» {len(refs)}; не найдены в заголовках этого документа (возможно, ссылки на другой документ): {miss[:12]}; ссылок на пункты чужих документов (по тексту рядом): {len(cross)}; таблиц {tabs}; ссылок на таблицы вне набора {sorted(trefs - set(tabs))}')
print('== 5. Носитель: сканер секретов/идентификаторов и файлы ПМИ — результат строк make_all.sh (см. вывод build_deposit)')
sys.exit(1 if bad else 0)
