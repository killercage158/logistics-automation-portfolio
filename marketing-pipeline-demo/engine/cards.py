"""Card and image rules (MK-11) and the Instagram ratio rule (MK-16).

  fit_headline()     at most 60 characters (cut at a word, never mid-word) and at most 3 lines;
                     the largest font size that fits is chosen
  render_card()      a branded SVG card: fixed frame, headline, brand line. Feed card 1080x1080,
                     messaging-article cover 1280x720 (16:9)
  fit_for_instagram  Instagram accepts width/height between 0.8 and 1.91: wider images are
                     cropped to 1.91, taller ones are padded to 0.8 (4:5) so nothing is cut off

WHY a fixed frame and only the headline changing: the brand always looks the same, and
text drawn by code is always spelled right. A fully AI-generated card can misspell words
and drift off-brand.

In production the card is a brand template image with an AI-generated background and
the headline drawn on top in the brand font. Here the card is plain SVG, so the demo
needs no image library and the board can show it inline.
"""
from html import escape

MAX_HEADLINE = 60
MAX_LINES = 3
FONT_SIZES = [96, 84, 72, 60, 52]
FEED = (1080, 1080)
COVER = (1280, 720)
IG_MIN, IG_MAX = 0.8, 1.91
THEMES = {"news card": ("#0f3b63", "#1b7a8c"), "cover": ("#173a5e", "#2a6f97")}


def shorten(text, limit=MAX_HEADLINE):
    """Cut at the last space before the limit and add an ellipsis. Returns (text, was_cut)."""
    text = " ".join(text.split())
    if len(text) <= limit:
        return text, False
    cut = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "...", True


def wrap(text, per_line):
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > per_line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return lines + ([line] if line else [])


def fit_headline(headline, width=FEED[0]):
    """Return (lines, font_size, shortened_text, was_cut). Largest font with at most 3 lines wins."""
    text, was_cut = shorten(headline)
    usable = width * 0.84
    for size in FONT_SIZES:
        per_line = int(usable / (size * 0.56))      # average character width of a bold sans font
        lines = wrap(text, per_line)
        if len(lines) <= MAX_LINES:
            return lines, size, text, was_cut
    size = FONT_SIZES[-1]
    return wrap(text, int(usable / (size * 0.56)))[:MAX_LINES], size, text, was_cut


def render_card(headline, size=FEED, theme="news card", label="Logistics news"):
    """Return an SVG card. The headline is fitted with fit_headline()."""
    w, h = size
    lines, font, _, _ = fit_headline(headline, w)
    c1, c2 = THEMES.get(theme, THEMES["news card"])
    line_h = font * 1.15
    top = h * 0.5 - line_h * len(lines) / 2 + font * 0.8
    text = "".join(f"<text x='{w * 0.08:.0f}' y='{top + i * line_h:.0f}' font-size='{font}' "
                   f"font-family='Arial Black,Arial,sans-serif' font-weight='900' fill='#ffffff'>{escape(line)}</text>"
                   for i, line in enumerate(lines))
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<defs><linearGradient id='g' x1='0' y1='0' x2='1' y2='1'><stop offset='0' stop-color='{c1}'/>"
            f"<stop offset='1' stop-color='{c2}'/></linearGradient></defs>"
            f"<rect width='{w}' height='{h}' fill='url(#g)'/>"
            f"<rect x='{w * 0.08:.0f}' y='{h * 0.1:.0f}' width='{w * 0.16:.0f}' height='{h * 0.012:.0f}' fill='#f2a33a'/>"
            f"<text x='{w * 0.08:.0f}' y='{h * 0.17:.0f}' font-size='{h * 0.035:.0f}' font-family='Arial,sans-serif' "
            f"fill='#cfe3f1' letter-spacing='4'>{escape(label.upper())}</text>{text}"
            f"<text x='{w * 0.08:.0f}' y='{h * 0.92:.0f}' font-size='{h * 0.03:.0f}' font-family='Arial,sans-serif' "
            f"font-weight='700' fill='#ffffff'>DEMO FREIGHT CO.</text>"
            f"<text x='{w * 0.92:.0f}' y='{h * 0.92:.0f}' text-anchor='end' font-size='{h * 0.025:.0f}' "
            f"font-family='Arial,sans-serif' fill='#cfe3f1'>fictional brand</text></svg>")


def photo_placeholder(i, n, w=640, h=480):
    """A grey tile standing in for the source's own photo i of n."""
    return (f"<svg xmlns='http://www.w3.org/2000/svg' width='{w}' height='{h}' viewBox='0 0 {w} {h}'>"
            f"<rect width='{w}' height='{h}' fill='#c9d1de'/><text x='{w / 2}' y='{h / 2}' text-anchor='middle' "
            f"font-size='36' font-family='Arial,sans-serif' fill='#46526a'>source photo {i}/{n}</text></svg>")


def fit_for_instagram(width, height):
    """Return (action, new_width, new_height). action is ok, crop (too wide) or pad (too tall)."""
    ratio = width / height
    if ratio > IG_MAX:
        return "crop", round(height * IG_MAX), height
    if ratio < IG_MIN:
        return "pad", round(height * IG_MIN), height
    return "ok", width, height
