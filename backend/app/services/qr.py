"""講座ページの QR コード(チラシ印刷用。segno 生成)。"""

import io

import segno


def png(url: str, scale: int = 6) -> bytes:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=scale)
    return buf.getvalue()
