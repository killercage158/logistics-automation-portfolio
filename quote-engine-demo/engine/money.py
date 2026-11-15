"""Money helpers. Trucking and customs fees are in Vietnamese dong (VND); the combined
quote is in US dollars. One fictional exchange rate keeps the demo repeatable.

In production, the rate comes from a published daily bank rate and is shown on the quote.
"""
FX_VND_PER_USD = 25_000          # fictional rate used by this demo


def vnd_to_usd(vnd):
    return vnd / FX_VND_PER_USD
