from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ProductBatch, MaterialTransaction,
    Client, ClientOrder, ClientOrderLine,
    ProductionRun, ProductionRunAllocation,
    ProductionComponent, ProductionRunShipment,
)


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display  = ['id', 'name']
    search_fields = ['name']


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display  = ['id', 'name', 'is_external']
    list_filter   = ['is_external']
    search_fields = ['name']


@admin.register(Material)
class MaterialAdmin(admin.ModelAdmin):
    list_display  = ['id', 'name', 'sku', 'category', 'unit']
    list_filter   = ['category', 'unit']
    search_fields = ['name', 'sku']


class MaterialTransactionInline(admin.TabularInline):
    model           = MaterialTransaction
    extra           = 0
    readonly_fields = ['transaction_type', 'quantity', 'product_batch', 'reference', 'created_at']
    can_delete      = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(RawMaterialBatch)
class RawMaterialBatchAdmin(admin.ModelAdmin):
    list_display    = ['id', 'lot_number', 'material', 'location', 'total_quantity', 'available_qty', 'created_at']
    list_filter     = ['material__category', 'location']
    search_fields   = ['lot_number', 'material__name', 'material__sku']
    readonly_fields = ['id', 'created_at', 'available_qty', 'produced_qty', 'reserved_qty', 'consumed_qty', 'released_qty']
    inlines         = [MaterialTransactionInline]

    @admin.display(description='Available')
    def available_qty(self, obj):
        qty   = obj.available_quantity
        color = 'green' if qty > 0 else 'red'
        return format_html('<span style="color:{};font-weight:bold">{}</span>', color, qty)

    @admin.display(description='Produced')
    def produced_qty(self, obj): return obj.produced_quantity

    @admin.display(description='Reserved')
    def reserved_qty(self, obj): return obj.reserved_quantity

    @admin.display(description='Consumed')
    def consumed_qty(self, obj): return obj.consumed_quantity

    @admin.display(description='Released')
    def released_qty(self, obj): return obj.released_quantity


@admin.register(MaterialTransaction)
class MaterialTransactionAdmin(admin.ModelAdmin):
    list_display  = ['id', 'transaction_type', 'quantity', 'raw_material_batch', 'product_batch', 'reference', 'created_at']
    list_filter   = ['transaction_type']
    search_fields = ['raw_material_batch__lot_number', 'product_batch__batch_number', 'reference']
    readonly_fields = ['id', 'transaction_type', 'quantity', 'raw_material_batch', 'product_batch', 'reference', 'created_at']

    def has_add_permission(self, request):        return False
    def has_delete_permission(self, request, obj=None): return False
    def has_change_permission(self, request, obj=None): return False


class ProductBatchTransactionInline(admin.TabularInline):
    model           = MaterialTransaction
    fk_name         = 'product_batch'
    extra           = 0
    readonly_fields = ['raw_material_batch', 'transaction_type', 'quantity', 'reference', 'created_at']
    can_delete      = False

    def has_add_permission(self, request, obj=None): return False


@admin.register(ProductBatch)
class ProductBatchAdmin(admin.ModelAdmin):
    list_display  = ['id', 'batch_number', 'material', 'quantity_produced', 'location', 'created_at']
    list_filter   = ['material', 'location']
    search_fields = ['batch_number', 'material__name']
    inlines       = [ProductBatchTransactionInline]


# ─────────────────────────────────────────────
# CLIENTS & ORDERS
# ─────────────────────────────────────────────

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display  = ['id', 'name', 'contact_email', 'contact_phone', 'created_at']
    search_fields = ['name', 'contact_email']


class ClientOrderLineInline(admin.TabularInline):
    model  = ClientOrderLine
    extra  = 1
    fields = ['material', 'quantity_ordered', 'quantity_fulfilled', 'status', 'notes']


@admin.register(ClientOrder)
class ClientOrderAdmin(admin.ModelAdmin):
    list_display    = ['id', 'reference', 'client', 'status', 'order_date', 'required_by']
    list_filter     = ['status', 'client']
    search_fields   = ['reference', 'client__name']
    readonly_fields = ['id', 'created_at']
    inlines         = [ClientOrderLineInline]


@admin.register(ClientOrderLine)
class ClientOrderLineAdmin(admin.ModelAdmin):
    list_display  = ['id', 'order', 'material', 'quantity_ordered', 'quantity_fulfilled', 'status']
    list_filter   = ['status', 'material']
    search_fields = ['order__reference', 'material__name']


# ─────────────────────────────────────────────
# PRODUCTION RUNS
# ─────────────────────────────────────────────

class ProductionComponentInline(admin.TabularInline):
    model  = ProductionComponent
    extra  = 1
    fields = ['material', 'quantity_required', 'quantity_available', 'status', 'raw_material_batch', 'expected_date', 'actual_date']


class ProductionRunAllocationInline(admin.TabularInline):
    model  = ProductionRunAllocation
    extra  = 1
    fields = ['order_line', 'quantity_allocated', 'notes']


@admin.register(ProductionRun)
class ProductionRunAdmin(admin.ModelAdmin):
    list_display    = ['id', 'reference', 'material', 'status', 'planned_quantity', 'allocated_qty', 'planned_start', 'planned_end']
    list_filter     = ['status', 'material']
    search_fields   = ['reference', 'material__name']
    readonly_fields = ['id', 'created_at']
    inlines         = [ProductionComponentInline, ProductionRunAllocationInline]
    actions         = ['mark_active', 'mark_completed', 'mark_cancelled']

    @admin.display(description='Allocated')
    def allocated_qty(self, obj): return obj.allocated_quantity

    @admin.action(description='Mark selected runs as Active')
    def mark_active(self, request, qs):
        qs.update(status='ACTIVE')

    @admin.action(description='Mark selected runs as Completed')
    def mark_completed(self, request, qs):
        qs.update(status='COMPLETED', actual_end=timezone.now().date())

    @admin.action(description='Mark selected runs as Cancelled')
    def mark_cancelled(self, request, qs):
        qs.update(status='CANCELLED')


@admin.register(ProductionComponent)
class ProductionComponentAdmin(admin.ModelAdmin):
    list_display  = ['id', 'production_run', 'material', 'status', 'quantity_required', 'quantity_available', 'expected_date']
    list_filter   = ['status', 'material']
    search_fields = ['production_run__reference', 'material__name']


@admin.register(ProductionRunAllocation)
class ProductionRunAllocationAdmin(admin.ModelAdmin):
    list_display  = ['id', 'production_run', 'order_line', 'quantity_allocated', 'created_at']
    search_fields = ['production_run__reference', 'order_line__order__reference']


@admin.register(ProductionRunShipment)
class ProductionRunShipmentAdmin(admin.ModelAdmin):
    list_display  = ['id', 'production_run', 'quantity_shipped', 'order_line', 'shipped_at']
    list_filter   = ['shipped_at']
    search_fields = ['production_run__reference']
    readonly_fields = ['id', 'shipped_at']
