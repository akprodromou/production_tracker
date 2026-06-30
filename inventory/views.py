from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Prefetch, Count
from django.db.models.functions import Coalesce
from django.db.models import DecimalField
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.utils import timezone
from decimal import Decimal, InvalidOperation
import json

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ProductBatch, MaterialTransaction,
    Client, ClientOrder, ClientOrderLine,
    ProductionRun, ProductionRunAllocation,
    ProductionComponent, ProductionRunShipment,
    ProductBatchReservation, RawBatchAllocation,
    ProductionTemplate, ProductionTemplateComponent,
)
from .forms import (
    UnitForm, LocationForm, MaterialForm, RawMaterialBatchForm,
    ProductBatchForm,
    ReserveMaterialForm, ConsumeMaterialForm, ReleaseMaterialForm,
    ClientForm, ClientOrderForm, ClientOrderLineFormSet,
    ProductionRunForm, ProductionRunAllocationForm,
    ProductionComponentForm, ProductionComponentFormSet,
)
from .services import reserve_material, consume_material, release_material


def _deletion_blocked_msg(exc):
    """
    Converts a Django ProtectedError into a readable message
    listing exactly which related objects are blocking deletion.
    """
    from django.db.models.deletion import ProtectedError
    if isinstance(exc, ProtectedError):
        blocked = exc.protected_objects
        # Group by model name
        by_model = {}
        for obj in blocked:
            name = obj.__class__.__name__
            by_model.setdefault(name, []).append(str(obj))
        parts = []
        for model_name, objs in by_model.items():
            sample = ', '.join(objs[:3])
            if len(objs) > 3:
                sample += f' … and {len(objs) - 3} more'
            parts.append(f'{model_name}: {sample}')
        return 'Cannot delete — referenced by: ' + ' | '.join(parts)
    return f'Cannot delete: {exc}'



# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

class DashboardView(View):
    def get(self, request):
        all_batches = list(RawMaterialBatch.objects.select_related('material', 'location'))
        low_stock = sorted(
            [b for b in all_batches
             if b.available_quantity < Decimal('1000')],
            key=lambda b: b.available_quantity
        )[:8]

        return render(request, 'dashboard.html', {
            'total_materials':        Material.objects.count(),
            'raw_materials':          Material.objects.filter(category__in=['RAW', 'PKG']).count(),
            'finished_materials':     Material.objects.filter(category='FIN').count(),
            'active_batches':         RawMaterialBatch.objects.count(),
            'open_orders':            ClientOrder.objects.exclude(
                                          status__in=['FULFILLED', 'CANCELLED']
                                      ).count(),
            'active_production_runs': ProductionRun.objects.filter(
                                          status__in=['PLANNED', 'ACTIVE']
                                      ).count(),
            'low_stock_batches':      low_stock,
            'recent_transactions':    MaterialTransaction.objects.select_related(
                                          'raw_material_batch__material', 'product_batch'
                                      ).order_by('-created_at')[:8],
            'recent_orders':          ClientOrder.objects.select_related(
                                          'client'
                                      ).order_by('-created_at')[:6],
            'recent_product_batches': ProductBatch.objects.select_related(
                                          'material', 'location'
                                      ).order_by('-created_at')[:6],
            'low_product_batches':    ProductBatch.objects.select_related(
                                          'material__unit', 'location'
                                      ).filter(
                                          quantity_produced__lt=1000
                                      ).order_by('quantity_produced')[:8],
        })


# ─────────────────────────────────────────────
# UNITS
# ─────────────────────────────────────────────

class UnitListView(View):
    def get(self, request):
        return render(request, 'units/list.html', {
            'units': Unit.objects.all().order_by('name')
        })


class UnitCreateView(View):
    def get(self, request):
        return render(request, 'units/form.html', {
            'form': UnitForm(), 'form_title': 'New Unit', 'submit_label': 'Create Unit'
        })

    def post(self, request):
        form = UnitForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Unit created.')
            return redirect('unit-list')
        return render(request, 'units/form.html', {
            'form': form, 'form_title': 'New Unit', 'submit_label': 'Create Unit'
        })


class UnitEditView(View):
    def get(self, request, pk):
        unit = get_object_or_404(Unit, pk=pk)
        return render(request, 'units/form.html', {
            'form': UnitForm(instance=unit),
            'form_title': f'Edit Unit: {unit.name}', 'submit_label': 'Save Changes'
        })

    def post(self, request, pk):
        unit = get_object_or_404(Unit, pk=pk)
        form = UnitForm(request.POST, instance=unit)
        if form.is_valid():
            form.save()
            messages.success(request, 'Unit updated.')
            return redirect('unit-list')
        return render(request, 'units/form.html', {
            'form': form, 'form_title': f'Edit Unit: {unit.name}', 'submit_label': 'Save Changes'
        })


class UnitDeleteView(View):
    def post(self, request, pk):
        unit = get_object_or_404(Unit, pk=pk)
        try:
            unit.delete()
            messages.success(request, f'Unit "{unit.name}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete "{unit.name}" — it is in use.')
        return redirect('unit-list')


# ─────────────────────────────────────────────
# LOCATIONS
# ─────────────────────────────────────────────

class LocationListView(View):
    def get(self, request):
        qs = Location.objects.all().order_by('name')
        is_external = request.GET.get('is_external')
        if is_external == 'true':
            qs = qs.filter(is_external=True)
        elif is_external == 'false':
            qs = qs.filter(is_external=False)
        return render(request, 'locations/list.html', {'locations': qs})


class LocationDetailView(View):
    """Shows all raw material batches and product batches stored at this location."""
    def get(self, request, pk):
        location = get_object_or_404(Location, pk=pk)
        raw_batches = RawMaterialBatch.objects.filter(
            location=location
        ).select_related('material__unit').order_by('-created_at')
        product_batches = ProductBatch.objects.filter(
            location=location
        ).select_related('material__unit').order_by('-created_at')
        return render(request, 'locations/detail.html', {
            'location':      location,
            'raw_batches':   raw_batches,
            'product_batches': product_batches,
        })


class LocationCreateView(View):
    def get(self, request):
        return render(request, 'locations/form.html', {
            'form': LocationForm(), 'form_title': 'New Location', 'submit_label': 'Create Location'
        })

    def post(self, request):
        form = LocationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Location created.')
            return redirect('location-list')
        return render(request, 'locations/form.html', {
            'form': form, 'form_title': 'New Location', 'submit_label': 'Create Location'
        })


class LocationEditView(View):
    def get(self, request, pk):
        loc = get_object_or_404(Location, pk=pk)
        return render(request, 'locations/form.html', {
            'form': LocationForm(instance=loc),
            'form_title': f'Edit: {loc.name}', 'submit_label': 'Save Changes'
        })

    def post(self, request, pk):
        loc = get_object_or_404(Location, pk=pk)
        form = LocationForm(request.POST, instance=loc)
        if form.is_valid():
            form.save()
            messages.success(request, 'Location updated.')
            return redirect('location-list')
        return render(request, 'locations/form.html', {
            'form': form, 'form_title': f'Edit: {loc.name}', 'submit_label': 'Save Changes'
        })


class LocationDeleteView(View):
    def post(self, request, pk):
        loc = get_object_or_404(Location, pk=pk)
        try:
            loc.delete()
            messages.success(request, f'Location "{loc.name}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete "{loc.name}" — it is in use.')
        return redirect('location-list')


# ─────────────────────────────────────────────
# MATERIALS
# ─────────────────────────────────────────────

class MaterialListView(View):
    def get(self, request):
        qs = Material.objects.select_related('unit').all()
        category = request.GET.get('category')
        q = request.GET.get('q', '').strip()
        if category:
            qs = qs.filter(category=category)
        if q:
            # Split query into words — each word must appear in name or sku
            # e.g. "KR 50ml" matches "KR EVOO 50ml original"
            terms = q.split()
            for term in terms:
                qs = qs.filter(Q(name__icontains=term) | Q(sku__icontains=term))
        paginator = Paginator(qs.order_by('name'), 25)
        return render(request, 'materials/list.html', {
            'materials':        paginator.get_page(request.GET.get('page')),
            'category_choices': Material.CATEGORY_CHOICES,
        })


