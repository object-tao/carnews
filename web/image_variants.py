"""Small display images; source files and publication controls stay unchanged."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image,ImageOps

SIZES={'card':640,'detail':1440}


@lru_cache(maxsize=128)
def _encode(path,mtime_ns,source_size,variant):
    # The file version is part of the key so replacement uploads invalidate old variants.
    with Image.open(path) as original:
        image=ImageOps.exif_transpose(original)
        image.thumbnail((SIZES[variant],SIZES[variant]),Image.Resampling.LANCZOS)
        image=image.convert('RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB')
        output=BytesIO()
        image.save(output,format='WEBP',quality=82 if variant=='card' else 88,method=4)
        return output.getvalue()


def display_image(field,variant):
    path=Path(field.path)
    stat=path.stat()
    return _encode(str(path),stat.st_mtime_ns,stat.st_size,variant)
