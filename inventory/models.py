from django.db import models
from django.utils import timezone
from decimal import Decimal
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.db.models import DecimalField


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
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

    @property
    def reserved_quantity(self):
        return self.transactions.filter(
            transaction_type='RESERVED'
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

    @property
    def consumed_quantity(self):
        return self.transactions.filter(
            transaction_type='CONSUMED'
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

    @property
    def released_quantity(self):
        return self.transactions.filter(
            transaction_type='RELEASED'
        ).aggregate(
            total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
        )['total']

    @property
    def available_quantity(self):
        return (
            self.produced_quantity
            - self.reserved_quantity
            + self.released_quantity
        )


class ProductBatch(models.Model):
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
        self.full_clean()
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


# ─────────────────────────────────────────────
# CLIENT ORDERS
# ─────────────────────────────────────────────

class Client(models.Model):
    name = models.CharField(max_length=255)
    contact_email = models.EmailField(blank=True)
    contact_phone = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class ClientOrder(models.Model):
    STATUS_CHOICES = [
        ('DRAFT',       'Draft'),
        ('CONFIRMED',   'Confirmed'),
        ('IN_PRODUCTION', 'In Production'),
        ('PARTIALLY_FULFILLED', 'Partially Fulfilled'),
        ('FULFILLED',   'Fulfilled'),
        ('CANCELLED',   'Cancelled'),
    ]
    reference = models.CharField(max_length=100, unique=True)
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name='orders')
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default='DRAFT')
    order_date = models.DateField(default=timezone.now)
    required_by = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.reference} — {self.client.name}"

    @property
    def total_lines(self):
        return self.lines.count()

    @property
    def fulfilment_summary(self):
        """Returns dict of line-level fulfilment status counts."""
        lines = self.lines.all()
        return {
            'total':     lines.count(),
            'fulfilled': lines.filter(status='FULFILLED').count(),
            'partial':   lines.filter(status='PARTIAL').count(),
            'pending':   lines.filter(status='PENDING').count(),
        }

    class Meta:
        ordering = ['-order_date']


class ClientOrderLine(models.Model):
    STATUS_CHOICES = [
        ('PENDING',   'Pending'),
        ('ALLOCATED', 'Allocated to Production'),
        ('PARTIAL',   'Partially Fulfilled'),
        ('FULFILLED', 'Fulfilled'),
        ('CANCELLED', 'Cancelled'),
    ]
    order = models.ForeignKey(ClientOrder, on_delete=models.CASCADE, related_name='lines')
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        limit_choices_to={'category': 'FIN'}
    )
    quantity_ordered = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_fulfilled = models.DecimalField(max_digits=15, decimal_places=3, default=Decimal('0'))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.order.reference} — {self.material.name} × {self.quantity_ordered}"

    @property
    def quantity_remaining(self):
        return self.quantity_ordered - self.quantity_fulfilled

    @property
    def allocated_quantity(self):
        return self.allocations.aggregate(
            total=Coalesce(Sum('quantity_allocated'), Decimal('0'), output_field=DecimalField())
        )['total']

    class Meta:
        unique_together = [['order', 'material']]


# ─────────────────────────────────────────────
# PRODUCTION RUNS  (replaces ManufacturingOrder)
# ─────────────────────────────────────────────

