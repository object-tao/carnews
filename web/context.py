from .models import SiteSettings
from django.conf import settings
def site(request):
    return {'site': SiteSettings.objects.first() or SiteSettings(), 'canonical':settings.SITE_URL + request.path}