class MaterialDetailView(View):
    def get(self, request, pk):
        m = get_object_or_404(Material.objects.select_related('unit'), pk=pk)
        # For finished products: show production runs with component breakdown
        runs = []
        if m.category == 'FIN':
            runs = ProductionRun.objects.filter(
                material=m
            ).prefetch_related(
                Prefetch('components', queryset=ProductionComponent.objects.select_related('material'))
            ).exclude(status='CANCELLED').order_by('-created_at')
        from django.db.models import Sum as _Sum
        material = m
        raw_batches  = list(RawMaterialBatch.objects.filter(material=m).select_related('location')) if m.category in ('RAW', 'PKG') else []
        prod_batches = list(ProductBatch.objects.filter(material=m).select_related('location')) if m.category == 'FIN' else []

        if m.category in ('RAW', 'PKG'):
            total_qty = sum(b.total_quantity for b in raw_batches) or Decimal('0')
            from inventory.models import RawBatchAllocation as RBA
            allocated = RBA.objects.filter(
                raw_batch__material=m
            ).aggregate(t=_Sum('quantity'))['t'] or Decimal('0')
            net_available = total_qty - allocated
            stock_summary = {
                'total': total_qty, 'allocated': allocated,
                'net_available': net_available, 'type': 'raw',
            }
        elif m.category == 'FIN':
            total_qty = sum(b.quantity_produced for b in prod_batches) or Decimal('0')
            from inventory.models import ProductBatchReservation as PBR
            reserved = PBR.objects.filter(
                product_batch__material=m
            ).aggregate(t=_Sum('quantity_reserved'))['t'] or Decimal('0')
            net_available = total_qty - reserved
            stock_summary = {
                'total': total_qty, 'reserved': reserved,
                'net_available': net_available, 'type': 'fin',
            }
        else:
            stock_summary = None

        return render(request, 'materials/detail.html', {
            'material':      m,
            'raw_batches':   raw_batches,
            'product_batches': prod_batches,
            'stock_summary': stock_summary,
        })


class MaterialCreateView(View):
    def get(self, request):
        return render(request, 'materials/form.html', {
            'form': MaterialForm(), 'form_title': 'New Material', 'submit_label': 'Create Material'
        })

    def post(self, request):
        form = MaterialForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Material created.')
            return redirect('material-list')
        return render(request, 'materials/form.html', {
            'form': form, 'form_title': 'New Material', 'submit_label': 'Create Material'
        })


class MaterialEditView(View):
    def get(self, request, pk):
        m = get_object_or_404(Material, pk=pk)
        return render(request, 'materials/form.html', {
            'form': MaterialForm(instance=m),
            'form_title': f'Edit: {m.name}', 'submit_label': 'Save Changes'
        })

    def post(self, request, pk):
        m = get_object_or_404(Material, pk=pk)
        form = MaterialForm(request.POST, instance=m)
        if form.is_valid():
            form.save()
            messages.success(request, 'Material updated.')
            return redirect('material-detail', pk=m.pk)
        return render(request, 'materials/form.html', {
            'form': form, 'form_title': f'Edit: {m.name}', 'submit_label': 'Save Changes'
        })


class MaterialDeleteView(View):
    def post(self, request, pk):
        m = get_object_or_404(Material, pk=pk)
        name = m.name
        try:
            m.delete()
            messages.success(request, f'Material "{name}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete "{name}" — it is in use.')
        return redirect('material-list')


# ─────────────────────────────────────────────
# RAW MATERIAL BATCHES
# ─────────────────────────────────────────────

class RawMaterialBatchListView(View):
    def get(self, request):
        qs = RawMaterialBatch.objects.select_related('material', 'location').all()
        material_id = request.GET.get('material_id', '').strip()
        location_id = request.GET.get('location_id', '').strip()
        q = request.GET.get('q', '').strip()
        if material_id:
            try:
                qs = qs.filter(material_id=int(material_id))
            except (ValueError, TypeError):
                pass
        if location_id:
            try:
                qs = qs.filter(location_id=int(location_id))
            except (ValueError, TypeError):
                pass
        if q:
            terms = q.split()
            for term in terms:
                qs = qs.filter(
                    Q(lot_number__icontains=term) |
                    Q(material__sku__icontains=term) |
                    Q(material__name__icontains=term)
                )
        from django.db.models import F
        qs = qs.annotate(
            total_allocated=Coalesce(
                Sum('allocations__quantity'), Decimal('0'), output_field=DecimalField()
            )
        ).annotate(
            computed_available=F('total_quantity') - Coalesce(
                Sum('allocations__quantity'), Decimal('0'), output_field=DecimalField()
            )
        )
        sort      = request.GET.get('sort', 'date')
        direction = request.GET.get('dir', 'desc')
        sort_map  = {
            'lot_number': 'lot_number',
            'material':   'material__name',
            'sku':        'material__sku',
            'location':   'location__name',
            'status':     'status',
            'total':      'total_quantity',
            'allocated':  'total_allocated',
            'available':  'total_quantity',
            'date':       'created_at',
        }
        sort_field = sort_map.get(sort, 'created_at')
        order      = sort_field if direction == 'asc' else f'-{sort_field}'
        paginator  = Paginator(qs.order_by(order), 25)
        return render(request, 'batches/list.html', {
            'batches':       paginator.get_page(request.GET.get('page')),
            'all_materials': Material.objects.filter(category__in=['RAW', 'PKG']).order_by('name'),
            'all_locations': Location.objects.order_by('name'),
            'current_sort':  sort,
            'current_dir':   direction,
            'cols': [
                ('lot_number', 'Lot Number'),
                ('material',   'Material'),
                ('sku',        'SKU'),
                ('location',   'Location'),
                ('total',      'Total'),
                ('available',  'Available'),
                ('allocated',  'Allocated to Runs'),
            ],
        })


class RawMaterialBatchDetailView(View):
    def get(self, request, pk):
        batch = get_object_or_404(
            RawMaterialBatch.objects.select_related('material', 'location'), pk=pk
        )
        # Production runs that contain this material as a component
        # Annotate with quantity_required for this material and already allocated
        from django.db.models import OuterRef, Subquery
        eligible_runs_qs = ProductionRun.objects.filter(
            components__material=batch.material,
            status__in=['PLANNED', 'ACTIVE']
        ).select_related('material').distinct().order_by('-created_at')

        # Build enriched run info with needed qty and already allocated qty
        eligible_runs = []
        for run in eligible_runs_qs:
            comp = run.components.filter(material=batch.material).first()
            qty_required = comp.quantity_required if comp else 0
            already_allocated = RawBatchAllocation.objects.filter(
                production_run=run,
                raw_batch__material=batch.material
            ).aggregate(
                total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
            )['total']
            still_needed = max(Decimal('0'), qty_required - already_allocated)
            eligible_runs.append({
                'run':           run,
                'qty_required':  qty_required,
                'still_needed':  still_needed,
            })

        # Existing allocations for this batch
        allocations = RawBatchAllocation.objects.filter(
            raw_batch=batch
        ).select_related('production_run__material')

        total_allocated = sum(a.quantity for a in allocations)
        available       = batch.total_quantity - total_allocated

        return render(request, 'batches/detail.html', {
            'batch':          batch,
            'transactions':   MaterialTransaction.objects.filter(
                                  raw_material_batch=batch
                              ).select_related('product_batch').order_by('-created_at'),
            'eligible_runs':  eligible_runs,
            'allocations':    allocations,
            'total_allocated': total_allocated,
            'available':      available,
        })

    def post(self, request, pk):
        batch  = get_object_or_404(RawMaterialBatch, pk=pk)
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in dict(RawMaterialBatch.STATUS_CHOICES):
                batch.status = new_status
                batch.save()
                messages.success(request, f'Status updated to {batch.get_status_display()}.')

        elif action == 'allocate':
            run_id  = request.POST.get('production_run_id')
            qty_str = request.POST.get('quantity', '').strip()
            try:
                run = ProductionRun.objects.get(pk=int(run_id))
                qty = Decimal(qty_str)
                if qty <= 0:
                    raise ValueError

                # Check available quantity
                total_allocated = RawBatchAllocation.objects.filter(
                    raw_batch=batch
                ).aggregate(
                    total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
                )['total']
                available = batch.total_quantity - total_allocated

                if qty > available:
                    messages.error(request, f'Only {available} units available.')
                elif not run.components.filter(material=batch.material).exists():
                    messages.error(
                        request,
                        f'{run.reference} does not contain {batch.material.name} as a component.'
                    )
                else:
                    # Check how much is still needed for this run
                    comp = run.components.filter(material=batch.material).first()
                    qty_required = comp.quantity_required if comp else Decimal('0')
                    already_allocated = RawBatchAllocation.objects.filter(
                        production_run=run,
                        raw_batch__material=batch.material
                    ).aggregate(
                        total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
                    )['total']
                    still_needed = max(Decimal('0'), qty_required - already_allocated)
                    if qty > still_needed:
                        messages.error(
                            request,
                            f'{run.reference} only needs {still_needed} more units of {batch.material.name}.'
                        )
                    else:
                        RawBatchAllocation.objects.create(
                            raw_batch=batch,
                            production_run=run,
                            quantity=qty,
                            notes=request.POST.get('notes', ''),
                        )
                        messages.success(
                            request,
                            f'Allocated {qty} units to {run.reference}.'
                        )
            except (ProductionRun.DoesNotExist, ValueError, InvalidOperation):
                messages.error(request, 'Invalid run or quantity.')

        elif action == 'edit_allocation':
            alloc_id = request.POST.get('allocation_id')
            qty_str  = request.POST.get('quantity', '').strip()
            try:
                alloc = RawBatchAllocation.objects.get(pk=alloc_id, raw_batch=batch)
                qty   = Decimal(qty_str)
                if qty <= 0:
                    raise ValueError
                # Check available (excluding this allocation's current quantity)
                total_allocated = RawBatchAllocation.objects.filter(
                    raw_batch=batch
                ).exclude(pk=alloc.pk).aggregate(
                    total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField())
                )['total']
                available = batch.total_quantity - total_allocated
                if qty > available:
                    messages.error(request, f'Only {available} units available.')
                else:
                    alloc.quantity = qty
                    alloc.save()
                    messages.success(request, f'Allocation updated to {qty}.')
            except (RawBatchAllocation.DoesNotExist, ValueError, InvalidOperation):
                messages.error(request, 'Invalid allocation or quantity.')

        elif action == 'remove_allocation':
            alloc_id = request.POST.get('allocation_id')
            try:
                alloc = RawBatchAllocation.objects.get(pk=alloc_id, raw_batch=batch)
                run_ref = alloc.production_run.reference
                alloc.delete()
                messages.success(request, f'Allocation to {run_ref} removed.')
            except RawBatchAllocation.DoesNotExist:
                messages.error(request, 'Allocation not found.')

        return redirect('batch-detail', pk=pk)


