import re, zlib, sys

fn = sys.argv[1] if len(sys.argv)>1 else 'notice.pdf'
data = open(fn,'rb').read()

objs = {}
for m in re.finditer(rb'(\d+)\s+(\d+)\s+obj(.*?)endobj', data, re.S):
    objs[int(m.group(1))] = m.group(3)

def decode_stream(body):
    sm = re.search(rb'stream\r?\n', body)
    if not sm: return None
    start = sm.end(); end = body.rfind(b'endstream')
    raw = body[start:end]; header = body[:sm.start()]
    if b'FlateDecode' in header:
        try: return zlib.decompress(raw)
        except Exception:
            try: return zlib.decompressobj().decompress(raw)
            except Exception: return None
    return raw

decoded = {n: d for n, d in ((n, decode_stream(b)) for n, b in objs.items()) if d is not None}

for num, body in list(objs.items()):
    if b'/ObjStm' in body and num in decoded:
        d = decoded[num]
        try:
            n = int(re.search(rb'/N\s+(\d+)', body).group(1))
            first = int(re.search(rb'/First\s+(\d+)', body).group(1))
        except Exception: continue
        head = d[:first].split()
        for i in range(n):
            onum = int(head[2*i]); off = int(head[2*i+1])
            nxt = int(head[2*i+3]) if 2*i+3 < len(head) else len(d)-first
            objs.setdefault(onum, d[first+off:first+nxt])

def parse_cmap(d):
    m = {}
    for blk in re.findall(rb'beginbfchar(.*?)endbfchar', d, re.S):
        for a,b in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            m[int(a,16)] = bytes.fromhex(b.decode()).decode('utf-16-be','ignore')
    for blk in re.findall(rb'beginbfrange(.*?)endbfrange', d, re.S):
        for a,b,c in re.findall(rb'<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>', blk):
            lo,hi,base = int(a,16), int(b,16), int(c,16)
            for k in range(lo, min(hi, lo+65535)+1):
                m[k] = chr(base + (k-lo))
    return m

_cc = {}
def cmap_for(n):
    if n not in _cc:
        d = decoded.get(n); _cc[n] = parse_cmap(d) if d else {}
    return _cc[n]

GLYPH = re.compile(r'^(?:uni([0-9A-Fa-f]{4})|g?(\d+))$')
def font_info(fobj):
    """return (map, nbytes)"""
    body = objs.get(fobj, b'')
    two = b'/Type0' in body or b'Identity-H' in body
    m = re.search(rb'/ToUnicode\s+(\d+)\s+\d+\s+R', body)
    cm = cmap_for(int(m.group(1))) if m else {}
    if not cm and not two:
        # Differences-based encoding
        enc = re.search(rb'/Encoding\s+(\d+)\s+\d+\s+R', body)
        encbody = objs.get(int(enc.group(1)), b'') if enc else body
        diffs = re.search(rb'/Differences\s*\[(.*?)\]', encbody, re.S)
        if diffs:
            cur = 0
            for tok in re.findall(rb'(\d+)|/([^\s/\]]+)', diffs.group(1)):
                if tok[0]:
                    cur = int(tok[0])
                else:
                    nm = tok[1].decode('latin1')
                    g = GLYPH.match(nm)
                    if g and g.group(1): cm[cur] = chr(int(g.group(1),16))
                    cur += 1
    return cm, (2 if two else 1)

def resolve_names(b):
    return {n.decode(): int(o) for n,o in re.findall(rb'/([A-Za-z0-9#_.\-]+)\s+(\d+)\s+\d+\s+R', b)}

page_objs = sorted([(n,b) for n,b in objs.items() if re.search(rb'/Type\s*/Page[^s]', b)])

def get_fonts(body):
    m = re.search(rb'/Resources\s+(\d+)\s+\d+\s+R', body)
    res = objs.get(int(m.group(1)), b'') if m else body
    fm = re.search(rb'/Font\s*<<(.*?)>>', res, re.S)
    if fm: return resolve_names(fm.group(1))
    fm = re.search(rb'/Font\s+(\d+)\s+\d+\s+R', res)
    if fm: return resolve_names(objs.get(int(fm.group(1)), b''))
    return {}

def contents(body):
    m = re.search(rb'/Contents\s+(\d+)\s+\d+\s+R', body)
    if m:
        n = int(m.group(1)); return decoded.get(n, objs.get(n, b''))
    m = re.search(rb'/Contents\s*\[(.*?)\]', body, re.S)
    out = b''
    if m:
        for num in re.findall(rb'(\d+)\s+\d+\s+R', m.group(1)):
            out += decoded.get(int(num), b'') + b'\n'
    return out

def unescape(s):
    s = re.sub(rb'\\([nrtbf()\\])', lambda m: {b'n':b'\n',b'r':b'\r',b't':b'\t',b'b':b'\b',b'f':b'\f'}.get(m.group(1), m.group(1)), s)
    s = re.sub(rb'\\([0-7]{1,3})', lambda m: bytes([int(m.group(1),8)&0xFF]), s)
    return s

TOKEN = re.compile(rb'/([A-Za-z0-9#_.\-]+)\s+[\d.]+\s+Tf|\[((?:[^\[\]\\]|\\.)*)\]\s*TJ|(<[0-9A-Fa-f\s]*>|\((?:\\.|[^\\()])*\))\s*(?:Tj|TJ|\'|")|(TD|Td|T\*)', re.S)
STR = re.compile(rb'<([0-9A-Fa-f\s]*)>|\((?:\\.|[^\\()])*\)', re.S)

def render(tok, cm, nb):
    if tok.startswith(b'<'):
        h = re.sub(rb'\s', b'', tok[1:-1]).decode()
        if len(h) % 2: h += '0'
        bb = bytes.fromhex(h)
    else:
        bb = unescape(tok[1:-1])
    out = []
    if nb == 2:
        for i in range(0, len(bb)-1, 2):
            out.append(cm.get(bb[i]<<8 | bb[i+1], ''))
    else:
        for c in bb:
            out.append(cm.get(c, chr(c) if 32 <= c < 127 else ''))
    return ''.join(out)

print(f"pages={len(page_objs)}", file=sys.stderr)
for pi,(pnum, body) in enumerate(page_objs, 1):
    finfo = {n: font_info(o) for n,o in get_fonts(body).items()}
    d = contents(body)
    cm, nb = {}, 2
    out = []
    for m in TOKEN.finditer(d):
        if m.group(1):
            cm, nb = finfo.get(m.group(1).decode(), ({}, 2))
        elif m.group(2) is not None:
            for sm in STR.finditer(m.group(2)):
                out.append(render(sm.group(0), cm, nb))
        elif m.group(3) is not None:
            out.append(render(m.group(3), cm, nb))
        else:
            out.append('\n')
    txt = re.sub(r'\n{3,}', '\n\n', ''.join(out))
    print(f"\n\n=============== PAGE {pi} ===============")
    print(txt)
