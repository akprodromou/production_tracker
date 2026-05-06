# admin.py

from django.contrib import admin
from django.utils import timezone
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.utils.html import format_html
from decimal import Decimal

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ManufacturingOrder, ProductBatch, MaterialTransaction, WorkflowTask
)


# ─────────────────────────────────────────────
# UNIT
# ─────────────────────────────────────────────

@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']
    search_fields = ['name']
    ordering = ['name']


# ─────────────────────────────────────────────
# LOCATION
# ─────────────────────────────────────────────

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'is_external']
    list_filter = ['is_external']
    search_fields = ['name']
    ordering = ['name']


# ─────────────────────────────────────────────
# MATERIAL
# ─────────────────────────────────────────────

@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'sku', 'category', 'unit']
    list_filter = ['category', 'unit']
    search_fields = ['name', 'sku']
    ordering = ['category', 'name']
    readonly_fields = ['id']


# ─────────────────────────────────────────────
# MATERIAL TRANSACTION INLINE
# ─────────────────────────────────────────────

class MaterialTransactionInline(admin.TabularInline):
    model = MaterialTransaction
    extra = 0
    readonly_fields = [
        'transaction_type', 'quantity', 'product_batch', 'reference', 'created_at'
    ]
    fields = [
        'transaction_type', 'quantity', 'product_batch', 'reference', 'created_at'
    ]
    ordering = ['-created_at']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────
# RAW MATERIAL BATCH
# ─────────────────────────────────────────────

@admin.register(RawMaterialBatch)
class RawMaterialBatchAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'lot_number', 'material', 'location',
        'total_quantity', 'produced_qty', 'reserved_qty',
        'consumed_qty', 'available_qty', 'created_at'
    ]
    list_filter = ['material__category', 'location', 'material']
    search_fields = ['lot_number', 'material__name', 'material__sku']
    ordering = ['-created_at']
    readonly_fields = [
        'id', 'created_at',
        'produced_qty', 'reserved_qty',
        'consumed_qty', 'released_qty', 'available_qty'
    ]
    fieldsets = (
        ('Batch Identity', {
            'fields': ('id', 'material', 'lot_number', 'location', 'created_at')
        }),
        ('Quantity', {
            'fields': ('total_quantity',)
        }),
        ('Ledger Summary (read-only)', {
            'fields': (
                'produced_qty', 'reserved_qty',
                'consumed_qty', 'released_qty', 'available_qty'
            ),
            'classes': ('collapse',),
        }),
    )
    inlines = [MaterialTransactionInline]

    # ── computed columns ──────────────────────

    @admin.display(description='Produced')
    def produced_qty(self, obj):
        return obj.produced_quantity

    @admin.display(description='Reserved')
    def reserved_qty(self, obj):
        return obj.reserved_quantity

    @admin.display(description='Consumed')
    def consumed_qty(self, obj):
        return obj.consumed_quantity

    @admin.display(description='Released')
    def released_qty(self, obj):
        return obj.released_quantity

    @admin.display(description='Available')
    def available_qty(self, obj):
        qty = obj.available_quantity
        color = 'green' if qty > 0 else 'red'
        return format_html('<span style="color: {}; font-weight: bold;">{}</span>', color, qty)


# ─────────────────────────────────────────────
# MANUFACTURING ORDER
# ─────────────────────────────────────────────

@admin.register(ManufacturingOrder)
class ManufacturingOrderAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'raw_material_batch', 'created_at',
        'is_cancelled', 'cancellation_badge'
    ]
    list_filter = ['is_cancelled']
    search_fields = [
        'raw_material_batch__lot_number',
        'raw_material_batch__material__name',
        'raw_material_batch__material__sku',
    ]
    ordering = ['-created_at']
    readonly_fields = ['id', 'created_at']
    fieldsets = (
        ('Order', {
            'fields': ('id', 'raw_material_batch', 'created_at')
        }),
        ('Status', {
            'fields': ('is_cancelled',)
        }),
    )
    actions = ['cancel_orders', 'uncancel_orders']

    @admin.display(description='Status')
    def cancellation_badge(self, obj):
        if obj.is_cancelled:
            return format_html(
                '<span style="color: red; font-weight: bold;">CANCELLED</span>'
            )
        return format_html(
            '<span style="color: green;">Active</span>'
        )

    @admin.action(description='Cancel selected manufacturing orders')
    def cancel_orders(self, request, queryset):
        updated = queryset.update(is_cancelled=True)
        self.message_user(request, f'{updated} order(s) cancelled.')

    @admin.action(description='Re-activate selected manufacturing orders')
    def uncancel_orders(self, request, queryset):
        updated = queryset.update(is_cancelled=False)
        self.message_user(request, f'{updated} order(s) re-activated.')