class RawMaterialBatchCreateView(View):
    def get(self, request):
        form = RawMaterialBatchForm()
        if request.GET.get('material'):
            form.initial['material'] = request.GET['material']
        raw_mats = list(Material.objects.filter(
            category__in=['RAW', 'PKG']
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'batches/form.html', {
            'form': form,
            'form_title': 'New Raw Material Batch',
            'submit_label': 'Create Batch',
            'raw_materials_json': json.dumps(raw_mats),
        })

    def post(self, request):
        form = RawMaterialBatchForm(request.POST)
        if form.is_valid():
            batch = form.save()
            MaterialTransaction.objects.create(
                raw_material_batch=batch,
                transaction_type='PRODUCED',
                quantity=batch.total_quantity,
            )
            messages.success(request, f'Batch {batch.lot_number} created.')
            return redirect('batch-detail', pk=batch.pk)
        raw_mats = list(Material.objects.filter(
            category__in=['RAW', 'PKG']
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'batches/form.html', {
            'form': form,
            'form_title': 'New Raw Material Batch',
            'submit_label': 'Create Batch',
            'raw_materials_json': json.dumps(raw_mats),
        })



class RawMaterialBatchEditView(View):
    def get(self, request, pk):
        batch = get_object_or_404(RawMaterialBatch, pk=pk)
        form  = RawMaterialBatchForm(instance=batch)
        return render(request, 'batches/form.html', {
            'form':         form,
            'form_title':   f'Edit Batch: {batch.lot_number}',
            'submit_label': 'Save Changes',
            'batch':        batch,
        })

    def post(self, request, pk):
        batch = get_object_or_404(RawMaterialBatch, pk=pk)
        form  = RawMaterialBatchForm(request.POST, instance=batch)
        if form.is_valid():
            form.save()
            messages.success(request, f'Batch {batch.lot_number} updated.')
            return redirect('batch-detail', pk=pk)
        return render(request, 'batches/form.html', {
            'form':         form,
            'form_title':   f'Edit Batch: {batch.lot_number}',
            'submit_label': 'Save Changes',
            'batch':        batch,
        })


class RawMaterialBatchDeleteView(View):
    def post(self, request, pk):
        batch = get_object_or_404(RawMaterialBatch, pk=pk)
        lot = batch.lot_number
        try:
            batch.delete()
            messages.success(request, f'Batch "{lot}" deleted.')
        except Exception as e:
            messages.error(request, _deletion_blocked_msg(e))
        return redirect('batch-list')


# ─────────────────────────────────────────────
# PRODUCT BATCHES
# ─────────────────────────────────────────────

class ProductBatchListView(View):
    def get(self, request):
        qs = ProductBatch.objects.select_related('material', 'location').all()
        material_id = request.GET.get('material_id', '').strip()
        location_id = request.GET.get('location_id', '').strip()
        q = request.GET.get('q', '').strip()
        if material_id:
            try:
                qs = qs.filter(material_id=int(material_id))
            except (ValueError, TypeError):
                pass
        if location_id:
            try:
                qs = qs.filter(location_id=int(location_id))
            except (ValueError, TypeError):
                pass
        if q:
            terms = q.split()
            for term in terms:
                qs = qs.filter(
                    Q(batch_number__icontains=term) |
                    Q(material__sku__icontains=term) |
                    Q(material__name__icontains=term)
                )
        sort      = request.GET.get('sort', 'date')
        direction = request.GET.get('dir', 'desc')
        sort_map  = {
            'batch_number': 'batch_number',
            'material':     'material__name',
            'sku':          'material__sku',
            'location':     'location__name',
            'quantity':     'quantity_produced',
            'date':         'created_at',
        }
        sort_field = sort_map.get(sort, 'created_at')
        order      = sort_field if direction == 'asc' else f'-{sort_field}'
        paginator  = Paginator(qs.order_by(order), 25)
        return render(request, 'product_batches/list.html', {
            'batches':       paginator.get_page(request.GET.get('page')),
            'all_materials': Material.objects.filter(category='FIN').order_by('name'),
            'all_locations': Location.objects.order_by('name'),
            'current_sort':  sort,
            'current_dir':   direction,
            'cols': [
                ('batch_number', 'Batch Number'),
                ('material',     'Product'),
                ('sku',          'SKU'),
                ('location',     'Location'),
                ('quantity',     'Qty Produced'),
                ('date',         'Date'),
            ],
        })


class ProductBatchDetailView(View):
    def get(self, request, pk):
        batch = get_object_or_404(
            ProductBatch.objects.select_related('material', 'location'), pk=pk
        )
        transactions = MaterialTransaction.objects.filter(
            product_batch=batch
        ).select_related('raw_material_batch__material').order_by('-created_at')
        summary = {}
        for tx in transactions:
            rb = tx.raw_material_batch
            if rb.pk not in summary:
                summary[rb.pk] = {'batch': rb, 'reserved': Decimal('0'), 'consumed': Decimal('0')}
            if tx.transaction_type == 'RESERVED':
                summary[rb.pk]['reserved'] += tx.quantity
            elif tx.transaction_type == 'CONSUMED':
                summary[rb.pk]['consumed'] += tx.quantity

        reservations = ProductBatchReservation.objects.filter(
            product_batch=batch
        ).select_related('order_line__order__client', 'order_line__material')

        total_reserved = sum(r.quantity_reserved for r in reservations)
        available      = batch.quantity_produced - total_reserved

        # Order lines eligible for reservation (FIN material matches batch material)
        eligible_lines = ClientOrderLine.objects.filter(
            material=batch.material
        ).exclude(status='FULFILLED').select_related('order__client')

        return render(request, 'product_batches/detail.html', {
            'batch':               batch,
            'transactions':        transactions,
            'consumption_summary': list(summary.values()),
            'reservations':        reservations,
            'total_reserved':      total_reserved,
            'available':           available,
            'eligible_lines':      eligible_lines,
        })

    def post(self, request, pk):
        batch  = get_object_or_404(ProductBatch, pk=pk)
        action = request.POST.get('action')

        if action == 'reserve':
            line_id  = request.POST.get('order_line_id')
            qty_str  = request.POST.get('quantity_reserved', '').strip()
            try:
                line = ClientOrderLine.objects.get(pk=line_id)
                qty  = Decimal(qty_str)
                if qty <= 0:
                    raise ValueError
                # Check available
                existing = ProductBatchReservation.objects.filter(
                    product_batch=batch
                ).aggregate(
                    total=Coalesce(Sum('quantity_reserved'), Decimal('0'), output_field=DecimalField())
                )['total']
                available = batch.quantity_produced - existing
                if qty > available:
                    messages.error(request, f'Only {available} units available.')
                else:
                    ProductBatchReservation.objects.create(
                        product_batch=batch,
                        order_line=line,
                        quantity_reserved=qty,
                        notes=request.POST.get('notes', ''),
                    )
                    # Update order line fulfilled quantity and status
                    line.quantity_fulfilled = (line.quantity_fulfilled or Decimal('0')) + qty
                    if line.quantity_fulfilled >= line.quantity_ordered:
                        line.status = 'FULFILLED'
                    else:
                        line.status = 'PARTIAL'
                    line.save()
                    messages.success(request, f'Reserved {qty} units for {line.order.reference}.')
            except (ClientOrderLine.DoesNotExist, ValueError, InvalidOperation):
                messages.error(request, 'Invalid order line or quantity.')

        elif action == 'delete_reservation':
            res_id = request.POST.get('reservation_id')
            try:
                res = ProductBatchReservation.objects.get(pk=res_id, product_batch=batch)
                line = res.order_line
                qty  = res.quantity_reserved
                res.delete()
                # Reverse the fulfilled quantity
                line.quantity_fulfilled = max(Decimal('0'), (line.quantity_fulfilled or Decimal('0')) - qty)
                if line.quantity_fulfilled == 0:
                    line.status = 'PENDING'
                elif line.quantity_fulfilled < line.quantity_ordered:
                    line.status = 'PARTIAL'
                line.save()
                messages.success(request, 'Reservation removed.')
            except ProductBatchReservation.DoesNotExist:
                messages.error(request, 'Reservation not found.')

        return redirect('product-batch-detail', pk=pk)


class ProductBatchCreateView(View):
    def get(self, request):
        form = ProductBatchForm()
        if request.GET.get('material'):
            form.initial['material'] = request.GET['material']
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'product_batches/form.html', {
            'form': form,
            'form_title': 'New Product Batch',
            'submit_label': 'Create Batch',
            'fin_materials_json': json.dumps(fin_mats),
        })

    def post(self, request):
        form = ProductBatchForm(request.POST)
        if form.is_valid():
            pb = form.save()
            messages.success(request, f'Product batch {pb.batch_number} created.')
            return redirect('product-batch-detail', pk=pb.pk)
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'product_batches/form.html', {
            'form': form,
            'form_title': 'New Product Batch',
            'submit_label': 'Create Batch',
            'fin_materials_json': json.dumps(fin_mats),
        })



