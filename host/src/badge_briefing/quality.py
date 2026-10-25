import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageStat, UnidentifiedImageError

MAX_BYTES = 10_000_000
MAX_PIXELS = 50_000_000


@dataclass
class Quality:
    jpeg: bytes
    reasons: list[str]
    metrics: dict


def gate(data: bytes) -> Quality:
    if len(data) > MAX_BYTES or not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Upload a complete JPEG smaller than 10 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format != "JPEG" or source.width * source.height > MAX_PIXELS:
                    raise ValueError("JPEG exceeds the 50 megapixel safety limit.")
                source.load()
                im = source.convert("RGB")
        im.thumbnail((1600, 1600))
        gray = im.convert("L")
        stats = ImageStat.Stat(gray)
        edge = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
        histogram = gray.histogram()
        glare = sum(histogram[250:]) / (gray.width * gray.height)
        reasons = []
        if min(im.size) < 200:
            reasons.append("Move closer or increase camera resolution.")
        if stats.mean[0] < 35:
            reasons.append("Add soft light; the image is too dark.")
        if edge < 45:
            reasons.append("Hold still and focus on the printed text.")
        if glare > 0.90:
            reasons.append("Tilt the page or badge to reduce glare or overexposure.")
        out = io.BytesIO()
        im.save(out, format="JPEG", quality=90)  # strips EXIF and all original metadata
        return Quality(
            out.getvalue(),
            reasons,
            {"width": im.width, "height": im.height, "edge_variance": round(edge), "glare": round(glare, 3)},
        )
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValueError("The JPEG could not be safely decoded.") from exc
