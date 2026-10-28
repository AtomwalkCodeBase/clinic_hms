import io
from unittest import mock

from django.test import SimpleTestCase, TestCase
from PIL import Image
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.patients.views import PortalDocumentPreviewView
from apps.documents import previews
from apps.documents.tests.tests import make_doc
from core.api.authentication import MockUser


def png_bytes(size=(600, 800), color=(200, 30, 30)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return out.getvalue()


def jpeg_bytes(size=(600, 800), orientation=None):
    img = Image.new("RGB", size, (30, 120, 200))
    out = io.BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation
        img.save(out, "JPEG", exif=exif)
    else:
        img.save(out, "JPEG")
    return out.getvalue()


def pdf_bytes(pages=1):
    import fitz
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        page.insert_text((72, 100), f"Page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def decode(data):
    img = Image.open(io.BytesIO(data))
    return img.format, img.size


class RenderPreviewTests(SimpleTestCase):
    def test_a_png_becomes_a_smaller_jpeg(self):
        fmt, size = decode(previews.render_preview(png_bytes((1200, 1600)), "image/png", 1, 300))
        self.assertEqual((fmt, size[0]), ("JPEG", 300))
        self.assertEqual(size[1], 400)

    def test_a_small_image_is_not_enlarged(self):
        _, size = decode(previews.render_preview(png_bytes((200, 260)), "image/png", 1, 600))
        self.assertEqual(size, (200, 260))

    def test_a_photo_stored_sideways_comes_out_upright(self):
        # orientation 6 = the pixels are stored rotated; the picture must be turned back (portrait, not landscape)
        _, size = decode(previews.render_preview(jpeg_bytes((800, 600), orientation=6), "image/jpeg", 1, 300))
        self.assertGreater(size[1], size[0])

    def test_a_transparent_png_gets_a_white_background(self):
        out = io.BytesIO()
        Image.new("RGBA", (400, 500), (0, 0, 0, 0)).save(out, "PNG")
        img = Image.open(io.BytesIO(previews.render_preview(out.getvalue(), "image/png", 1, 300)))
        r, g, b = img.getpixel((10, 10))
        self.assertGreater(min(r, g, b), 240)

    def test_a_photo_has_only_page_one(self):
        with self.assertRaises(previews.NoSuchPage):
            previews.render_preview(png_bytes(), "image/png", 2, 300)

    def test_pdf_pages_are_drawn_and_a_missing_page_is_reported(self):
        raw = pdf_bytes(2)
        for page in (1, 2):
            fmt, size = decode(previews.render_preview(raw, "application/pdf", page, 300))
            self.assertEqual((fmt, size[0]), ("JPEG", 300))
        with self.assertRaises(previews.NoSuchPage):
            previews.render_preview(raw, "application/pdf", 3, 300)

    def test_page_zero_is_no_page(self):
        with self.assertRaises(previews.NoSuchPage):
            previews.render_preview(pdf_bytes(), "application/pdf", 0, 300)

    def test_the_width_is_kept_inside_its_limits(self):
        self.assertEqual(previews.clamp_width(5), previews.MIN_WIDTH)
        self.assertEqual(previews.clamp_width(99999), previews.MAX_WIDTH)
        self.assertEqual(previews.clamp_width("abc"), previews.DEFAULT_WIDTH)
        self.assertEqual(previews.clamp_width(None), previews.DEFAULT_WIDTH)
        self.assertEqual(previews.clamp_width("450"), 450)

    def test_an_image_too_small_or_too_thin_is_refused(self):
        for size in ((16, 16), (1, 1), (2000, 100)):
            with self.assertRaises(previews.PreviewUnavailable, msg=str(size)):
                previews.render_preview(png_bytes(size), "image/png", 1, 300)

    def test_an_image_with_too_many_pixels_is_refused_before_it_is_decoded(self):
        with mock.patch.object(previews, "MAX_PIXELS", 1000):
            with self.assertRaises(previews.PreviewUnavailable):
                previews.render_preview(png_bytes((600, 800)), "image/png", 1, 300)

    def test_garbage_is_unavailable_not_an_error(self):
        with self.assertRaises(previews.PreviewUnavailable):
            previews.render_preview(b"not a pdf at all", "application/pdf", 1, 300)
        with self.assertRaises(previews.PreviewUnavailable):
            previews.render_preview(b"not an image", "image/png", 1, 300)

    def test_another_kind_of_file_is_unavailable(self):
        with self.assertRaises(previews.PreviewUnavailable):
            previews.render_preview(b"x", "text/plain", 1, 300)


@mock.patch("apps.patients.views.resolve_target_awpid_and_dob", return_value=("AWP-T1", None, None))
class PreviewViewTests(TestCase):
    databases = {"default"}

    def get(self, doc_id, raw, params=None, headers=None, awpid_user="AWP-T1", resolve=None):
        request = APIRequestFactory().get(f"/api/v1/portal/documents/{doc_id}/preview/", params or {}, **(headers or {}))
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "patient", "awpid": awpid_user}))
        with mock.patch("core.storage.get_bytes", return_value=raw):
            return PortalDocumentPreviewView.as_view()(request, doc_id=doc_id)

    def test_the_owner_gets_a_jpeg_with_cache_headers(self, _resolve):
        doc = make_doc(status="completed")
        resp = self.get(doc.pk, png_bytes((900, 1200)), {"width": "300"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/jpeg")
        self.assertIn("max-age=86400", resp["Cache-Control"])
        self.assertTrue(resp["ETag"])
        self.assertEqual(decode(resp.content)[1][0], 300)

    def test_a_pdf_page_two_and_a_missing_page(self, _resolve):
        doc = make_doc(status="completed")
        raw = pdf_bytes(2)
        self.assertEqual(self.get(doc.pk, raw, {"page": "2"}).status_code, 200)
        self.assertEqual(self.get(doc.pk, raw, {"page": "3"}).status_code, 404)

    def test_a_file_still_being_read_can_be_previewed(self, _resolve):
        doc = make_doc(status="extracting")
        self.assertEqual(self.get(doc.pk, png_bytes()).status_code, 200)

    def test_the_same_etag_gets_not_modified_without_reading_the_file(self, _resolve):
        doc = make_doc(status="completed")
        etag = self.get(doc.pk, png_bytes())["ETag"]
        with mock.patch("apps.documents.previews.render_preview") as draw:
            resp = self.get(doc.pk, png_bytes(), headers={"HTTP_IF_NONE_MATCH": etag})
        self.assertEqual(resp.status_code, 304)
        draw.assert_not_called()

    def test_a_different_width_is_a_different_etag(self, _resolve):
        doc = make_doc(status="completed")
        self.assertNotEqual(self.get(doc.pk, png_bytes(), {"width": "300"})["ETag"],
                            self.get(doc.pk, png_bytes(), {"width": "900"})["ETag"])

    def test_another_patients_document_is_not_found(self, resolve):
        doc = make_doc(awpid="AWP-T1", status="completed")
        resolve.return_value = ("AWP-OTHER", None, None)
        self.assertEqual(self.get(doc.pk, png_bytes()).status_code, 404)

    def test_a_bad_page_number_is_a_400_and_page_zero_a_404(self, _resolve):
        doc = make_doc(status="completed")
        self.assertEqual(self.get(doc.pk, png_bytes(), {"page": "x"}).status_code, 400)
        self.assertEqual(self.get(doc.pk, png_bytes(), {"page": "0"}).status_code, 404)

    def test_a_file_that_cannot_be_drawn_is_a_422(self, _resolve):
        doc = make_doc(status="completed")
        self.assertEqual(self.get(doc.pk, b"not a real file").status_code, 422)
        self.assertEqual(self.get(doc.pk, png_bytes((1, 1))).status_code, 422)

    def test_a_file_over_the_size_limit_is_refused(self, _resolve):
        doc = make_doc(status="completed")
        self.assertEqual(self.get(doc.pk, b"%PDF" + b"x" * previews.MAX_BYTES).status_code, 422)

    def test_a_staff_user_is_refused(self, _resolve):
        doc = make_doc(status="completed")
        request = APIRequestFactory().get(f"/api/v1/portal/documents/{doc.pk}/preview/")
        force_authenticate(request, user=MockUser({"user_id": 1, "role": "doctor", "awpid": ""}))
        self.assertEqual(PortalDocumentPreviewView.as_view()(request, doc_id=doc.pk).status_code, 403)

    def test_no_login_is_refused(self, _resolve):
        doc = make_doc(status="completed")
        request = APIRequestFactory().get(f"/api/v1/portal/documents/{doc.pk}/preview/")
        self.assertIn(PortalDocumentPreviewView.as_view()(request, doc_id=doc.pk).status_code, (401, 403))