class ProductBatchEditView(View):
    def get(self, request, pk):
        batch = get_object_or_404(ProductBatch.objects.select_related('material__unit', 'location', 'production_run__material__unit'), pk=pk)
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        form = ProductBatchForm(instance=batch)
        return render(request, 'product_batches/form.html', {
            'form':               form,
            'form_title':         f'Edit Batch: {batch.batch_number}',
            'submit_label':       'Save Changes',
            'batch':              batch,
            'fin_materials_json': json.dumps(fin_mats),
        })

    def post(self, request, pk):
        batch = get_object_or_404(ProductBatch.objects.select_related('material__unit', 'location', 'production_run__material__unit'), pk=pk)
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        form = ProductBatchForm(request.POST, instance=batch)
        if form.is_valid():
            form.save()
            messages.success(request, f'Batch {batch.batch_number} updated.')
            return redirect('product-batch-detail', pk=pk)
        return render(request, 'product_batches/form.html', {
            'form':               form,
            'form_title':         f'Edit Batch: {batch.batch_number}',
            'submit_label':       'Save Changes',
            'batch':              batch,
            'fin_materials_json': json.dumps(fin_mats),
        })


class ProductBatchDeleteView(View):
    def post(self, request, pk):
        pb = get_object_or_404(ProductBatch, pk=pk)
        bn = pb.batch_number
        try:
            pb.delete()
            messages.success(request, f'Product batch "{bn}" deleted.')
        except Exception as e:
            messages.error(request, _deletion_blocked_msg(e))
        return redirect('product-batch-list')


# ─────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────

class MaterialTransactionListView(View):
    def get(self, request):
        qs = MaterialTransaction.objects.select_related(
            'raw_material_batch__material', 'product_batch__material'
        ).order_by('-created_at')
        batch_id         = request.GET.get('batch_id', '').strip()
        product_batch_id = request.GET.get('product_batch_id', '').strip()
        tx_type          = request.GET.get('transaction_type', '').strip()
        reference        = request.GET.get('reference', '').strip()
        if batch_id:
            qs = qs.filter(raw_material_batch_id=batch_id)
        if product_batch_id:
            qs = qs.filter(product_batch_id=product_batch_id)
        if tx_type:
            qs = qs.filter(transaction_type=tx_type.upper())
        if reference:
            qs = qs.filter(reference__icontains=reference)
        summary = qs.values('transaction_type').annotate(total=Sum('quantity'))
        summary_map = {s['transaction_type']: s['total'] for s in summary}
        paginator = Paginator(qs, 50)
        return render(request, 'transactions/list.html', {
            'transactions':        paginator.get_page(request.GET.get('page')),
            'summary': {
                'produced': summary_map.get('PRODUCED', 0),
                'reserved': summary_map.get('RESERVED', 0),
                'consumed': summary_map.get('CONSUMED', 0),
                'released': summary_map.get('RELEASED', 0),
            },
            'all_batches':         RawMaterialBatch.objects.select_related('material').order_by('-created_at'),
            'all_product_batches': ProductBatch.objects.select_related('material').order_by('-created_at'),
        })


# ─────────────────────────────────────────────
# SERVICE ACTIONS  (reserve / consume / release)
# ─────────────────────────────────────────────

