from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError


class Unit(models.Model):
    name = models.CharField(max_length=20, unique=True)

    def __str__(self):
        return self.name


class Location(models.Model):
    name = models.CharField(max_length=100)
    is_external = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class Material(models.Model):
    """
    SKU definition (applies to both raw materials and finished products)
    """
    CATEGORY_CHOICES = [
        ('RAW', 'Raw Material'),
        ('PKG', 'Packaging'),
        ('FIN', 'Finished Product'),
    ]

    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=50, unique=True)
    unit = models.ForeignKey(Unit, on_delete=models.PROTECT)
    category = models.CharField(max_length=3, choices=CATEGORY_CHOICES)

    def __str__(self):
        return f"{self.name} ({self.sku})"
    

class RawMaterialBatch(models.Model):
    material = models.ForeignKey('Material', on_delete=models.PROTECT)
    lot_number = models.CharField(max_length=100, unique=True)

    total_quantity = models.DecimalField(max_digits=15, decimal_places=3)
    created_at = models.DateTimeField(default=timezone.now)
    location = models.ForeignKey('Location', on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.material.sku} | LOT: {self.lot_number}"

    @property
    def produced_quantity(self):
        return self.transactions.filter(
            transaction_type='PRODUCED'
        ).aggregate(total=Coalesce(Sum('quantity'), 0))['total']

    @property
    def reserved_quantity(self):
        return self.transactions.filter(
            transaction_type='RESERVED'
        ).aggregate(total=Coalesce(Sum('quantity'), 0))['total']

    @property
    def consumed_quantity(self):
        return self.transactions.filter(
            transaction_type='CONSUMED'
        ).aggregate(total=Coalesce(Sum('quantity'), 0))['total']

    @property
    def released_quantity(self):
        return self.transactions.filter(
            transaction_type='RELEASED'
        ).aggregate(total=Coalesce(Sum('quantity'), 0))['total']

    @property
    def available_quantity(self):
        return (
            self.produced_quantity
            - self.reserved_quantity
            + self.released_quantity
        )
    
class ManufacturingOrder(models.Model):
    """
    Produces exactly ONE RawMaterialBatch
    """
    created_at = models.DateTimeField(default=timezone.now)

    raw_material_batch = models.OneToOneField(
        RawMaterialBatch,
        on_delete=models.PROTECT,
        related_name='manufacturing_order'
    )

    is_cancelled = models.BooleanField(default=False)

    def __str__(self):
        return f"MO-{self.id} → {self.raw_material_batch}"

class ProductBatch(models.Model):
    """
    Batch of finished product
    """
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        limit_choices_to={'category': 'FIN'}
    )

    batch_number = models.CharField(max_length=100, unique=True)

    quantity_produced = models.DecimalField(max_digits=15, decimal_places=3)

    created_at = models.DateTimeField(default=timezone.now)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)

    def __str__(self):
        return f"{self.material.sku} | BATCH: {self.batch_number}"
    
class MaterialTransaction(models.Model):
    """
    Immutable ledger of all material movements
    """

    class TransactionType(models.TextChoices):
        PRODUCED = 'PRODUCED', 'Produced via Manufacturing'
        RESERVED = 'RESERVED', 'Reserved for Production'
        CONSUMED = 'CONSUMED', 'Consumed in Production'
        RELEASED = 'RELEASED', 'Reservation Released'

    raw_material_batch = models.ForeignKey(
        'RawMaterialBatch',
        on_delete=models.PROTECT,
        related_name='transactions'
    )

    product_batch = models.ForeignKey(
        'ProductBatch',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='material_transactions'
    )

    transaction_type = models.CharField(max_length=20, choices=TransactionType.choices)

    quantity = models.DecimalField(max_digits=15, decimal_places=3)

    created_at = models.DateTimeField(auto_now_add=True)

    reference = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional external reference (e.g., order ID)"
    )

    def clean(self):
        if self.quantity <= 0:
            raise ValidationError("Quantity must be positive")

        if self.transaction_type in ['RESERVED', 'CONSUMED'] and not self.product_batch:
            raise ValidationError("Product batch required")

        if self.transaction_type == 'PRODUCED' and self.product_batch:
            raise ValidationError("Produced should not reference product batch")
        
        
    def save(self, *args, **kwargs):
        self.full_clean()  # ensures clean() runs
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_type} | {self.quantity} | {self.raw_material_batch}"
    
    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__gt=0),
                name='quantity_positive'
            )
        ]

class WorkflowTask(models.Model):
    """
    Now tied to a specific batch, not generic material
    """

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('DONE', 'Done'),
    ]

    description = models.CharField(max_length=255)

    raw_material_batch = models.ForeignKey(
        RawMaterialBatch,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    product_batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )

    location = models.ForeignKey(Location, on_delete=models.PROTECT)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    expected_completion = models.DateTimeField()
    actual_completion = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.description
    
