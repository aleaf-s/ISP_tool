"""Compact numeric presentation only; never use this to serialize model data."""
from decimal import Decimal
import math


def format_number(value, decimals=3, step=None):
    value=float(value)
    if not math.isfinite(value):return str(value)
    if step is not None and float(step)>0:
        decimals=max(0,-Decimal(str(step)).normalize().as_tuple().exponent)
    decimals=min(6,max(0,int(decimals)))
    text=f'{value:.{decimals}f}'
    if decimals:text=text.rstrip('0').rstrip('.')
    # Do not disguise a small but nonzero coefficient as exact zero.
    if float(text)==0:return '0' if value==0 else f'{value:.3g}'
    return text
