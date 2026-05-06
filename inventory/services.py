from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal

from .models import RawMaterialBatch, MaterialTransaction


def reserve_material(batch_id, product_batch, quantity):
    with transaction.atomic():

        # 🔒 Lock the batch row
        batch = RawMaterialBatch.objects.select_for_update().get(id=batch_id)

        if quantity <= 0:
            raise ValidationError("Quantity must be positive")

        if batch.available_quantity < quantity:
            raise ValidationError("Not enough available stock")

        MaterialTransaction.objects.create(
            raw_material_batch=batch,
            product_batch=product_batch,
            transaction_type='RESERVED',
            quantity=quantity
        )

def consume_material(batch_id, product_batch, quantity):
    with transaction.atomic():

        batch = RawMaterialBatch.objects.select_for_update().get(id=batch_id)

        reserved = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='RESERVED'
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        consumed = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='CONSUMED'
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        remaining_reserved = reserved - consumed

        if quantity > remaining_reserved:
            raise ValidationError("Cannot consume more than reserved")

        MaterialTransaction.objects.create(
            raw_material_batch=batch,
            product_batch=product_batch,
            transaction_type='CONSUMED',
            quantity=quantity
        )

def release_material(batch_id, product_batch, quantity):
    with transaction.atomic():

        batch = RawMaterialBatch.objects.select_for_update().get(id=batch_id)

        reserved = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='RESERVED'
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        consumed = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='CONSUMED'
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        released = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='RELEASED'
        ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

        remaining_reserved = reserved - consumed - released

        if quantity > remaining_reserved:
            raise ValidationError("Cannot release more than remaining reserved")

        MaterialTransaction.objects.create(
            raw_material_batch=batch,
            product_batch=product_batch,
            transaction_type='RELEASED',
            quantity=quantity
        )

