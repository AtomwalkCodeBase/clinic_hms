"""apps/opd/qr.py"""

import base64
import io


def render_qr_data_uri(text: str, *, box_size: int = 6, border: int = 2) -> str:
    """Render `text` as a QR PNG and return "data:image/png;base64,..."."""
    import qrcode

    qr = qrcode.QRCode(box_size=box_size, border=border)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
