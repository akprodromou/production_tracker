from django import template
from decimal import Decimal

register = template.Library()

# Units that should display as whole numbers
WHOLE_NUMBER_UNITS = {
    'pcs', 'pc', 'piece', 'pieces', 'units', 'unit',
    'bottles', 'bottle', 'box', 'boxes', 'jar', 'jars',
    'can', 'cans', 'bag', 'bags', 'pack', 'packs',
    'sheet', 'sheets', 'roll', 'rolls', 'set', 'sets',
    'pair', 'pairs', 'item', 'items',
}


@register.filter
def smart_qty(value, unit=None):
    """
    Format a quantity based on its unit.
    Whole-number units (pcs, bottles, etc.) show no decimals.
    All others show up to 3 decimal places, stripping trailing zeros.
    Usage: {{ quantity|smart_qty:material.unit.name }}
           {{ quantity|smart_qty }}  (no unit = 3dp with trailing zero strip)
    """
    if value is None:
        return ''
    try:
        d = Decimal(str(value))
    except Exception:
        return value

    unit_lower = (unit or '').strip().lower()

    if unit_lower in WHOLE_NUMBER_UNITS:
        return str(int(d))
    else:
        # Round to 1 decimal place, strip trailing zero
        formatted = '{:.1f}'.format(d)
        if formatted.endswith('.0'):
            formatted = formatted[:-2]  # show as integer if .0
        return formatted


@register.filter
def getitem(obj, key):
    try:
        return obj[key]
    except (KeyError, TypeError, IndexError):
        return ''