class ReserveMaterialView(View):
    def post(self, request):
        form = ReserveMaterialForm(request.POST)
        if form.is_valid():
            try:
                order_id  = request.POST.get('order_id', '').strip()
                reference = f'ORDER-{order_id}' if order_id else ''
                reserve_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
                    reference=reference,
                )
                messages.success(request, f"Reserved {form.cleaned_data['quantity']} units.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
        batch_id = request.POST.get('batch_id')
        return redirect('batch-detail', pk=batch_id) if batch_id else redirect('batch-list')


class ConsumeMaterialView(View):
    def post(self, request):
        form = ConsumeMaterialForm(request.POST)
        if form.is_valid():
            try:
                order_id  = request.POST.get('order_id', '').strip()
                reference = f'ORDER-{order_id}' if order_id else ''
                consume_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
                    reference=reference,
                )
                messages.success(request, f"Consumed {form.cleaned_data['quantity']} units.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
        batch_id = request.POST.get('batch_id')
        return redirect('batch-detail', pk=batch_id) if batch_id else redirect('batch-list')


class ReleaseMaterialView(View):
    def post(self, request):
        form = ReleaseMaterialForm(request.POST)
        if form.is_valid():
            try:
                order_id  = request.POST.get('order_id', '').strip()
                reference = f'ORDER-{order_id}' if order_id else ''
                release_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
                    reference=reference,
                )
                messages.success(request, f"Released {form.cleaned_data['quantity']} units.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
        batch_id = request.POST.get('batch_id')
        return redirect('batch-detail', pk=batch_id) if batch_id else redirect('batch-list')


# ─────────────────────────────────────────────
# CLIENTS
# ─────────────────────────────────────────────

class ClientListView(View):
    def get(self, request):
        qs = Client.objects.all()
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(name__icontains=q)
        paginator = Paginator(qs.order_by('name'), 25)
        return render(request, 'client_orders/client_list.html', {
            'clients': paginator.get_page(request.GET.get('page'))
        })


class ClientDetailView(View):
    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        orders = ClientOrder.objects.filter(client=client).prefetch_related('lines').order_by('-order_date')
        return render(request, 'client_orders/client_detail.html', {
            'client': client,
            'orders': orders,
        })


class ClientCreateView(View):
    def get(self, request):
        return render(request, 'client_orders/client_form.html', {
            'form': ClientForm(), 'form_title': 'New Client', 'submit_label': 'Create Client'
        })

    def post(self, request):
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            messages.success(request, f'Client "{client.name}" created.')
            return redirect('client-list')
        return render(request, 'client_orders/client_form.html', {
            'form': form, 'form_title': 'New Client', 'submit_label': 'Create Client'
        })


class ClientEditView(View):
    def get(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        return render(request, 'client_orders/client_form.html', {
            'form': ClientForm(instance=client),
            'form_title': f'Edit: {client.name}', 'submit_label': 'Save Changes'
        })

    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            form.save()
            messages.success(request, 'Client updated.')
            return redirect('client-list')
        return render(request, 'client_orders/client_form.html', {
            'form': form, 'form_title': f'Edit: {client.name}', 'submit_label': 'Save Changes'
        })


class ClientDeleteView(View):
    def post(self, request, pk):
        client = get_object_or_404(Client, pk=pk)
        name = client.name
        try:
            client.delete()
            messages.success(request, f'Client "{name}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete "{name}" — they have existing orders.')
        return redirect('client-list')


# ─────────────────────────────────────────────
# CLIENT ORDERS
# ─────────────────────────────────────────────

class ClientOrderListView(View):
    def get(self, request):
        qs = ClientOrder.objects.select_related('client').all()
        status  = request.GET.get('status')
        client  = request.GET.get('client_id', '').strip()
        q       = request.GET.get('q', '').strip()
        if status:
            qs = qs.filter(status=status)
        if client:
            try:
                qs = qs.filter(client_id=int(client))
            except (ValueError, TypeError):
                pass
        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(client__name__icontains=q))
        paginator = Paginator(qs.order_by('-order_date'), 25)
        return render(request, 'client_orders/order_list.html', {
            'orders':         paginator.get_page(request.GET.get('page')),
            'all_clients':    Client.objects.order_by('name'),
            'status_choices': ClientOrder.STATUS_CHOICES,
        })


class ClientOrderDetailView(View):
    def get(self, request, pk):
        order = get_object_or_404(
            ClientOrder.objects.select_related('client').prefetch_related(
                Prefetch('lines', queryset=ClientOrderLine.objects.select_related('material__unit').prefetch_related(
                    Prefetch('batch_reservations', queryset=ProductBatchReservation.objects.select_related('product_batch'))
                ))
            ), pk=pk
        )
        # Compute available quantity for every product batch
        from django.db.models import Sum as _Sum
        pb_reserved = {
            r['product_batch_id']: r['total']
            for r in ProductBatchReservation.objects.values('product_batch_id').annotate(total=_Sum('quantity_reserved'))
        }
        pb_available = {}
        for pb in ProductBatch.objects.all():
            reserved = pb_reserved.get(pb.pk, Decimal('0'))
            pb_available[pb.pk] = pb.quantity_produced - reserved

        import json as _json
        pb_available_json = _json.dumps({str(k): float(v) for k, v in pb_available.items()})

        # Bill of Quantities — sourced from product batches reserved against this order
        from collections import defaultdict
        # Step 1: find all product batches reserved against this order's lines
        reserved_batch_ids = ProductBatchReservation.objects.filter(
            order_line__order=order
        ).values_list('product_batch_id', flat=True).distinct()

        # Step 2: find production runs linked to those batches
        run_ids = ProductionRun.objects.filter(
            product_batch_id__in=reserved_batch_ids
        ).values_list('id', flat=True).distinct()

        boq = defaultdict(lambda: {
            'material': None,
            'required': Decimal('0'),
            'statuses': set(),
        })
        components = ProductionComponent.objects.filter(
            production_run_id__in=run_ids
        ).select_related('material__unit')
        for comp in components:
            m = comp.material
            boq[m.pk]['material']  = m
            boq[m.pk]['required'] += comp.quantity_required
            boq[m.pk]['statuses'].add(comp.status)
        STATUS_PRIORITY = [
            'PENDING', 'ORDERED', 'IN_WAREHOUSE_RAW', 'IN_PROCESS', 'FINAL_PRODUCT'
        ]
        boq_rows = []
        for entry in boq.values():
            m = entry['material']
            batches = RawMaterialBatch.objects.filter(material=m)
            total_available = sum(b.available_quantity for b in batches)
            total_reserved  = sum(b.reserved_quantity  for b in batches)
            gap = entry['required'] - total_available
            worst = min(
                entry['statuses'],
                key=lambda s: STATUS_PRIORITY.index(s) if s in STATUS_PRIORITY else 0
            ) if entry['statuses'] else 'PENDING'
            boq_rows.append({
                'material':  m,
                'required':  entry['required'],
                'available': total_available,
                'reserved':  total_reserved,
                'gap':       gap,
                'status':    worst,
            })

        boq_rows.sort(key=lambda r: (
            STATUS_PRIORITY.index(r['status']) if r['status'] in STATUS_PRIORITY else 0,
            r['material'].name
        ))

        # Derive fulfilment status from order lines (worst-case)
        lines = list(order.lines.all())
        if not lines:
            fulfilment_status = None
        else:
            priority = ['PENDING', 'PARTIAL', 'FULFILLED']
            line_statuses = []
            for line in lines:
                if line.status in ('PENDING', 'ALLOCATED'):
                    line_statuses.append('PENDING')
                elif line.status == 'PARTIAL':
                    line_statuses.append('PARTIAL')
                elif line.status == 'FULFILLED':
                    line_statuses.append('FULFILLED')
                else:
                    line_statuses.append('PENDING')
            fulfilment_status = min(
                line_statuses,
                key=lambda s: priority.index(s) if s in priority else 0
            )

        return render(request, 'client_orders/order_detail.html', {
            'order':             order,
            'boq_rows':          boq_rows,
            'fulfilment_status': fulfilment_status,
            'pb_available':      pb_available,
            'pb_available_json': pb_available_json,
        })

    def post(self, request, pk):
        order  = get_object_or_404(ClientOrder, pk=pk)
        action = request.POST.get('action', 'status')

        if action == 'ship':
            # Deduct reserved quantities from product batches and delete reservations
            reservations = ProductBatchReservation.objects.filter(
                order_line__order=order
            ).select_related('product_batch')

            deducted = {}
            for res in reservations:
                pb  = res.product_batch
                qty = res.quantity_reserved
                pb.quantity_produced = max(Decimal('0'), pb.quantity_produced - qty)
                pb.save()
                deducted[pb.batch_number] = deducted.get(pb.batch_number, Decimal('0')) + qty

            reservations.delete()

            # Mark all order lines as fulfilled
            order.lines.all().update(status='FULFILLED')

            order.status = 'SHIPPED'
            order.save()

            summary = ', '.join(f'{b}: -{q}' for b, q in deducted.items())
            messages.success(
                request,
                f'Order {order.reference} shipped. Stock deducted: {summary or "none"}.'
            )

        elif action == 'status':
            new_status = request.POST.get('status')
            if new_status in dict(ClientOrder.STATUS_CHOICES):
                order.status = new_status
                order.save()
                messages.success(request, f'Order status updated to {order.get_status_display()}.')

        elif action == 'reserve_batch':
            line_id    = request.POST.get('line_id')
            batch_id   = request.POST.get('product_batch_id')
            qty_str    = request.POST.get('quantity_reserved', '').strip()
            try:
                line  = ClientOrderLine.objects.get(pk=line_id, order=order)
                batch = ProductBatch.objects.get(pk=batch_id)
                qty   = Decimal(qty_str)
                if qty <= 0:
                    raise ValueError
                if batch.material != line.material:
                    messages.error(request, 'Batch material does not match order line material.')
                else:
                    # Check available on batch
                    batch_reserved = ProductBatchReservation.objects.filter(
                        product_batch=batch
                    ).aggregate(
                        total=Coalesce(Sum('quantity_reserved'), Decimal('0'), output_field=DecimalField())
                    )['total']
                    batch_available = batch.quantity_produced - batch_reserved

                    # Check against order line remaining quantity
                    line_reserved = ProductBatchReservation.objects.filter(
                        order_line=line
                    ).aggregate(
                        total=Coalesce(Sum('quantity_reserved'), Decimal('0'), output_field=DecimalField())
                    )['total']
                    line_remaining = line.quantity_ordered - line_reserved

                    if qty > batch_available:
                        messages.error(request, f'Only {batch_available} units available in this batch.')
                    elif qty > line_remaining:
                        messages.error(request, f'Only {line_remaining} units still needed for this order line.')
                    else:
                        ProductBatchReservation.objects.create(
                            product_batch=batch,
                            order_line=line,
                            quantity_reserved=qty,
                        )
                        # Recalculate fulfilled from all reservations
                        total_reserved = line_reserved + qty
                        line.quantity_fulfilled = total_reserved
                        if line.quantity_fulfilled >= line.quantity_ordered:
                            line.status = 'FULFILLED'
                        else:
                            line.status = 'PARTIAL'
                        line.save()
                        messages.success(request, f'Reserved {qty} units from {batch.batch_number}.')
            except (ClientOrderLine.DoesNotExist, ProductBatch.DoesNotExist, ValueError, InvalidOperation) as e:
                messages.error(request, f'Error: {e}')

        elif action == 'remove_reservation':
            res_id = request.POST.get('reservation_id')
            try:
                res  = ProductBatchReservation.objects.get(pk=res_id)
                line = res.order_line
                qty  = res.quantity_reserved
                if line.order != order:
                    raise ProductBatchReservation.DoesNotExist
                res.delete()
                line.quantity_fulfilled = max(Decimal('0'), (line.quantity_fulfilled or Decimal('0')) - qty)
                if line.quantity_fulfilled == 0:
                    line.status = 'PENDING'
                elif line.quantity_fulfilled < line.quantity_ordered:
                    line.status = 'PARTIAL'
                line.save()
                messages.success(request, 'Reservation removed.')
            except ProductBatchReservation.DoesNotExist:
                messages.error(request, 'Reservation not found.')

        return redirect('order-detail', pk=pk)


class ClientOrderCreateView(View):
    def get(self, request):
        fin_materials = list(
            Material.objects.filter(category='FIN').order_by('name').values('id', 'name', 'sku')
        )
        clients_list = list(Client.objects.order_by('name').values('id', 'name', 'code'))
        return render(request, 'client_orders/order_form.html', {
            'form':               ClientOrderForm(),
            'formset':            ClientOrderLineFormSet(),
            'form_title':         'New Client Order',
            'submit_label':       'Create Order',
            'fin_materials_json': json.dumps(fin_materials),
            'clients_json':       json.dumps(clients_list),
        })

    def post(self, request):
        form    = ClientOrderForm(request.POST)
        formset = ClientOrderLineFormSet(request.POST)
        if form.is_valid() and formset.is_valid():
            order = form.save()
            formset.instance = order
            formset.save()
            messages.success(request, f'Order {order.reference} created.')
            return redirect('order-detail', pk=order.pk)
        fin_materials = list(
            Material.objects.filter(category='FIN').order_by('name').values('id', 'name', 'sku')
        )
        clients_list = list(Client.objects.order_by('name').values('id', 'name', 'code'))
        return render(request, 'client_orders/order_form.html', {
            'form':               form,
            'formset':            formset,
            'form_title':         'New Client Order',
            'submit_label':       'Create Order',
            'fin_materials_json': json.dumps(fin_materials),
            'clients_json':       json.dumps(clients_list),
        })


class ClientOrderEditView(View):
    def get(self, request, pk):
        order = get_object_or_404(ClientOrder, pk=pk)
        fin_materials = list(
            Material.objects.filter(category='FIN').order_by('name').values('id', 'name', 'sku')
        )
        clients_list = list(Client.objects.order_by('name').values('id', 'name', 'code'))
        return render(request, 'client_orders/order_form.html', {
            'form':               ClientOrderForm(instance=order),
            'formset':            ClientOrderLineFormSet(instance=order),
            'form_title':         f'Edit Order: {order.reference}',
            'submit_label':       'Save Changes',
            'order':              order,
            'fin_materials_json': json.dumps(fin_materials),
            'clients_json':       json.dumps(clients_list),
        })

    def post(self, request, pk):
        order = get_object_or_404(ClientOrder, pk=pk)
        form  = ClientOrderForm(request.POST, instance=order)

        # Build a mutable copy of POST data, dropping any lines marked DELETE
        # before constructing the formset, and re-index the remaining lines.
        # This avoids Django's formset validating against rows we are about
        # to remove, which previously corrupted unrelated lines with
        # "This field is required" errors.
        post_data = request.POST.copy()
        total = int(post_data.get('lines-TOTAL_FORMS', 0))

        deleted_ids  = []
        kept_indices = []
        for i in range(total):
            if post_data.get('lines-%d-DELETE' % i):
                line_id = post_data.get('lines-%d-id' % i)
                if line_id:
                    deleted_ids.append(line_id)
            else:
                kept_indices.append(i)

        if deleted_ids:
            ClientOrderLine.objects.filter(
                pk__in=[int(x) for x in deleted_ids if x.isdigit()],
                order=order
            ).delete()

            new_post = post_data.copy()
            for key in list(new_post.keys()):
                if key.startswith('lines-') and key not in (
                    'lines-TOTAL_FORMS', 'lines-INITIAL_FORMS',
                    'lines-MIN_NUM_FORMS', 'lines-MAX_NUM_FORMS'
                ):
                    del new_post[key]

            for new_idx, old_idx in enumerate(kept_indices):
                for field in ('id', 'material', 'quantity_ordered'):
                    val = post_data.get('lines-%d-%s' % (old_idx, field))
                    if val is not None:
                        new_post['lines-%d-%s' % (new_idx, field)] = val

            new_post['lines-TOTAL_FORMS']   = str(len(kept_indices))
            new_post['lines-INITIAL_FORMS'] = post_data.get('lines-INITIAL_FORMS', '0')
            post_data = new_post

        formset = ClientOrderLineFormSet(post_data, instance=order)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Order updated.')
            return redirect('order-detail', pk=pk)
        fin_materials = list(
            Material.objects.filter(category='FIN').order_by('name').values('id', 'name', 'sku')
        )
        clients_list = list(Client.objects.order_by('name').values('id', 'name', 'code'))
        return render(request, 'client_orders/order_form.html', {
            'form':               form,
            'formset':            formset,
            'form_title':         f'Edit Order: {order.reference}',
            'submit_label':       'Save Changes',
            'order':              order,
            'fin_materials_json': json.dumps(fin_materials),
            'clients_json':       json.dumps(clients_list),
        })


class ClientOrderDeleteView(View):
    def post(self, request, pk):
        order = get_object_or_404(ClientOrder, pk=pk)
        ref = order.reference
        try:
            order.delete()
            messages.success(request, f'Order "{ref}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete order "{ref}".')
        return redirect('order-list')


# ─────────────────────────────────────────────
# PRODUCTION RUNS
# ─────────────────────────────────────────────

class ProductionRunListView(View):
    def get(self, request):
        qs = ProductionRun.objects.select_related('material', 'location').all()
        status      = request.GET.get('status', '').strip()
        material_id = request.GET.get('material_id', '').strip()
        q           = request.GET.get('q', '').strip()
        if status:
            qs = qs.filter(status=status)
        if material_id:
            try:
                qs = qs.filter(material_id=int(material_id))
            except (ValueError, TypeError):
                pass
        if q:
            qs = qs.filter(
                Q(reference__icontains=q) |
                Q(material__name__icontains=q) |
                Q(material__sku__icontains=q)
            )
        paginator = Paginator(qs.order_by('-created_at'), 25)
        return render(request, 'production_runs/list.html', {
            'runs':           paginator.get_page(request.GET.get('page')),
            'all_materials':  Material.objects.filter(category='FIN').order_by('name'),
            'status_choices': ProductionRun.STATUS_CHOICES,
        })


class ProductionRunDetailView(View):
    def get(self, request, pk):
        run = get_object_or_404(
            ProductionRun.objects.select_related(
                'material', 'location', 'product_batch'
            ).prefetch_related(
                Prefetch('components', queryset=ProductionComponent.objects.select_related(
                    'material__unit'
                ).order_by('material__name')),
                Prefetch('allocations', queryset=ProductionRunAllocation.objects.select_related(
                    'order_line__order__client', 'order_line__material'
                )),
            ), pk=pk
        )
        allocation_form = ProductionRunAllocationForm(production_run=run)
        # Product batches with matching material for linking
        linkable_batches = ProductBatch.objects.filter(
            material=run.material
        ).select_related('material').order_by('-created_at')

        return render(request, 'production_runs/detail.html', {
            'run':               run,
            'allocation_form':   allocation_form,
            'component_status_choices': ProductionComponent.STATUS_CHOICES,
            'linkable_batches':  linkable_batches,
        })

    def post(self, request, pk):
        run    = get_object_or_404(ProductionRun, pk=pk)
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = request.POST.get('status')
            if new_status == 'COMPLETED':
                # Only allow completing if all components are IN_WAREHOUSE_RAW
                if not run.all_components_in_warehouse:
                    messages.error(
                        request,
                        'Cannot complete run — not all components are In Warehouse as Raw Material.'
                    )
                else:
                    run.status = 'COMPLETED'
                    run.actual_end = timezone.now().date()
                    run.save()
                    # Auto-create a ProductBatch for this run
                    from .models import ProductBatch as PB
                    batch_num = f"BATCH-{run.reference}"
                    if not PB.objects.filter(batch_number=batch_num).exists():
                        pb = PB.objects.create(
                            material         = run.material,
                            batch_number     = batch_num,
                            quantity_produced= run.actual_quantity or run.planned_quantity,
                            location         = run.location,
                        )
                        run.product_batch = pb
                        run.save()
                        messages.success(
                            request,
                            f'Run completed. Product batch {pb.batch_number} created.'
                        )
                    else:
                        messages.success(request, f'Run marked as completed.')
            elif new_status in dict(ProductionRun.STATUS_CHOICES):
                run.status = new_status
                if new_status == 'ACTIVE' and not run.actual_start:
                    run.actual_start = timezone.now().date()
                run.save()
                messages.success(request, f'Run status updated to {run.get_status_display()}.')

        elif action == 'add_allocation':
            form = ProductionRunAllocationForm(request.POST, production_run=run)
            if form.is_valid():
                qty        = form.cleaned_data['quantity_allocated']
                order_line = form.cleaned_data['order_line']
                # Validate capacity manually — avoids FK-not-set issue in model.clean()
                existing = run.allocations.aggregate(
                    total=Coalesce(Sum('quantity_allocated'), Decimal('0'), output_field=DecimalField())
                )['total']
                if existing + qty > run.planned_quantity:
                    messages.error(
                        request,
                        f"Allocation exceeds run capacity. Available: {run.planned_quantity - existing}"
                    )
                elif ProductionRunAllocation.objects.filter(
                    production_run=run, order_line=order_line
                ).exists():
                    messages.error(request, "This order line is already allocated to this run.")
                else:
                    ProductionRunAllocation.objects.create(
                        production_run=run,
                        order_line=order_line,
                        quantity_allocated=qty,
                        notes=form.cleaned_data.get('notes', ''),
                    )
                    messages.success(request, 'Allocation added.')
            else:
                for errs in form.errors.values():
                    for e in errs:
                        messages.error(request, e)

        elif action == 'link_batch':
            batch_id = request.POST.get('product_batch_id')
            if batch_id:
                try:
                    pb = ProductBatch.objects.get(pk=int(batch_id))
                    # Check material matches
                    if pb.material != run.material:
                        messages.error(
                            request,
                            f'Batch material ({pb.material.name}) does not match '
                            f'run material ({run.material.name}).'
                        )
                    else:
                        run.product_batch = pb
                        run.save()
                        messages.success(
                            request,
                            f'Product batch {pb.batch_number} linked to this run.'
                        )
                except (ProductBatch.DoesNotExist, ValueError):
                    messages.error(request, 'Product batch not found.')
            else:
                # Unlink
                run.product_batch = None
                run.save()
                messages.success(request, 'Product batch unlinked.')

        elif action == 'ship':
            qty = request.POST.get('quantity_shipped', '').strip()
            order_line_id = request.POST.get('order_line_id', '').strip()
            try:
                qty_dec = Decimal(qty)
                if qty_dec <= 0:
                    raise ValueError
                order_line = ClientOrderLine.objects.get(pk=int(order_line_id)) if order_line_id else None
                ProductionRunShipment.objects.create(
                    production_run=run,
                    order_line=order_line,
                    quantity_shipped=qty_dec,
                    notes=request.POST.get('ship_notes', ''),
                )
                run.status = 'COMPLETED'
                run.actual_end = timezone.now().date()
                run.save()
                messages.success(request, f'Run {run.reference} shipped and moved to history.')
                return redirect('production-run-list')
            except (ValueError, InvalidOperation):
                messages.error(request, 'Invalid quantity for shipment.')
            except ClientOrderLine.DoesNotExist:
                messages.error(request, 'Order line not found.')

        return redirect('production-run-detail', pk=pk)



class ProductionTemplateLookupView(View):
    """
    GET /production-runs/template-lookup/?material_id=123&planned_quantity=500
    Returns JSON: {"found": true, "components": [{"material_id":..,"name":..,"sku":..,
                   "unit":.., "quantity_required":..}, ...]}
    Used by the production run create form to auto-populate components
    from the saved ProductionTemplate for the selected finished product.
    """
    def get(self, request):
        material_id = request.GET.get('material_id', '').strip()
        qty_str     = request.GET.get('planned_quantity', '0').strip()
        try:
            material_id = int(material_id)
        except (ValueError, TypeError):
            return JsonResponse({'found': False, 'components': []})
        try:
            planned_qty = Decimal(qty_str or '0')
        except InvalidOperation:
            planned_qty = Decimal('0')

        try:
            template = ProductionTemplate.objects.select_related('product').get(product_id=material_id)
        except ProductionTemplate.DoesNotExist:
            return JsonResponse({'found': False, 'components': []})

        components = []
        for comp in template.components.select_related('material__unit').all():
            qty_required = (comp.ratio * planned_qty) if planned_qty else Decimal('0')
            components.append({
                'material_id':      comp.material.id,
                'name':             comp.material.name,
                'sku':              comp.material.sku,
                'unit':             comp.material.unit.name if comp.material.unit else '',
                'ratio':            float(comp.ratio),
                'quantity_required': float(qty_required),
            })

        return JsonResponse({'found': True, 'components': components})


class ProductionRunCreateView(View):
    def get(self, request):
        form    = ProductionRunForm()
        formset = ProductionComponentFormSet(prefix='comp')
        if request.GET.get('material'):
            form.initial['material'] = request.GET['material']
        raw_mats = list(Material.objects.filter(
            category__in=['RAW', 'PKG']
        ).order_by('name').values('id', 'name', 'sku'))
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'production_runs/form.html', {
            'form': form, 'formset': formset,
            'form_title': 'New Production Run', 'submit_label': 'Create Run',
            'all_raw_materials_json': json.dumps(raw_mats),
            'fin_materials_json': json.dumps(fin_mats),
        })

    def post(self, request):
        form    = ProductionRunForm(request.POST)
        formset = ProductionComponentFormSet(request.POST, prefix='comp')
        if form.is_valid():
            run = form.save()
            # Components are optional — save only if formset is valid
            if formset.is_valid():
                formset.instance = run
                formset.save()
            messages.success(request, f'Production run {run.reference} created.')
            return redirect('production-run-detail', pk=run.pk)
        raw_mats = list(Material.objects.filter(
            category__in=['RAW', 'PKG']
        ).order_by('name').values('id', 'name', 'sku'))
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'production_runs/form.html', {
            'form': form, 'formset': formset,
            'form_title': 'New Production Run', 'submit_label': 'Create Run',
            'all_raw_materials_json': json.dumps(raw_mats),
            'fin_materials_json': json.dumps(fin_mats),
        })


