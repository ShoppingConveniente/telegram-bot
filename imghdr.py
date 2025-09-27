# Minimal imghdr replacement for Python 3.13+
# Detects jpeg / png / gif, which is enough for python-telegram-bot v13.x usage.
def what(file, h=None):
    def head32(f):
        if hasattr(f, "read"):
            pos = f.tell()
            data = f.read(32)
            try:
                f.seek(pos)
            except Exception:
                pass
            return data
        elif isinstance(f, (bytes, bytearray)):
            return bytes(f[:32])
        else:
            with open(f, "rb") as fp:
                return fp.read(32)

    try:
        data = h if h is not None else head32(file)
    except Exception:
        return None

    if not data:
        return None

    # JPEG
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    # PNG
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    # GIF
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"

    return None