class ProductionRun(models.Model):
    STATUS_CHOICES = [
        ('PLANNED',     'Planned'),
        ('ACTIVE',      'Active'),
        ('COMPLETED',   'Completed'),
        ('CANCELLED',   'Cancelled'),
    ]
    reference = models.CharField(max_length=100, unique=True)
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        limit_choices_to={'category': 'FIN'},
        help_text="The finished product being manufactured"
    )
    planned_quantity = models.DecimalField(max_digits=15, decimal_places=3)
    actual_quantity = models.DecimalField(
        max_digits=15, decimal_places=3,
        null=True, blank=True,
        help_text="Filled in on completion"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PLANNED')
    planned_start = models.DateField(null=True, blank=True)
    planned_end = models.DateField(null=True, blank=True)
    actual_start = models.DateField(null=True, blank=True)
    actual_end = models.DateField(null=True, blank=True)
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    # Links to the inventory layer
    product_batch = models.OneToOneField(
        ProductBatch,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='production_run',
        help_text="Set when the run is completed and a product batch is recorded"
    )

    def __str__(self):
        return f"{self.reference} — {self.material.name}"

    @property
    def allocated_quantity(self):
        return self.allocations.aggregate(
            total=Coalesce(Sum('quantity_allocated'), Decimal('0'), output_field=DecimalField())
        )['total']

    @property
    def unallocated_quantity(self):
        return self.planned_quantity - self.allocated_quantity

    class Meta:
        ordering = ['-created_at']


class ProductionRunAllocation(models.Model):
    """
    Many-to-many bridge between ClientOrderLine and ProductionRun.
    Records how many units from a run are allocated to an order line.
    """
    production_run = models.ForeignKey(
        ProductionRun,
        on_delete=models.CASCADE,
        related_name='allocations'
    )
    order_line = models.ForeignKey(
        ClientOrderLine,
        on_delete=models.CASCADE,
        related_name='allocations'
    )
    quantity_allocated = models.DecimalField(max_digits=15, decimal_places=3)
    created_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True)

    def clean(self):
        if self.quantity_allocated <= 0:
            raise ValidationError("Allocated quantity must be positive.")
        # Cannot allocate more than the run has unallocated (excluding self on edit)
        existing = self.production_run.allocations.exclude(pk=self.pk).aggregate(
            total=Coalesce(Sum('quantity_allocated'), Decimal('0'), output_field=DecimalField())
        )['total']
        if existing + self.quantity_allocated > self.production_run.planned_quantity:
            raise ValidationError(
                f"Allocation exceeds production run capacity. "
                f"Available: {self.production_run.planned_quantity - existing}"
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.production_run.reference} → "
            f"{self.order_line.order.reference} × {self.quantity_allocated}"
        )

    class Meta:
        unique_together = [['production_run', 'order_line']]


class ProductionComponent(models.Model):
    """
    Tracks the per-material status within a production run.
    One row per raw material / packaging item required.
    This is what answers: "bottles delivered, caps still in production."
    """
    STATUS_CHOICES = [
        ('PENDING',      'Pending — not yet ordered'),
        ('ORDERED',      'Ordered from supplier'),
        ('IN_TRANSIT',   'In Transit'),
        ('IN_WAREHOUSE', 'In Warehouse'),
        ('RESERVED',     'Reserved for this run'),
        ('CONSUMED',     'Consumed / used in production'),
        ('SHORT',        'Shortage — insufficient quantity'),
    ]
    production_run = models.ForeignKey(
        ProductionRun,
        on_delete=models.CASCADE,
        related_name='components'
    )
    material = models.ForeignKey(
        Material,
        on_delete=models.PROTECT,
        limit_choices_to={'category__in': ['RAW', 'PKG']}
    )
    quantity_required = models.DecimalField(max_digits=15, decimal_places=3)
    quantity_available = models.DecimalField(
        max_digits=15, decimal_places=3,
        default=Decimal('0')
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    raw_material_batch = models.ForeignKey(
        RawMaterialBatch,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        help_text="Set when a specific batch is assigned to this component"
    )
    expected_date = models.DateField(null=True, blank=True)
    actual_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.production_run.reference} | {self.material.name} | {self.status}"

    @property
    def is_ready(self):
        return self.status in ('IN_WAREHOUSE', 'RESERVED', 'CONSUMED')

    @property
    def quantity_shortfall(self):
        shortfall = self.quantity_required - self.quantity_available
        return shortfall if shortfall > 0 else Decimal('0')

    class Meta:
        unique_together = [['production_run', 'material']]
        ordering = ['production_run', 'material__name']


# ─────────────────────────────────────────────
# WORKFLOW TASKS  (general operational tasks)
# ─────────────────────────────────────────────

class WorkflowTask(models.Model):
    STATUS_CHOICES = [
        ('PENDING',     'Pending'),
        ('IN_PROGRESS', 'In Progress'),
        ('DONE',        'Done'),
    ]
    description = models.CharField(max_length=255)
    raw_material_batch = models.ForeignKey(
        RawMaterialBatch,
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    product_batch = models.ForeignKey(
        ProductBatch,
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    production_run = models.ForeignKey(
        ProductionRun,
        on_delete=models.CASCADE,
        null=True, blank=True
    )
    location = models.ForeignKey(Location, on_delete=models.PROTECT)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    expected_completion = models.DateField()                          # ← DATE only (was DateTimeField)
    actual_completion = models.DateField(null=True, blank=True)       # ← DATE only

    def __str__(self):
        return self.description