class ProductionRunEditView(View):
    def get(self, request, pk):
        run = get_object_or_404(ProductionRun, pk=pk)
        raw_mats = list(Material.objects.filter(
            category__in=['RAW', 'PKG']
        ).order_by('name').values('id', 'name', 'sku'))
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'production_runs/form.html', {
            'form':    ProductionRunForm(instance=run),
            'formset': ProductionComponentFormSet(instance=run, prefix='comp'),
            'form_title': f'Edit Run: {run.reference}', 'submit_label': 'Save Changes',
            'run':     run,
            'all_raw_materials_json': json.dumps(raw_mats),
            'fin_materials_json':     json.dumps(fin_mats),
        })

    def post(self, request, pk):
        run     = get_object_or_404(ProductionRun, pk=pk)
        form    = ProductionRunForm(request.POST, instance=run)
        formset = ProductionComponentFormSet(request.POST, instance=run, prefix='comp')
        if form.is_valid():
            form.save()
            if formset.is_valid():
                formset.save()
                messages.success(request, 'Production run updated.')
            else:
                messages.success(request, 'Production run updated.')
                for f in formset.forms:
                    for field, errs in f.errors.items():
                        for e in errs:
                            messages.warning(request, f'Component row — {field}: {e}')
                for e in formset.non_form_errors():
                    messages.warning(request, f'Components: {e}')
            return redirect('production-run-detail', pk=pk)
        raw_mats = list(Material.objects.filter(
            category__in=['RAW', 'PKG']
        ).order_by('name').values('id', 'name', 'sku'))
        fin_mats = list(Material.objects.filter(
            category='FIN'
        ).order_by('name').values('id', 'name', 'sku'))
        return render(request, 'production_runs/form.html', {
            'form': form, 'formset': formset,
            'form_title': f'Edit Run: {run.reference}', 'submit_label': 'Save Changes',
            'run':  run,
            'all_raw_materials_json': json.dumps(raw_mats),
            'fin_materials_json': json.dumps(fin_mats),
        })