# ─────────────────────────────────────────────
# PRODUCT BATCH
# ─────────────────────────────────────────────

class ProductBatchTransactionInline(admin.TabularInline):
    model = MaterialTransaction
    fk_name = 'product_batch'
    extra = 0
    readonly_fields = [
        'raw_material_batch', 'transaction_type',
        'quantity', 'reference', 'created_at'
    ]
    fields = [
        'raw_material_batch', 'transaction_type',
        'quantity', 'reference', 'created_at'
    ]
    ordering = ['-created_at']
    can_delete = False
    verbose_name = 'Material Transaction'
    verbose_name_plural = 'Material Transactions'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'batch_number', 'material',
        'quantity_produced', 'location', 'created_at'
    ]
    list_filter = ['material', 'location']
    search_fields = ['batch_number', 'material__name', 'material__sku']
    ordering = ['-created_at']
    readonly_fields = ['id', 'created_at']
    fieldsets = (
        ('Batch Identity', {
            'fields': ('id', 'material', 'batch_number', 'location', 'created_at')
        }),
        ('Quantity', {
            'fields': ('quantity_produced',)
        }),
    )
    inlines = [ProductBatchTransactionInline]


# ─────────────────────────────────────────────
# MATERIAL TRANSACTION
# ─────────────────────────────────────────────

@admin.register(MaterialTransaction)
class MaterialTransactionAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'transaction_type', 'quantity',
        'raw_material_batch', 'product_batch', 'reference', 'created_at'
    ]
    list_filter = ['transaction_type']
    search_fields = [
        'raw_material_batch__lot_number',
        'product_batch__batch_number',
        'reference',
    ]
    ordering = ['-created_at']
    readonly_fields = [
        'id', 'transaction_type', 'quantity',
        'raw_material_batch', 'product_batch',
        'reference', 'created_at'
    ]

    # Ledger is immutable — no adding or deleting through admin
    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


# ─────────────────────────────────────────────
# WORKFLOW TASK
# ─────────────────────────────────────────────

@admin.register(WorkflowTask)
class WorkflowTaskAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'description', 'status_badge', 'location',
        'raw_material_batch', 'product_batch',
        'expected_completion', 'actual_completion'
    ]
    list_filter = ['status', 'location']
    search_fields = [
        'description',
        'raw_material_batch__lot_number',
        'product_batch__batch_number',
    ]
    ordering = ['status', 'expected_completion']
    readonly_fields = ['id']
    fieldsets = (
        ('Task', {
            'fields': ('id', 'description', 'location')
        }),
        ('Linked Batches', {
            'fields': ('raw_material_batch', 'product_batch')
        }),
        ('Schedule & Status', {
            'fields': ('status', 'expected_completion', 'actual_completion')
        }),
    )
    actions = ['mark_in_progress', 'mark_done']

    @admin.display(description='Status')
    def status_badge(self, obj):
        colours = {
            'PENDING': 'orange',
            'IN_PROGRESS': 'blue',
            'DONE': 'green',
        }
        colour = colours.get(obj.status, 'grey')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            colour, obj.get_status_display()
        )

    @admin.action(description='Mark selected tasks as In Progress')
    def mark_in_progress(self, request, queryset):
        updated = queryset.exclude(status='DONE').update(status='IN_PROGRESS')
        self.message_user(request, f'{updated} task(s) marked as In Progress.')

    @admin.action(description='Mark selected tasks as Done')
    def mark_done(self, request, queryset):
        updated = queryset.exclude(status='DONE').update(
            status='DONE',
            actual_completion=timezone.now()
        )
        self.message_user(request, f'{updated} task(s) marked as Done.')