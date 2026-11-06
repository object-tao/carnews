from django.db import migrations

def foundations(apps,schema_editor):
    db = schema_editor.connection.alias
    Country = apps.get_model('web','Country')
    ResourceType = apps.get_model('web','ResourceType')
    Article = apps.get_model('web','Article')
    countries = [('china','中国'),('kazakhstan','哈萨克斯坦'),('kyrgyzstan','吉尔吉斯斯坦'),('uzbekistan','乌兹别克斯坦'),('tajikistan','塔吉克斯坦'),('turkmenistan','土库曼斯坦'),('russia','俄罗斯'),('belarus','白俄罗斯'),('united-kingdom','英国'),('vietnam','越南'),('laos','老挝'),('thailand','泰国'),('cambodia','柬埔寨'),('myanmar','缅甸'),('malaysia','马来西亚'),('singapore','新加坡'),('indonesia','印度尼西亚'),('philippines','菲律宾'),('brunei','文莱'),('timor-leste','东帝汶')]
    for i,(slug,name) in enumerate(countries):
        Country.objects.using(db).get_or_create(slug=slug,defaults={'name':name,'order':i})
    for i,(slug,name) in enumerate([('ports','口岸介绍'),('vehicles','车型介绍'),('bridges','桥梁介绍'),('knowledge','运输知识'),('other','其他资料')]):
        ResourceType.objects.using(db).get_or_create(slug=slug,defaults={'name':name,'order':i})
    knowledge=ResourceType.objects.using(db).get(slug='knowledge')
    Article.objects.using(db).filter(kind='resources',resource_type__isnull=True).update(resource_type=knowledge)
    # Generic regional pages deliberately remain untagged until actual country coverage is edited.
    Route=apps.get_model('web','Route')
    route=Route.objects.using(db).filter(slug='russia-belarus',country_tags__isnull=True).first()
    if route:
        route.country_tags.add(*Country.objects.using(db).filter(slug__in=['china','russia','belarus']))

class Migration(migrations.Migration):
    dependencies=[('web','0002_country_resourcetype_article_access_info_and_more')]
    operations=[migrations.RunPython(foundations,migrations.RunPython.noop)]