class ProductionRunCopyView(View):
    """Creates a copy of an existing production run with all its components."""
    def post(self, request, pk):
        original = get_object_or_404(ProductionRun, pk=pk)

        # Generate a new reference based on the original
        base_ref = original.reference
        # Find a unique reference by appending -COPY, -COPY-2, etc.
        new_ref  = f"{base_ref}-COPY"
        counter  = 1
        while ProductionRun.objects.filter(reference=new_ref).exists():
            counter += 1
            new_ref = f"{base_ref}-COPY-{counter}"

        # Create the new run
        new_run = ProductionRun.objects.create(
            reference       = new_ref,
            material        = original.material,
            planned_quantity= original.planned_quantity,
            status          = 'PLANNED',
            location        = original.location,
            notes           = original.notes,
            # Reset dates — user sets these on the new run
        )

        # Copy all components
        for comp in original.components.all():
            ProductionComponent.objects.create(
                production_run   = new_run,
                material         = comp.material,
                quantity_required= comp.quantity_required,
                status           = 'PENDING',  # reset to pending
                expected_date    = comp.expected_date,
                notes            = comp.notes,
            )

        messages.success(
            request,
            f'Production run copied as {new_ref}. Update the reference and dates as needed.'
        )
        return redirect('production-run-edit', pk=new_run.pk)


