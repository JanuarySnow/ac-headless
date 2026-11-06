import socket
import struct

COOKIE = b"MIT-MAGIC-COOKIE-1"


class ScreenError(Exception):
    pass


def _pad(b):
    return b + b"\0" * (-len(b) % 4)


def _plen(n):
    return n + (-n % 4)


def read_cookie(path):
    with open(path, "rb") as fh:
        data = fh.read()
    pos = 0
    while pos + 2 <= len(data):
        pos += 2
        fields = []
        for _ in range(4):
            if pos + 2 > len(data):
                return None
            n = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            fields.append(data[pos:pos + n])
            pos += n
        if fields[2] == COOKIE:
            return fields[3]
    return None


def _recv(s, n):
    buf = bytearray()
    while len(buf) < n:
        chunk = s.recv(min(n - len(buf), 1 << 20))
        if not chunk:
            raise ScreenError("the X server closed the connection")
        buf += chunk
    return bytes(buf)


class Image:
    def __init__(self, width, height, data):
        self.width = width
        self.height = height
        self.data = data

    def rgb(self, x, y):
        i = (y * self.width + x) * 4
        return self.data[i + 2], self.data[i + 1], self.data[i]


def parse_setup(extra):
    vlen = struct.unpack("<H", extra[16:18])[0]
    nfmt = extra[21]
    if extra[22] != 0:
        raise ScreenError("the X server does not use LSB first images")
    fmt_at = 32 + _plen(vlen)
    bpp = {}
    for i in range(nfmt):
        f = extra[fmt_at + 8 * i:fmt_at + 8 * i + 8]
        bpp[f[0]] = f[1]
    scr = fmt_at + 8 * nfmt
    root = struct.unpack("<I", extra[scr:scr + 4])[0]
    width, height = struct.unpack("<HH", extra[scr + 20:scr + 24])
    depth = extra[scr + 38]
    return root, width, height, depth, bpp.get(depth)


def capture(display, xauth=None, timeout=15):
    num = int(display.lstrip(":").split(".")[0])
    cookie = read_cookie(xauth) if xauth else None
    name = COOKIE if cookie else b""
    cookie = cookie or b""
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect("/tmp/.X11-unix/X%d" % num)
        s.sendall(struct.pack("<BxHHHH2x", 0x6C, 11, 0, len(name), len(cookie))
                  + _pad(name) + _pad(cookie))
        head = _recv(s, 8)
        extra = _recv(s, struct.unpack("<H", head[6:8])[0] * 4)
        if head[0] != 1:
            raise ScreenError("the X server refused the connection")
        root, width, height, depth, bpp = parse_setup(extra)
        if depth != 24 or bpp != 32:
            raise ScreenError("unsupported display depth %s" % depth)
        s.sendall(struct.pack("<BBHIhhHHI", 73, 2, 5, root, 0, 0, width, height, 0xFFFFFFFF))
        rep = _recv(s, 32)
        if rep[0] != 1:
            raise ScreenError("the X server could not copy the screen")
        data = _recv(s, struct.unpack("<I", rep[4:8])[0] * 4)
    except OSError as e:
        raise ScreenError("could not read display %s: %s" % (display, e))
    finally:
        s.close()
    return Image(width, height, data)


def is_red(r, g, b):
    return r >= 150 and r - g >= 60 and r - b >= 60


def is_white(r, g, b):
    return r >= 235 and g >= 235 and b >= 235


def is_dark(r, g, b):
    return r < 110 and g < 110 and b < 110


def counts(img, step=2):
    red = white = 0
    d = img.data
    w = img.width
    for y in range(0, img.height, step):
        row = y * w * 4
        for x in range(0, w, step):
            i = row + x * 4
            b, g, r = d[i], d[i + 1], d[i + 2]
            if r >= 150 and r - g >= 60 and r - b >= 60:
                red += 1
            elif r >= 235 and g >= 235 and b >= 235:
                white += 1
    return red, white


def look(img):
    red, white = counts(img)
    return {"error": red >= 150, "form": find_qr_box(img) is not None, "red": red, "white": white}


def red_fields(img, min_run=200):
    rows = []
    for y in range(img.height):
        xs = [x for x in range(0, img.width) if is_red(*img.rgb(x, y))]
        if len(xs) >= min_run:
            rows.append((y, xs[0], xs[-1]))
    groups = []
    for y, x0, x1 in rows:
        if groups and y - groups[-1][-1][0] <= 2:
            groups[-1].append((y, x0, x1))
        else:
            groups.append([(y, x0, x1)])
    lines = [(g[0][0], g[0][1], g[0][2]) for g in groups]
    fields = []
    for top, bottom in zip(lines[0::2], lines[1::2]):
        fields.append(((top[1] + top[2]) // 2, (top[0] + bottom[0]) // 2))
    return fields


def find_qr_box(img, min_count=80):
    cols = [0] * img.width
    rows = [0] * img.height
    for y in range(0, img.height, 2):
        for x in range(0, img.width, 2):
            if is_white(*img.rgb(x, y)):
                cols[x] += 1
                rows[y] += 1
    xs = [x for x, c in enumerate(cols) if c >= min_count // 2]
    ys = [y for y, c in enumerate(rows) if c >= min_count // 2]
    if not xs or not ys:
        return None
    x0, x1, y0, y1 = xs[0], xs[-1], ys[0], ys[-1]
    if x1 - x0 < 100 or y1 - y0 < 100 or abs((x1 - x0) - (y1 - y0)) > 40:
        return None
    return x0, y0, x1, y1


def qr_matrix(img):
    box = find_qr_box(img)
    if not box:
        return None
    x0, y0, x1, y1 = box[0] + 8, box[1] + 8, box[2] - 8, box[3] - 8
    dark =[(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
            if is_dark(*img.rgb(x, y))]
    if not dark:
        return None
    left = min(x for x, _ in dark)
    right = max(x for x, _ in dark)
    top = min(y for _, y in dark)
    bottom = max(y for _, y in dark)
    run = 0
    while left + run <= right and is_dark(*img.rgb(left + run, top)):
        run += 1
    if run < 7:
        return None
    size = (right - left + 1) / (run / 7.0)
    for n in sorted(range(21, 178, 4), key=lambda n: abs(size - n)):
        if abs(size - n) > 3:
            break
        mw = (right - left + 1) / float(n)
        mh = (bottom - top + 1) / float(n)
        m = [[is_dark(*img.rgb(int(left + (c + 0.5) * mw), int(top + (r + 0.5) * mh)))
              for c in range(n)] for r in range(n)]
        if finder_ok(m):
            return m
    return None


def finder_ok(m):
    n = len(m)

    def finder(r0, c0):
        for r in range(7):
            for c in range(7):
                ring = max(abs(r - 3), abs(c - 3))
                if m[r0 + r][c0 + c] != (ring != 2):
                    return False
        return True

    return finder(0, 0) and finder(0, n - 7) and finder(n - 7, 0)


def qr_text(m, quiet=2):
    n = len(m)
    size = n + 2 * quiet

    def light(r, c):
        r -= quiet
        c -= quiet
        return not (0 <= r < n and 0 <= c < n and m[r][c])

    lines = []
    for r in range(0, size, 2):
        line = []
        for c in range(size):
            top = light(r, c)
            bottom = light(r + 1, c) if r + 1 < size else False
            line.append("█" if top and bottom else "▀" if top else
                        "▄" if bottom else " ")
        lines.append("\x1b[40;97m" + "".join(line) + "\x1b[0m")
    return "\n".join(lines)
