import bleach
import markdown
from django import template
from django.utils.html import linebreaks
from django.utils.safestring import mark_safe
register = template.Library()

@register.filter
def article_body(article):
    if article.body_format != 'markdown':
        return mark_safe(linebreaks(article.body, autoescape=True))
    html = markdown.markdown(article.body, extensions=['tables','fenced_code','sane_lists'])
    # User files and administrator content are untrusted HTML. Only editorial formatting survives.
    html = bleach.clean(html, tags=['p','br','h2','h3','h4','ul','ol','li','strong','em','blockquote','table','thead','tbody','tr','th','td','a','pre','code','hr'], attributes={'a':['href','title']}, protocols=['https','http'], strip=True)
    return mark_safe(html)
