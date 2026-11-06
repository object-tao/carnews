from django.db import migrations, models


def credit_existing_commons_photos(apps, schema_editor):
    apps.get_model('web', 'Article').objects.using(schema_editor.connection.alias).filter(
        image_source__startswith='https://commons.wikimedia.org/', image_note='',
    ).exclude(image='').update(image_note='历史实景资料图，不代表当前设施或通关状态；使用 Commons 缩略版本，未改动图像内容。')


class Migration(migrations.Migration):
    dependencies = [('web', '0005_article_body_format_article_editorial_notes_and_more')]
    operations = [
        migrations.AddField(model_name='article', name='image_note', field=models.TextField(blank=True, verbose_name='图片性质与使用说明')),
        migrations.RunPython(credit_existing_commons_photos, migrations.RunPython.noop),
    ]
