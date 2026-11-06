"""Stable snapshots protect existing port articles during an editorial release."""
import hashlib
import json


FIELDS = ('title', 'summary', 'body', 'location', 'body_format', 'reviewed_on', 'editorial_notes')


def digest(values, references):
    payload = {key:values[key] for key in FIELDS}
    if payload['reviewed_on'] is not None:
        payload['reviewed_on'] = str(payload['reviewed_on'])
    payload['references'] = sorted(references, key=lambda ref:(ref['url'],ref['title'],ref['note']))
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(',', ':')).encode()).hexdigest()


def catalog_digest(entry):
    return digest({**entry,'body_format':'markdown'},entry['references'])


def article_digest(article):
    return digest({key:getattr(article,key) for key in FIELDS},list(article.references.values('title','url','note')))
