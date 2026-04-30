"""
Garment Catalog PowerPoint Generator
Faithfully replicates the reference layout:
  - Pure white background
  - Large hero images filling the slide (bleeding to edge)
  - Bottom-right spec text box with bold label / normal value runs
  - Cover: left-half image + centred title on right
  - Closing: website · lines · cities
"""

from pathlib import Path
from PIL import Image as PILImage
from pptx import Presentation
from pptx.util import Pt, Emu, Inches
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.oxml.ns import qn
from lxml import etree

# ── Dimensions (16:9 widescreen) ──────────────────────────────────────────────
SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.500)

# Colour tokens
BLACK  = RGBColor(0x1A, 0x1A, 0x1A)
WHITE  = RGBColor(0xFF, 0xFF, 0xFF)
LGRAY  = RGBColor(0xF2, 0xF2, 0xF2)
MGRAY  = RGBColor(0x8A, 0x8A, 0x8A)
RULE   = RGBColor(0xCC, 0xCC, 0xCC)


def _in(val: float) -> Emu:
    return Inches(val)


# ── PPT skeleton ──────────────────────────────────────────────────────────────

def generate_catalog_ppt(
    groups: list[dict],
    output_path: str,
    brand_name: str = "GARMENT COLLECTION",
) -> str:
    prs = Presentation()
    prs.slide_width  = SLIDE_W
    prs.slide_height = SLIDE_H

    _cover(prs, brand_name)
    for i, grp in enumerate(groups, start=1):
        _product_slide(prs, grp, i)
    _closing(prs, brand_name)

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    prs.save(output_path)
    return output_path


# ── Cover slide ───────────────────────────────────────────────────────────────

