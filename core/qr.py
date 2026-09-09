"""
core/qr.py
----------
One place to turn a short string into a web-ready QR code PNG.

Every QR the app shows the user is server-rendered with the `qrcode`
library (already a project dependency) rather than pulling in a frontend
QR package. This helper returns a base64 `data:` URI ready to drop straight
into an <img src>.

`apps/billing/pdf.py::_qr_image` is deliberately NOT this — that one returns
a PIL image for embedding into a ReportLab invoice PDF, not a data URI for
the browser.
"""

import base64
import io


def render_qr_data_uri(text: str, *, box_size: int = 6, border: int = 2) -> str:
    """
    Render `text` as a QR PNG and return "data:image/png;base64,...".
    box_size/border default to the same values the emergency-QR screen has
    always used, so codes stay a familiar size across the app.
    """
    import qrcode

    qr = qrcode.QRCode(box_size=box_size, border=border)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
