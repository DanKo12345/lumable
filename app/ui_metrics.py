"""Shared geometry tokens for cards, grouped rows, forms and overlays.

The base unit is four pixels. Surfaces may use different multiples, but they
should not invent near-matches such as 9, 10, 13, 14 or 18.
"""

GRID = 4

SPACE_XS = GRID
SPACE_SM = GRID * 2
SPACE_MD = GRID * 3
SPACE_LG = GRID * 4
SPACE_XL = GRID * 5
SPACE_2XL = GRID * 6

ROW_INSET = SPACE_LG
PANEL_INSET = SPACE_2XL

FIELD_HEIGHT = 44
ACTION_HEIGHT = 40
ACTION_WIDTH = 128

FIELD_RADIUS = 12
CARD_RADIUS = 20
OVERLAY_RADIUS = 24
