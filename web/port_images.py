"""Validation and attribution shared by initial import and image-only backfills."""
import hashlib
from pathlib import Path

from PIL import Image


IMAGE_METADATA_FIELDS = (
    'image_caption', 'image_note', 'image_creator', 'image_source',
    'image_license', 'image_license_url', 'image_taken_on',
)
HISTORICAL_NOTE = '历史实景资料图，不代表当前设施或通关状态；使用 Commons 缩略版本，未改动图像内容。'


def validate_port_image(photo, root):
    root = Path(root).resolve()
    path = (root / photo['file']).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Image missing or outside catalog directory: {photo["file"]}')
    kind = photo.get('kind', 'photo')
    if kind not in ('photo', 'diagram', 'ai_scene'):
        raise ValueError('Unknown port illustration kind')
    required = ('creator', 'caption')
    if kind == 'photo':
        required += ('source', 'license', 'license_url')
    elif kind == 'diagram' and ('非实景' not in photo.get('note', '') or '不按比例' not in photo.get('note', '')):
        raise ValueError('Diagrams must be explicitly identified as non-photographic and not to scale')
    elif kind == 'ai_scene':
        if not all(label in photo.get('note', '') and label in photo.get('caption', '') for label in ('AI生成', '非现场实拍')):
            raise ValueError('Generated scenes must disclose AI generation in both caption and note')
        if photo.get('taken_on') or photo.get('source'):
            raise ValueError('Generated scenes cannot claim a photographic date or external photo source')
    if not all(photo.get(key) for key in required):
        raise ValueError('Image attribution is incomplete')
    if photo.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest() != photo['sha256']:
        raise ValueError(f'Image checksum mismatch: {photo["file"]}')
    with Image.open(path) as image:
        extensions = {'JPEG': ('.jpg', '.jpeg'), 'PNG': ('.png',), 'WEBP': ('.webp',)}
        if path.suffix.lower() not in extensions.get(image.format, ()):
            raise ValueError('Port images must be JPEG, PNG or WebP with a matching extension')
        image.verify()
    return path


def apply_port_image_metadata(article, photo):
    for field, value in port_image_metadata(photo).items():
        setattr(article, field, value)


def port_image_metadata(photo):
    values = {}
    for field in IMAGE_METADATA_FIELDS:
        key = field.removeprefix('image_')
        default = HISTORICAL_NOTE if key == 'note' else ''
        values[field] = photo.get(key, default)
    return values
