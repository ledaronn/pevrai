"""Explicit UI test browser selection; Chrome failures never silently pass as Chromium."""
import os


def baslat(playwright, **options):
    secim = os.environ.get('PEVRAI_TEST_TARAYICI', 'chrome')
    if secim not in ('chrome', 'chromium'):
        raise ValueError('PEVRAI_TEST_TARAYICI must be chrome or chromium')
    print('UI test browser: ' + secim, flush=True)
    if secim == 'chrome':
        options['channel'] = 'chrome'
    return playwright.chromium.launch(**options)
