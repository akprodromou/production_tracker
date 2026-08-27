"""
inventory/palletizer.py
-----------------------
Palletizer engine for 120x80cm EUR-1 pallets.

Algorithm:
1. Calculate cartons and layers needed per SKU
2. Assign full layers to SKUs with layers_needed >= 1
3. Group fractional remainder layers by compatible carton heights
   (same height, or ratio >= 8:1 → taller on perimeter, shorter inside)
4. Sort layers heaviest-first (net weight * qty descending)
5. Stack layers onto pallets, respecting height limits:
   - >50% of SKUs have net_weight > 0.400kg → max 160cm
   - else → max 190cm
6. Stackable only if 100% of SKUs have net_weight > 0.400kg
"""

import math
from decimal import Decimal


PALLET_BASE = '120x80cm'
HEAVY_THRESHOLD = Decimal('0.400')  # kg/unit


def _ceil(x):
    return math.ceil(float(x))


def _compatible_heights(h1, h2):
    """Two carton heights can share a layer if same or ratio >= 8:1."""
    h1, h2 = float(h1), float(h2)
    if h1 == 0 or h2 == 0:
        return False
    if abs(h1 - h2) < 0.5:  # same height (within 0.5cm tolerance)
        return True
    ratio = max(h1, h2) / min(h1, h2)
    return ratio >= 8.0


def calculate_pallets(order_lines):
    """
    order_lines: list of SalesOrderLine objects with material.pack,
                 material.pallet_tie, material.carton_height,
                 material.net_weight, material.gross_weight

    Returns dict with:
      - skus: list of per-SKU data dicts
      - layers: ordered list of layer dicts (bottom to top)
      - pallets: list of pallet dicts
      - warnings: list of warning strings
      - stackable: bool
      - max_height: int (cm)
      - missing_data: list of SKU strings missing required fields
    """
    warnings = []
    missing_data = []
    skus = []

    # ── Build per-SKU data ────────────────────────────────────────
    for line in order_lines:
        mat = line.material
        qty = float(line.quantity)

        required = ['pack', 'pallet_tie', 'carton_height', 'net_weight']
        missing = [f for f in required if not getattr(mat, f)]
        if missing:
            missing_data.append(f"{mat.sku} (missing: {', '.join(missing)})")
            continue

        pack     = int(mat.pack)
        tie      = int(mat.pallet_tie)
        height   = float(mat.carton_height)
        net_w    = float(mat.net_weight)
        gross_w  = float(mat.gross_weight) if mat.gross_weight else net_w

        cartons  = math.ceil(qty / pack)
        layers_f = cartons / tie  # fractional layers

        skus.append({
            'sku':          mat.sku,
            'name':         mat.name,
            'qty':          qty,
            'pack':         pack,
            'tie':          tie,
            'carton_height': height,
            'net_weight':   net_w,
            'gross_weight': gross_w,
            'cartons':      cartons,
            'layers_f':     layers_f,
            'full_layers':  int(layers_f),
            'remainder':    layers_f % 1,  # fractional part
            'total_net':    round(net_w * qty, 3),
            'total_gross':  round(gross_w * qty, 3),
        })

    if not skus:
        return {
            'skus': [], 'layers': [], 'pallets': [],
            'warnings': warnings, 'stackable': False,
            'max_height': 190, 'missing_data': missing_data,
        }

    # ── Determine height limit and stackability ───────────────────
    heavy_count = sum(1 for s in skus if s['net_weight'] > float(HEAVY_THRESHOLD))
    pct_heavy   = heavy_count / len(skus)
    max_height  = 160 if pct_heavy > 0.5 else 190
    stackable   = pct_heavy == 1.0

    if pct_heavy > 0.5:
        warnings.append(f"{heavy_count}/{len(skus)} SKUs are heavy (>{HEAVY_THRESHOLD}kg/unit) — max pallet height 160cm")
    if stackable:
        warnings.append("All SKUs are heavy — pallets are stackable")

    # ── Build layer list ─────────────────────────────────────────
    # Sort SKUs heaviest first (for layer ordering)
    skus_sorted = sorted(skus, key=lambda s: s['net_weight'], reverse=True)

    layers = []  # each layer: {skus, height, cartons_used}

    # First pass: assign full layers per SKU
    for sku in skus_sorted:
        for _ in range(sku['full_layers']):
            layers.append({
                'skus':    [sku['sku']],
                'names':   [sku['name']],
                'height':  sku['carton_height'],
                'cartons': sku['tie'],
                'combined': False,
            })

    # Second pass: group remainder layers
    remainders = [s for s in skus_sorted if s['remainder'] > 0.001]

    # Try to combine remainders with compatible heights
    used = set()
    combined_layers = []

    for i, s1 in enumerate(remainders):
        if i in used:
            continue
        group = [s1]
        used.add(i)
        for j, s2 in enumerate(remainders):
            if j in used or j == i:
                continue
            if all(_compatible_heights(s['carton_height'], s2['carton_height']) for s in group):
                group.append(s2)
                used.add(j)
        # Use max carton height for the combined layer
        layer_height = max(s['carton_height'] for s in group)
        combined_layers.append({
            'skus':    [s['sku'] for s in group],
            'names':   [s['name'] for s in group],
            'height':  layer_height,
            'cartons': sum(math.ceil(s['remainder'] * s['tie']) for s in group),
            'combined': len(group) > 1,
        })

    # Add combined layers (lightest first since they go on top)
    combined_layers.sort(key=lambda l: max(
        next(s['net_weight'] for s in skus if s['sku'] in l['skus']), 0
    ), reverse=True)
    layers.extend(combined_layers)

    # ── Assign layers to pallets ──────────────────────────────────
    pallets = []
    current_pallet_layers = []
    current_height = 0

    for layer in layers:
        if current_height + layer['height'] > max_height and current_pallet_layers:
            # Start new pallet
            pallets.append({
                'number': len(pallets) + 1,
                'layers': current_pallet_layers,
                'total_height': current_height,
            })
            current_pallet_layers = []
            current_height = 0

        current_height += layer['height']
        layer['cumulative_height'] = round(current_height, 1)
        current_pallet_layers.append(layer)

    if current_pallet_layers:
        pallets.append({
            'number': len(pallets) + 1,
            'layers': current_pallet_layers,
            'total_height': round(current_height, 1),
        })

    # Add gross weight per pallet (sum of SKU gross weights for layers on that pallet)
    sku_gross_map = {s['sku']: s for s in skus}
    for pallet in pallets:
        pallet_gross = 0
        for layer in pallet['layers']:
            for sku_code in layer['skus']:
                s = sku_gross_map.get(sku_code)
                if s:
                    # Apportion gross weight by cartons on this layer
                    pallet_gross += s['gross_weight'] * s['pack'] * layer['cartons'] / len(layer['skus'])
        pallet['total_gross'] = round(pallet_gross, 1)
        pallet['total_gross_with_pallet'] = round(pallet_gross + 22.5, 1)

    return {
        'skus':         skus,
        'layers':       layers,
        'pallets':      pallets,
        'warnings':     warnings,
        'stackable':    stackable,
        'max_height':   max_height,
        'missing_data': missing_data,
        'total_net':    round(sum(s['total_net'] for s in skus), 2),
        'total_gross':  round(sum(s['total_gross'] for s in skus), 2),
    }
