"""A huge image must never reach the OCR models at full size: that is what ran a 2 GB server out of memory."""
import io
from unittest import mock

from django.test import SimpleTestCase
from PIL import Image

from core import ocr


def _png(width, height):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, "PNG")
    return buf.getvalue()


class OcrImageLimitTests(SimpleTestCase):
    def test_a_normal_image_is_left_alone(self):
        img = ocr._open_for_ocr(_png(1200, 800))
        self.assertEqual(img.size, (1200, 800))

    def test_a_large_image_is_shrunk_to_the_limit_keeping_its_shape(self):
        img = ocr._open_for_ocr(_png(5000, 2500))
        self.assertEqual(max(img.size), ocr.MAX_OCR_SIDE)
        self.assertEqual(img.size, (2500, 1250))

    def test_an_image_with_too_many_pixels_is_refused(self):
        with mock.patch.object(ocr, "MAX_OCR_PIXELS", 1_000_000):
            self.assertIsNone(ocr._open_for_ocr(_png(1500, 1000)))
            self.assertIsNone(ocr._load_rgb(_png(1500, 1000)))

    def test_a_tiny_image_is_refused_because_the_models_blow_it_up(self):
        self.assertIsNone(ocr._open_for_ocr(_png(1, 1)))
        self.assertIsNone(ocr._open_for_ocr(_png(1, 500)))
        self.assertIsNotNone(ocr._open_for_ocr(_png(ocr.MIN_OCR_SIDE, ocr.MIN_OCR_SIDE)))

    def test_a_thin_strip_is_refused_because_the_models_blow_it_up(self):
        self.assertIsNone(ocr._open_for_ocr(_png(40, 2500)))        # 62:1
        self.assertIsNone(ocr._open_for_ocr(_png(2500, 40)))
        self.assertIsNone(ocr._open_for_ocr(_png(300, 2500)))       # 8.3:1
        self.assertIsNotNone(ocr._open_for_ocr(_png(500, 2500)))    # 5:1, like a long receipt

    def test_the_size_is_read_from_the_header(self):
        self.assertEqual(ocr.image_size(_png(40, 60)), (40, 60))
        self.assertIsNone(ocr.image_size(b"junk"))

    def test_bytes_that_are_not_an_image_give_nothing(self):
        self.assertIsNone(ocr._open_for_ocr(b"not an image"))

    def test_the_array_the_models_get_is_the_shrunk_one(self):
        arr = ocr._load_rgb(_png(4000, 3000))
        self.assertEqual(arr.shape, (1875, 2500, 3))
