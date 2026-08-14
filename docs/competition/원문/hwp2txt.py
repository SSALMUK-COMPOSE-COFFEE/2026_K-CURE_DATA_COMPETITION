import struct, zlib, sys

fn = sys.argv[1] if len(sys.argv)>1 else 'plan.hwp'
d = open(fn,'rb').read()

# --- minimal CFB (OLE2) parser ---
assert d[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
sect_shift = struct.unpack_from('<H', d, 0x1e)[0]
mini_shift = struct.unpack_from('<H', d, 0x20)[0]
SS = 1 << sect_shift
MS = 1 << mini_shift
num_fat = struct.unpack_from('<I', d, 0x2c)[0]
dir_start = struct.unpack_from('<I', d, 0x30)[0]
mini_start = struct.unpack_from('<I', d, 0x3c)[0]
difat_start = struct.unpack_from('<I', d, 0x44)[0]
num_difat = struct.unpack_from('<I', d, 0x48)[0]

def sect_off(s): return (s+1) * SS

difat = list(struct.unpack_from('<109I', d, 0x4c))
s = difat_start
while num_difat > 0 and s != 0xFFFFFFFE and s < 0xFFFFFFF0:
    blk = struct.unpack_from('<%dI' % (SS//4), d, sect_off(s))
    difat += list(blk[:-1]); s = blk[-1]; num_difat -= 1

fat = []
for fs in difat[:num_fat]:
    if fs >= 0xFFFFFFF0: continue
    fat += list(struct.unpack_from('<%dI' % (SS//4), d, sect_off(fs)))

def chain(start):
    out=[]; s=start
    while s < 0xFFFFFFF0 and len(out) < 200000:
        out.append(s); s = fat[s] if s < len(fat) else 0xFFFFFFFE
    return out

def read_chain(start, size=None):
    b = b''.join(d[sect_off(s):sect_off(s)+SS] for s in chain(start))
    return b[:size] if size else b

dirdata = read_chain(dir_start)
entries = []
for i in range(len(dirdata)//128):
    e = dirdata[i*128:(i+1)*128]
    nlen = struct.unpack_from('<H', e, 0x40)[0]
    name = e[:max(nlen-2,0)].decode('utf-16-le', 'ignore')
    typ = e[0x42]
    start = struct.unpack_from('<I', e, 0x74)[0]
    size = struct.unpack_from('<Q', e, 0x78)[0]
    entries.append((name, typ, start, size))

root = next(e for e in entries if e[1]==5)
ministream = read_chain(root[2], root[3]) if root[2] < 0xFFFFFFF0 else b''
minifat_entry = next((e for e in entries), None)
minifat = list(struct.unpack_from('<%dI' % (len(read_chain(mini_start))//4), read_chain(mini_start))) if mini_start < 0xFFFFFFF0 else []

def read_mini(start, size):
    out=b''; s=start
    while s < 0xFFFFFFF0 and len(out) < size:
        out += ministream[s*MS:(s+1)*MS]
        s = minifat[s] if s < len(minifat) else 0xFFFFFFFE
    return out[:size]

def read_entry(name):
    for n,t,st,sz in entries:
        if n == name and t == 2:
            return read_mini(st, sz) if sz < 4096 else read_chain(st, sz)
    return None

print("ENTRIES:", [(n,t,sz) for n,t,st,sz in entries if t==2], file=sys.stderr)

hdr = read_entry('FileHeader')
compressed = bool(hdr[36] & 1) if hdr else True
print("compressed:", compressed, file=sys.stderr)

def inflate(b):
    try: return zlib.decompress(b, -15)
    except Exception:
        try: return zlib.decompress(b)
        except Exception: return b

# BodyText sections
secs = sorted([n for n,t,st,sz in entries if t==2 and n.startswith('Section')])
print("sections:", secs, file=sys.stderr)

def parse_records(buf):
    i = 0
    while i + 4 <= len(buf):
        h = struct.unpack_from('<I', buf, i)[0]
        tag = h & 0x3FF
        level = (h >> 10) & 0x3FF
        size = (h >> 20) & 0xFFF
        i += 4
        if size == 0xFFF:
            size = struct.unpack_from('<I', buf, i)[0]; i += 4
        yield tag, level, buf[i:i+size]
        i += size

CTRL_INLINE = set([4,5,6,7,8,9,19,20,21,22,23])
for sname in secs:
    raw = read_entry(sname)
    buf = inflate(raw) if compressed else raw
    out = []
    for tag, level, payload in parse_records(buf):
        if tag == 67:  # HWPTAG_PARA_TEXT
            t = ''
            i = 0
            while i + 1 < len(payload):
                c = struct.unpack_from('<H', payload, i)[0]
                if c in (0,10,13):
                    t += '\n'; i += 2
                elif c < 32:
                    if c in CTRL_INLINE: i += 2
                    else: i += 16
                else:
                    t += chr(c); i += 2
            out.append(t)
    print(f"\n\n========== {sname} ==========")
    print('\n'.join(x for x in out))
