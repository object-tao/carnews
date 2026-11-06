from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.files.base import ContentFile
from django.test import TestCase,override_settings
from django.utils import timezone
from PIL import Image

from web.image_variants import _encode
from web.models import Article


@override_settings(SECURE_SSL_REDIRECT=False,STORAGES={
    'default':{'BACKEND':'django.core.files.storage.FileSystemStorage'},
    'staticfiles':{'BACKEND':'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class DisplayImageTests(TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.override=override_settings(MEDIA_ROOT=self.temp.name)
        self.override.enable()
        self.addCleanup(self.override.disable)
        _encode.cache_clear()
        self.addCleanup(_encode.cache_clear)
        output=BytesIO()
        Image.new('RGB',(1536,1024),(220,30,40)).save(output,'PNG')
        self.original=output.getvalue()
        self.item=Article.objects.create(slug='display-image',title='Display image',kind='resources',summary='Summary',body='Body',published=True,published_at=timezone.now())
        self.item.image.save('original.png',ContentFile(self.original),save=True)
        self.url='/article-images/display-image/'

    def test_display_sizes_preserve_the_original(self):
        for variant,expected in [('card',(640,427)),('detail',(1440,960))]:
            response=self.client.get(self.url,{'size':variant})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response['Content-Type'],'image/webp')
            self.assertEqual(response['Cache-Control'],'no-store')
            with Image.open(BytesIO(response.content)) as image:
                self.assertEqual(image.size,expected)
        original=self.client.get(self.url)
        self.assertEqual(b''.join(original.streaming_content),self.original)
        original.close()
        self.assertEqual(Path(self.item.image.path).read_bytes(),self.original)

    def test_cached_variants_cannot_bypass_unpublishing_or_schedule(self):
        self.assertEqual(self.client.get(self.url,{'size':'card'}).status_code,200)
        self.item.published=False
        self.item.save()
        for variant in ('','card','detail'):
            self.assertEqual(self.client.get(self.url,{'size':variant}).status_code,404)
        self.item.published=True
        self.item.published_at=timezone.now()+timedelta(days=1)
        self.item.save()
        self.assertEqual(self.client.get(self.url,{'size':'card'}).status_code,404)

    def test_replaced_source_invalidates_variant(self):
        before=self.client.get(self.url,{'size':'card'}).content
        Image.new('RGB',(1536,1024),(20,60,230)).save(self.item.image.path,'PNG')
        after=self.client.get(self.url,{'size':'card'}).content
        self.assertNotEqual(before,after)
        with Image.open(BytesIO(after)) as image:
            self.assertGreater(image.getpixel((0,0))[2],200)

    def test_unknown_variant_and_missing_source_are_not_served(self):
        self.assertEqual(self.client.get(self.url,{'size':'../../data'}).status_code,404)
        Path(self.item.image.path).unlink()
        self.assertEqual(self.client.get(self.url,{'size':'card'}).status_code,404)
