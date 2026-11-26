from django.db import migrations


def seed_categories(apps, schema_editor):
    Category = apps.get_model('faq', 'Category')
    rows = [
        ('basics', '卡车与卡航基础', '认识卡航、整车运输及不同运输方式的适用场景。'),
        ('routes-and-transit', '运输线路与时效', '了解中亚、俄罗斯、欧洲及英国、东南亚的运输安排。'),
        ('pricing-and-fees', '运价与费用', '准备询价信息，了解费用构成及报价适用条件。'),
        ('vehicles-and-loading', '车型与装载', '了解大通道、容积车、平板车及货物配载。'),
        ('borders-and-transit', '口岸与通关', '了解口岸选择、预约、放行、换装与转关。'),
        ('customs-and-documents', '报关清关与单证', '整理所需资料，了解单证准备与常见问题。'),
        ('oversized-and-special', '大件与特殊货物', '关注设备尺寸、路线勘察、加固与运输条件。'),
        ('process-and-protection', '运输流程与保障', '了解订车、装卸、运输跟踪、保险与异常处理。'),
    ]
    for order, (slug, name, description) in enumerate(rows, 1):
        Category.objects.get_or_create(slug=slug, defaults={'name': name, 'description': description, 'order': order})


class Migration(migrations.Migration):
    dependencies = [('faq', '0001_initial')]
    operations = [migrations.RunPython(seed_categories, migrations.RunPython.noop)]
