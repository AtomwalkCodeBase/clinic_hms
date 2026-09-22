import io

import numpy as np
from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from core import doc_crop


def _blank_photo(w=800, h=1200, color=(230, 230, 230)):
    """A photo with no rectangle in it at all — the "nothing to find" case."""
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG")
    return buf.getvalue()


def _photo_of_a_page(w=800, h=1200, margin=120, angle=0):
    """A synthetic photo: a lighter rectangular "page" on a darker background,
    optionally rotated — the shape auto_crop_straighten is meant to find."""
    bg = Image.new("RGB", (w, h), (40, 40, 40))
    page = Image.new("RGB", (w - 2 * margin, h - 2 * margin), (250, 250, 248))
    ImageDraw.Draw(page).rectangle([10, 10, page.width - 10, page.height - 10], outline=(0, 0, 0), width=4)
    if angle:
        page = page.rotate(angle, expand=True, fillcolor=(40, 40, 40))
    bg.paste(page, ((w - page.width) // 2, (h - page.height) // 2))
    buf = io.BytesIO()
    bg.save(buf, "JPEG", quality=95)
    return buf.getvalue()


class OrderPointsTests(SimpleTestCase):
    def test_orders_arbitrary_points_into_tl_tr_br_bl(self):
        # given in a scrambled order, on purpose
        pts = np.array([[500, 500], [10, 10], [500, 10], [10, 500]], dtype="float32")
        rect = doc_crop._order_points(pts)
        tl, tr, br, bl = rect
        self.assertLess(tl[0], tr[0])       # top-left is left of top-right
        self.assertLess(tl[1], bl[1])       # top-left is above bottom-left
        self.assertGreater(br[0], bl[0])    # bottom-right is right of bottom-left
        self.assertGreater(br[1], tr[1])    # bottom-right is below top-right


class FindDocumentQuadTests(SimpleTestCase):
    def _bgr(self, jpeg_bytes):
        import cv2
        arr = np.array(Image.open(io.BytesIO(jpeg_bytes)).convert("RGB"))
        return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

    def test_no_rectangle_returns_none(self):
        quad = doc_crop.find_document_quad(self._bgr(_blank_photo()))
        self.assertIsNone(quad)

    def test_finds_a_clear_rectangular_page(self):
        quad = doc_crop.find_document_quad(self._bgr(_photo_of_a_page()))
        self.assertIsNotNone(quad)
        self.assertEqual(quad.shape, (4, 2))

    def test_too_small_to_be_a_page_is_rejected(self):
        # a tiny rectangle (well under _MIN_AREA_FRACTION of the frame:
        # 100x500 = 50,000px vs a 20% threshold of 192,000px on an 800x1200 frame)
        quad = doc_crop.find_document_quad(self._bgr(_photo_of_a_page(margin=350)))
        self.assertIsNone(quad)

    def test_tiny_image_does_not_raise(self):
        import cv2
        tiny = cv2.cvtColor(np.array(Image.new("RGB", (5, 5))), cv2.COLOR_RGB2BGR)
        self.assertIsNone(doc_crop.find_document_quad(tiny))


class StraightenTests(SimpleTestCase):
    def test_straightens_a_known_quad_to_the_expected_size(self):
        import cv2
        bgr = cv2.cvtColor(np.array(Image.open(io.BytesIO(_photo_of_a_page())).convert("RGB")), cv2.COLOR_RGB2BGR)
        quad = doc_crop.find_document_quad(bgr)
        self.assertIsNotNone(quad)
        out = doc_crop.straighten(bgr, quad)
        self.assertIsNotNone(out)
        h, w = out.shape[:2]
        self.assertGreater(w, 400)
        self.assertGreater(h, 700)

    def test_degenerate_quad_returns_none(self):
        quad = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype="float32")   # 1x1 px
        self.assertIsNone(doc_crop.straighten(np.zeros((10, 10, 3), dtype="uint8"), quad))


class AutoCropStraightenTests(SimpleTestCase):
    def test_garbage_bytes_never_raise_and_return_none(self):
        self.assertIsNone(doc_crop.auto_crop_straighten(b"not an image"))

    def test_empty_bytes_never_raise(self):
        self.assertIsNone(doc_crop.auto_crop_straighten(b""))

    def test_page_with_background_gets_cropped(self):
        out = doc_crop.auto_crop_straighten(_photo_of_a_page())
        self.assertIsNotNone(out)
        # the result must itself be a valid, smaller-than-original JPEG
        cropped_img = Image.open(io.BytesIO(out))
        original_img = Image.open(io.BytesIO(_photo_of_a_page()))
        self.assertLess(cropped_img.width * cropped_img.height,
                        original_img.width * original_img.height)

    def test_page_already_filling_the_frame_is_left_alone(self):
        # margin=2: the "page" covers ~99.5% of the frame — nothing to gain
        out = doc_crop.auto_crop_straighten(_photo_of_a_page(margin=2))
        self.assertIsNone(out)

    def test_rotated_page_still_found(self):
        out = doc_crop.auto_crop_straighten(_photo_of_a_page(angle=8))
        self.assertIsNotNone(out)
