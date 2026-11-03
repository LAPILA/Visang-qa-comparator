"""User-supplied product/environment addresses, recorded 2026-11-03.

These entries are configuration, not an availability or login verification.
Domain-only STG entries use HTTPS and the root path; supplied paths and hash
routes are preserved. No hostname is derived from another environment.
"""

ENVIRONMENT_LABELS = {
    'production': '운영', 'staging': 'STG', 'vibe-dev': '바이브 개발', 'legacy-dev': '레거시 개발',
}

_URLS = {
    'elementary-pc': (
        'https://e.vivasam.com/main', 'https://stg-e.vivasam.com/',
        'https://dev2-e.vivasam.com/main', 'https://e-dev.vivasam.com/',
    ),
    'secondary-pc': (
        'https://v.vivasam.com/main', 'https://stg-v.vivasam.com/',
        'https://dev2-v.vivasam.com/main', 'https://v-dev.vivasam.com/',
    ),
    'elementary-mobile': (
        'https://me.vivasam.com/', 'https://stg-me.vivasam.com/',
        'https://dev2-me.vivasam.com/', 'https://me-dev.vivasam.com/#/',
    ),
    'secondary-mobile': (
        'https://mv.vivasam.com/', 'https://stg-mv.vivasam.com/',
        'https://dev2-mv.vivasam.com/', 'https://mv-dev.vivasam.com/#/',
    ),
}

PRODUCT_ENVIRONMENTS = {
    product: [{'id': identifier, 'label': ENVIRONMENT_LABELS[identifier], 'url': url}
              for identifier, url in zip(ENVIRONMENT_LABELS, urls)]
    for product, urls in _URLS.items()
}
