from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db.models import DecimalField
from decimal import Decimal

from .models import RawMaterialBatch, MaterialTransaction


def reserve_material(batch_id, product_batch, quantity):
    with transaction.atomic():
        batch = RawMaterialBatch.objects.select_for_update().get(id=batch_id)

        if quantity <= 0:
            raise ValidationError("Quantity must be positive")

        if batch.available_quantity < quantity:
            raise ValidationError(
                f"Not enough available stock. Available: {batch.available_quantity}"
            )

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
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

        consumed = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='CONSUMED'
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

        remaining_reserved = reserved - consumed

        if quantity > remaining_reserved:
            raise ValidationError(
                f"Cannot consume more than reserved. Remaining reserved: {remaining_reserved}"
            )

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
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

        consumed = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='CONSUMED'
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

        released = batch.transactions.filter(
            product_batch=product_batch,
            transaction_type='RELEASED'
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

        remaining_reserved = reserved - consumed - released

        if quantity > remaining_reserved:
            raise ValidationError(
                f"Cannot release more than remaining reserved. Remaining: {remaining_reserved}"
            )

        MaterialTransaction.objects.create(
            raw_material_batch=batch,
            product_batch=product_batch,
            transaction_type='RELEASED',
            quantity=quantity
        )