def _cover(prs: Presentation, brand: str):
    """
    Cover layout mirrors reference Slide 1:
      - Full left-half panel (light gray or image placeholder)
      - Right half: title, season line, tagline
      - Small logo bottom-right
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    W, H = SLIDE_W, SLIDE_H

    _fill_white(slide)

    # ── Left panel (mirror of reference's left background image) ─────────────
    _rect(slide, 0, 0, _in(5.95), H, LGRAY)
    # Inner inset frame for polish
    gap = _in(0.20)
    _rect_outline(slide, gap, gap, _in(5.95) - 2 * gap, H - 2 * gap, RULE, 0.75)

    # ── Right half content ────────────────────────────────────────────────────
    right_x = _in(6.5)

    # Collection name – matches reference font size (36 pt)
    _textbox(slide,
             text=brand,
             x=right_x, y=_in(2.95), w=_in(6.6), h=_in(0.85),
             size=36, bold=False, align=PP_ALIGN.LEFT)

    # Thin rule below title
    _rect(slide, right_x, _in(3.90), _in(5.90), _in(0.018), RULE)

    # Season / category line
    _textbox(slide,
             text="AW 2026  ·  SL SELECTION",
             x=right_x, y=_in(4.05), w=_in(6.6), h=_in(0.45),
             size=11, bold=False, color=MGRAY, align=PP_ALIGN.LEFT,
             letter_spacing=160)

    # Tagline / descriptor
    _textbox(slide,
             text="STYLE SPECIFICATIONS & TECHNICAL DATA",
             x=right_x, y=_in(4.65), w=_in(6.6), h=_in(0.38),
             size=8, bold=False, color=MGRAY, align=PP_ALIGN.LEFT,
             letter_spacing=260)


# ── Product slide ─────────────────────────────────────────────────────────────

def _product_slide(prs: Presentation, group: dict, slide_num: int):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    W, H = SLIDE_W, SLIDE_H

    _fill_white(slide)

    # Collect images by type
    by_type: dict[str, list[str]] = {
        "front": [], "back": [], "detail": [], "spec_label": []
    }
    for img in group.get("images", []):
        t   = img.get("image_type", "unknown")
        src = img.get("processed_path") or img.get("original_path", "")
        if src and Path(src).exists():
            bucket = by_type.get(t)
            if bucket is not None:
                bucket.append(src)

    # Build ordered image list: front → back → detail → spec_label
    ordered = (
        by_type["front"][:1]
        + by_type["back"][:1]
        + by_type["detail"][:2]
        + by_type["spec_label"][:1]
    )

    n = len(ordered)

    if n == 0:
        _place_placeholder(slide, _in(0.6), _in(0.6), W - _in(1.2), H - _in(1.2),
                           "NO IMAGES")

    elif n == 1:
        # Single image — centred, generous margin
        _image_slot(slide, ordered[0], _in(1.5), _in(0.15), _in(10.0), H - _in(0.3))

    elif n == 2:
        # ── Two images side-by-side, near-edge, matching reference 2-image slides ──
        # Left image: starts at left edge with tiny margin
        _image_slot(slide, ordered[0], _in(0.04), _in(0.15), _in(5.2), H - _in(0.3))
        # Right image: fills right side, ends before spec box area
        _image_slot(slide, ordered[1], _in(5.3),  _in(0.15), _in(4.8), H - _in(0.3))

    else:
        # ── 3-image layout: left + center fill height; right = top detail + spec ──
        # Left main image (~front view)
        _image_slot(slide, ordered[0], _in(0.04), _in(0.15), _in(4.82), H - _in(0.3))
        # Centre main image (~back view)
        _image_slot(slide, ordered[1], _in(4.9),  _in(0.15), _in(4.55), H - _in(0.3))
        # Right column — detail image(s) stacked in the TOP portion only
        # (lower portion is reserved for the spec box)
        right_x   = _in(9.5)
        right_w   = _in(3.70)
        right_imgs = ordered[2:]
        # Each detail image gets roughly a third of the height; spec box at bottom
        detail_slot_h = _in(2.55)
        for j, img_path in enumerate(right_imgs[:2]):
            _image_slot(slide, img_path,
                        right_x,
                        _in(0.15) + j * (detail_slot_h + _in(0.14)),
                        right_w,
                        detail_slot_h)

    # ── Spec box (bottom-right, matches reference positioning exactly) ────────
    gdata   = group.get("garment_data") or {}
    ref     = gdata.get("reference_number") or group.get("style_id", "")
    # AFS = a secondary/file code; use style_id if it differs from ref, else "—"
    style_id = group.get("style_id", "")
    afs     = style_id if (style_id and style_id != ref) else (gdata.get("gsm") or "—")
    comp    = gdata.get("fabric_composition") or "—"
    gsm     = gdata.get("gsm") or "—"
    date    = gdata.get("date") or ""

    # Exact spec box position mirrors reference (9.57" L, 5.56" T in ref)
    spec_x = _in(9.57)
    spec_y = _in(5.50)
    spec_w = _in(3.72)
    spec_h = _in(1.78)

    if n <= 2:
        # With only 2 wide images, the right edge is the spec box area
        spec_x = _in(10.10)
        spec_y = _in(5.20)
        spec_w = _in(3.10)
        spec_h = _in(1.78)

    _spec_box(slide, spec_x, spec_y, spec_w, spec_h, ref, afs, comp, gsm, date)

    # ── Slide number — bottom right corner ───────────────────────────────────
    _textbox(slide,
             text=f"{slide_num:02d}",
             x=W - _in(0.55), y=H - _in(0.38),
             w=_in(0.45), h=_in(0.3),
             size=8, bold=False, color=MGRAY, align=PP_ALIGN.RIGHT)


# ── Closing slide ─────────────────────────────────────────────────────────────

def _closing(prs: Presentation, brand: str):
    """
    Closing slide — mirrors reference Slide 18:
      - White background
      - Website URL centred
      - Two horizontal rules flanking the URL (at same vertical level)
      - City list below
    """
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    W, H = SLIDE_W, SLIDE_H

    _fill_white(slide)

    # ── Horizontal rules exactly as in reference ──────────────────────────────
    # Reference: rule1 at L=1.047", T=3.172"; rule2 at L=7.988", T=3.172"
    rule_y = _in(3.17)
    _rect(slide, _in(1.05), rule_y, _in(4.17), _in(0.018), RULE)
    _rect(slide, _in(7.99), rule_y, _in(4.17), _in(0.018), RULE)

    # ── Website URL — reference: L=5.345", T=2.954" ──────────────────────────
    _textbox(slide,
             text="www.garmentsupply.com",
             x=_in(5.35), y=_in(2.85),
             w=_in(2.65), h=_in(0.42),
             size=12, bold=False, align=PP_ALIGN.CENTER)

    # ── City list — reference: L=5.162", T=4.507", size=12 ───────────────────
    _textbox(slide,
             text="Bengaluru  .  Chennai  .  Gurugram  .  Tirupur",
             x=_in(4.20), y=_in(4.51),
             w=_in(5.00), h=_in(0.38),
             size=11, bold=False, color=MGRAY, align=PP_ALIGN.CENTER)

    # ── Season / brand footer ─────────────────────────────────────────────────
    _textbox(slide,
             text=f"{brand}  ·  2026",
             x=_in(4.20), y=H - _in(0.65),
             w=_in(5.00), h=_in(0.38),
             size=9, bold=False, color=MGRAY, align=PP_ALIGN.CENTER,
             letter_spacing=120)


# ── Image helpers ─────────────────────────────────────────────────────────────

def _image_slot(slide, img_path: str, x: Emu, y: Emu, max_w: Emu, max_h: Emu):
    """
    Place an image inside a slot.
    Uses CONTAIN mode: image fits fully within bounds, centered, no cropping.
    Aligns portrait images to top; landscape images to centre.
    """
    try:
        pil = PILImage.open(img_path)
        iw, ih = pil.size
        ratio_w = max_w / iw
        ratio_h = max_h / ih
        scale   = min(ratio_w, ratio_h)
        fw = int(iw * scale)
        fh = int(ih * scale)
        # Horizontal centre, vertical top-align for portrait images
        ox = (max_w - fw) // 2
        oy = 0 if ih >= iw else (max_h - fh) // 2
        slide.shapes.add_picture(str(img_path), x + ox, y + oy, fw, fh)
    except Exception:
        _place_placeholder(slide, x, y, max_w, max_h, "IMG")


def _place_image_contain(slide, img_path: str, x, y, max_w, max_h):
    _image_slot(slide, img_path, x, y, max_w, max_h)


def _place_placeholder(slide, x, y, w, h, label: str):
    shape = slide.shapes.add_shape(1, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = LGRAY
    shape.line.color.rgb = RULE
    shape.line.width = Pt(0.5)
    tf = shape.text_frame
    tf.paragraphs[0].alignment = PP_ALIGN.CENTER
    run = tf.paragraphs[0].add_run()
    run.text = label
    run.font.size = Pt(9)
    run.font.color.rgb = MGRAY


# ── Spec text box — mirrors reference format exactly ─────────────────────────

def _spec_box(slide, x, y, w, h, ref, afs, comp, gsm, date=""):
    """
    Renders the spec block exactly like the reference:
      REF NO   : <value>
      AFS       : <value>
      COMP    : <value>
      GSM      : <value>

    Each line = one paragraph with two runs:
      run1: bold label  (e.g. "REF NO   : ")
      run2: normal value (e.g. "AND-001")
    """
    txb = slide.shapes.add_textbox(x, y, w, h)
    tf  = txb.text_frame
    tf.word_wrap = True

    rows = [
        ("REF NO   : ", ref   or "—"),
        ("AFS          : ",  afs  or "—"),
        ("COMP     : ", comp  or "—"),
        ("GSM        : ", gsm  or "—"),
    ]
    if date:
        rows.append(("DATE       : ", date))

    for i, (label, value) in enumerate(rows):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.space_before = Pt(1.5)
        p.space_after  = Pt(0)

        # Label run — bold
        r_label = p.add_run()
        r_label.text       = label
        r_label.font.bold  = True
        r_label.font.size  = Pt(10.5)
        r_label.font.name  = "Calibri"

        # Value run — normal
        r_val = p.add_run()
        r_val.text       = str(value)[:60]
        r_val.font.bold  = False
        r_val.font.size  = Pt(10.5)
        r_val.font.name  = "Calibri"


# ── Shape / text utilities ────────────────────────────────────────────────────

def _fill_white(slide):
    bg   = slide.background
    fill = bg.fill
    fill.solid()
    fill.fore_color.rgb = WHITE


def _rect(slide, x, y, w, h, color: RGBColor):
    shape = slide.shapes.add_shape(1, x, y, w, h)
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape


def _rect_outline(slide, x, y, w, h, color: RGBColor, width_pt: float = 0.75):
    shape = slide.shapes.add_shape(1, x, y, w, h)
    shape.fill.background()
    shape.line.color.rgb = color
    shape.line.width = Pt(width_pt)
    return shape


def _textbox(slide, text: str, x, y, w, h,
             size=12, bold=False, color: RGBColor = BLACK,
             align=PP_ALIGN.LEFT, letter_spacing: int = 0,
             spacing_before: int = 0):
    txb = slide.shapes.add_textbox(x, y, w, h)
    tf  = txb.text_frame
    tf.word_wrap = False
    p   = tf.paragraphs[0]
    p.alignment = align
    if spacing_before:
        p.space_before = Pt(spacing_before)
    run = p.add_run()
    run.text          = text
    run.font.bold     = bold
    run.font.size     = Pt(size)
    run.font.color.rgb = color
    run.font.name     = "Calibri"

    if letter_spacing:
        # Apply letter spacing via rPr XML
        rPr = run._r.get_or_add_rPr()
        rPr.set("spc", str(letter_spacing))

    return txb
