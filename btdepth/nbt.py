"""Minimal NBT reader (enough for 1.16 chunk data). Returns plain dict/list/int/str."""
import struct


def parse_nbt(data):
    pos = 0

    def read_payload(tag):
        nonlocal pos
        if tag == 1:
            v = struct.unpack_from(">b", data, pos)[0]; pos += 1; return v
        if tag == 2:
            v = struct.unpack_from(">h", data, pos)[0]; pos += 2; return v
        if tag == 3:
            v = struct.unpack_from(">i", data, pos)[0]; pos += 4; return v
        if tag == 4:
            v = struct.unpack_from(">q", data, pos)[0]; pos += 8; return v
        if tag == 5:
            v = struct.unpack_from(">f", data, pos)[0]; pos += 4; return v
        if tag == 6:
            v = struct.unpack_from(">d", data, pos)[0]; pos += 8; return v
        if tag == 7:
            n = struct.unpack_from(">i", data, pos)[0]; pos += 4
            v = list(struct.unpack_from(">%db" % n, data, pos)); pos += n; return v
        if tag == 8:
            n = struct.unpack_from(">H", data, pos)[0]; pos += 2
            v = data[pos:pos + n].decode("utf-8", "replace"); pos += n; return v
        if tag == 9:
            t = data[pos]; pos += 1
            n = struct.unpack_from(">i", data, pos)[0]; pos += 4
            return [read_payload(t) for _ in range(n)]
        if tag == 10:
            d = {}
            while True:
                t = data[pos]; pos += 1
                if t == 0:
                    return d
                name = read_payload(8)
                d[name] = read_payload(t)
        if tag == 11:
            n = struct.unpack_from(">i", data, pos)[0]; pos += 4
            v = list(struct.unpack_from(">%di" % n, data, pos)); pos += 4 * n; return v
        if tag == 12:
            n = struct.unpack_from(">i", data, pos)[0]; pos += 4
            v = list(struct.unpack_from(">%dq" % n, data, pos)); pos += 8 * n; return v
        raise ValueError("unknown NBT tag %d" % tag)

    root_tag = data[0]
    pos = 1
    read_payload(8)  # root name
    return read_payload(root_tag)