class ProductionRunDeleteView(View):
    def post(self, request, pk):
        run = get_object_or_404(ProductionRun, pk=pk)
        ref = run.reference
        try:
            run.delete()
            messages.success(request, f'Production run "{ref}" deleted.')
        except Exception as e:
            messages.error(request, _deletion_blocked_msg(e))
        return redirect('production-run-list')


class ProductionComponentDeleteView(View):
    def post(self, request, pk):
        component = get_object_or_404(ProductionComponent, pk=pk)
        run_pk    = component.production_run.pk
        name      = component.material.name
        try:
            component.delete()
            messages.success(request, f'{name} removed from production run.')
        except Exception as e:
            messages.error(request, _deletion_blocked_msg(e))
        return redirect('production-run-edit', pk=run_pk)


class ProductionRunAllocationDeleteView(View):
    def post(self, request, pk):
        alloc  = get_object_or_404(ProductionRunAllocation, pk=pk)
        run_pk = alloc.production_run.pk
        alloc.delete()
        messages.success(request, 'Allocation removed.')
        return redirect('production-run-detail', pk=run_pk)


class ProductionComponentUpdateView(View):
    """Quick status update for a single component."""
    def post(self, request, pk):
        component  = get_object_or_404(ProductionComponent, pk=pk)
        new_status = request.POST.get('status')
        if new_status in dict(ProductionComponent.STATUS_CHOICES):
            component.status = new_status
            if new_status in ('IN_WAREHOUSE_RAW', 'IN_PROCESS', 'FINAL_PRODUCT') \
                    and not component.actual_date:
                component.actual_date = timezone.now().date()
            component.save()
            messages.success(
                request,
                f'{component.material.name} → {component.get_status_display()}'
            )
        return redirect('production-run-detail', pk=component.production_run.pk)


# ─────────────────────────────────────────────
# ALLOCATIONS TABLE
# ─────────────────────────────────────────────

class AllocationListView(View):
    """Shows all ProductionRunAllocation records in one filterable table."""
    def get(self, request):
        qs = ProductionRunAllocation.objects.select_related(
            'production_run__material',
            'order_line__order__client',
            'order_line__material',
        ).order_by('-created_at')

        run_id   = request.GET.get('run_id', '').strip()
        order_id = request.GET.get('order_id', '').strip()
        if run_id:
            try:
                qs = qs.filter(production_run_id=int(run_id))
            except (ValueError, TypeError):
                pass
        if order_id:
            try:
                qs = qs.filter(order_line__order_id=int(order_id))
            except (ValueError, TypeError):
                pass

        paginator = Paginator(qs, 50)
        return render(request, 'allocations/list.html', {
            'allocations':   paginator.get_page(request.GET.get('page')),
            'all_runs':      ProductionRun.objects.select_related('material').order_by('-created_at'),
            'all_orders':    ClientOrder.objects.select_related('client').order_by('-order_date'),
        })


# ─────────────────────────────────────────────
# PRODUCTION BOARD  (Kanban by component status)
# ─────────────────────────────────────────────

# Status priority order for deriving board_status
COMPONENT_STATUS_PRIORITY = [
    'PENDING', 'ORDERED', 'IN_WAREHOUSE_RAW', 'IN_PROCESS', 'FINAL_PRODUCT'
]

BOARD_STATUS_META = {
    'PENDING':          {'label': 'Pending',            'color': 'grey'},
    'ORDERED':          {'label': 'Ordered',            'color': 'blue'},
    'IN_WAREHOUSE_RAW': {'label': 'In Warehouse (Raw)', 'color': 'orange'},
    'IN_PROCESS':       {'label': 'In Process',         'color': 'warn'},
    'FINAL_PRODUCT':    {'label': 'Final Product',      'color': 'green'},
}


class ProductionBoardView(View):
    def get(self, request):
        order_id = request.GET.get('order', '').strip()

        runs = ProductionRun.objects.exclude(
            status__in=['COMPLETED', 'CANCELLED']
        ).select_related('material', 'location').prefetch_related(
            Prefetch('components', queryset=ProductionComponent.objects.select_related('material__unit'))
        ).order_by('planned_start')

        selected_order = None
        if order_id:
            try:
                selected_order = ClientOrder.objects.get(pk=int(order_id))
                # Get materials of product batches reserved against this order
                material_ids = ProductBatchReservation.objects.filter(
                    order_line__order=selected_order
                ).values_list(
                    'product_batch__material_id', flat=True
                ).distinct()
                # Show runs producing any of those materials
                runs = runs.filter(material_id__in=material_ids)
            except (ClientOrder.DoesNotExist, ValueError):
                pass

        orders = ClientOrder.objects.exclude(
            status__in=['SHIPPED', 'CANCELLED']
        ).select_related('client').order_by('-order_date')

        # Group runs into board columns by board_status
        columns = {'PENDING': [], 'ORDERED': [], 'IN_WAREHOUSE_RAW': []}
        for run in runs:
            bs = run.board_status
            if bs in columns:
                columns[bs].append(run)

        return render(request, 'production_runs/board.html', {
            'runs':           runs,
            'columns':        columns,
            'orders':         orders,
            'selected_order': selected_order,
        })

class ShipmentHistoryView(View):
    """Read-only archive of shipped production runs."""
    def get(self, request):
        qs = ProductionRunShipment.objects.select_related(
            'production_run__material',
            'order_line__order__client',
        ).order_by('-shipped_at')
        paginator = Paginator(qs, 25)
        return render(request, 'production_runs/shipment_history.html', {
            'shipments': paginator.get_page(request.GET.get('page')),
        })
