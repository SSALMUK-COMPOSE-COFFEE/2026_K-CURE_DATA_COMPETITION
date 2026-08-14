import zipfile, re, sys, xml.etree.ElementTree as ET

fn = sys.argv[1]
z = zipfile.ZipFile(fn)
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RNS = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'

shared = []
if 'xl/sharedStrings.xml' in z.namelist():
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    for si in root:
        shared.append(''.join(t.text or '' for t in si.iter(NS+'t')))

wb = ET.fromstring(z.read('xl/workbook.xml'))
rels = {}
r = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
for e in r:
    rels[e.get('Id')] = e.get('Target')

sheets = []
for sh in wb.iter(NS+'sheet'):
    tgt = rels.get(sh.get(RNS+'id'), '')
    if tgt and not tgt.startswith('xl/'): tgt = 'xl/' + tgt.lstrip('/')
    sheets.append((sh.get('name'), tgt))

def colnum(ref):
    m = re.match(r'([A-Z]+)', ref)
    n = 0
    for c in m.group(1): n = n*26 + (ord(c)-64)
    return n-1

for name, path in sheets:
    if path not in z.namelist(): continue
    print(f"\n\n########## SHEET: {name} ##########")
    root = ET.fromstring(z.read(path))
    for row in root.iter(NS+'row'):
        cells = {}
        auto = 0
        for c in row.iter(NS+'c'):
            t = c.get('t'); v = c.find(NS+'v'); isel = c.find(NS+'is')
            if t == 's' and v is not None:
                val = shared[int(v.text)]
            elif t == 'inlineStr' and isel is not None:
                val = ''.join(x.text or '' for x in isel.iter(NS+'t'))
            elif v is not None:
                val = v.text
            else:
                continue
            val = (val or '').replace('\n',' ').strip()
            ref = c.get('ref') or c.get('r')
            idx = colnum(ref) if ref else auto
            auto = idx + 1
            if val: cells[idx] = val
        if not cells: continue
        mx = max(cells)
        print(' | '.join(cells.get(i,'') for i in range(mx+1)))
