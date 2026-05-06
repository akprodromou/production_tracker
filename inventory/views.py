from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q
from django.db.models.functions import Coalesce
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ManufacturingOrder, ProductBatch, MaterialTransaction, WorkflowTask
)
from .forms import (
    UnitForm, LocationForm, MaterialForm, RawMaterialBatchForm,
    ManufacturingOrderForm, ManufacturingOrderCancelForm,
    ProductBatchForm, MaterialTransactionForm,
    ReserveMaterialForm, ConsumeMaterialForm, ReleaseMaterialForm,
    WorkflowTaskForm, WorkflowTaskStatusForm
)
from .services import reserve_material, consume_material, release_material


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

class DashboardView(View):
    def get(self, request):
        # Stats
        total_materials    = Material.objects.count()
        raw_materials      = Material.objects.filter(category__in=['RAW', 'PKG']).count()
        finished_materials = Material.objects.filter(category='FIN').count()
        active_batches     = RawMaterialBatch.objects.count()
        open_orders        = ManufacturingOrder.objects.filter(is_cancelled=False).count()
        cancelled_orders   = ManufacturingOrder.objects.filter(is_cancelled=True).count()
        pending_tasks      = WorkflowTask.objects.filter(status='PENDING').count()
        in_progress_tasks  = WorkflowTask.objects.filter(status='IN_PROGRESS').count()

        # Low stock: batches where available < 10% of total (or just show all, sorted)
        all_batches = list(RawMaterialBatch.objects.select_related('material', 'location'))
        low_stock_batches = sorted(
            [b for b in all_batches if b.available_quantity <= (b.total_quantity * Decimal('0.2'))],
            key=lambda b: b.available_quantity
        )[:8]

        recent_transactions = MaterialTransaction.objects.select_related(
            'raw_material_batch__material', 'product_batch'
        ).order_by('-created_at')[:8]

        upcoming_tasks = WorkflowTask.objects.select_related(
            'location', 'raw_material_batch', 'product_batch'
        ).exclude(status='DONE').order_by('expected_completion')[:6]

        recent_product_batches = ProductBatch.objects.select_related(
            'material', 'location'
        ).order_by('-created_at')[:6]

        return render(request, 'dashboard.html', {
            'total_materials':      total_materials,
            'raw_materials':        raw_materials,
            'finished_materials':   finished_materials,
            'active_batches':       active_batches,
            'open_orders':          open_orders,
            'cancelled_orders':     cancelled_orders,
            'pending_tasks':        pending_tasks,
            'in_progress_tasks':    in_progress_tasks,
            'low_stock_batches':    low_stock_batches,
            'recent_transactions':  recent_transactions,
            'upcoming_tasks':       upcoming_tasks,
            'recent_product_batches': recent_product_batches,
        })


# ─────────────────────────────────────────────
# UNITS
# ─────────────────────────────────────────────

class UnitListView(View):
    def get(self, request):
        units = Unit.objects.all().order_by('name')
        return render(request, 'units/list.html', {'units': units})


class UnitCreateView(View):
    def get(self, request):
        form = UnitForm()
        return render(request, 'units/form.html', {
            'form': form, 'form_title': 'New Unit', 'submit_label': 'Create Unit'
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
        form = UnitForm(instance=unit)
        return render(request, 'units/form.html', {
            'form': form, 'form_title': f'Edit Unit: {unit.name}', 'submit_label': 'Save Changes'
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


class LocationCreateView(View):
    def get(self, request):
        form = LocationForm()
        return render(request, 'locations/form.html', {
            'form': form, 'form_title': 'New Location', 'submit_label': 'Create Location'
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
        form = LocationForm(instance=loc)
        return render(request, 'locations/form.html', {
            'form': form, 'form_title': f'Edit: {loc.name}', 'submit_label': 'Save Changes'
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
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
        paginator = Paginator(qs.order_by('name'), 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'materials/list.html', {'materials': page})


class MaterialDetailView(View):
    def get(self, request, pk):
        m = get_object_or_404(Material.objects.select_related('unit'), pk=pk)
        raw_batches     = RawMaterialBatch.objects.filter(material=m).select_related('location') if m.category in ('RAW', 'PKG') else []
        product_batches = ProductBatch.objects.filter(material=m).select_related('location') if m.category == 'FIN' else []
        return render(request, 'materials/detail.html', {
            'material': m,
            'raw_batches': raw_batches,
            'product_batches': product_batches,
        })


class MaterialCreateView(View):
    def get(self, request):
        form = MaterialForm()
        return render(request, 'materials/form.html', {
            'form': form, 'form_title': 'New Material', 'submit_label': 'Create Material'
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
        form = MaterialForm(instance=m)
        return render(request, 'materials/form.html', {
            'form': form, 'form_title': f'Edit: {m.name}', 'submit_label': 'Save Changes'
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
        material_id = request.GET.get('material_id')
        location_id = request.GET.get('location_id')
        q = request.GET.get('q', '').strip()
        if material_id:
            qs = qs.filter(material_id=material_id)
        if location_id:
            qs = qs.filter(location_id=location_id)
        if q:
            qs = qs.filter(lot_number__icontains=q)
        paginator = Paginator(qs.order_by('-created_at'), 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'batches/list.html', {
            'batches':       page,
            'all_materials': Material.objects.filter(category__in=['RAW', 'PKG']).order_by('name'),
            'all_locations': Location.objects.order_by('name'),
        })


class RawMaterialBatchDetailView(View):
    def get(self, request, pk):
        batch = get_object_or_404(
            RawMaterialBatch.objects.select_related('material', 'location'), pk=pk
        )
        transactions = MaterialTransaction.objects.filter(
            raw_material_batch=batch
        ).select_related('product_batch').order_by('-created_at')
        product_batches = ProductBatch.objects.select_related('material').order_by('-created_at')
        return render(request, 'batches/detail.html', {
            'batch':          batch,
            'transactions':   transactions,
            'product_batches': product_batches,
        })


class RawMaterialBatchCreateView(View):
    def get(self, request):
        form = RawMaterialBatchForm()
        if request.GET.get('material'):
            form.initial['material'] = request.GET['material']
        return render(request, 'batches/form.html', {
            'form': form, 'form_title': 'New Raw Material Batch', 'submit_label': 'Create Batch'
        })

    def post(self, request):
        form = RawMaterialBatchForm(request.POST)
        if form.is_valid():
            batch = form.save()
            # Record the PRODUCED transaction
            MaterialTransaction.objects.create(
                raw_material_batch=batch,
                transaction_type='PRODUCED',
                quantity=batch.total_quantity,
            )
            messages.success(request, f'Batch {batch.lot_number} created.')
            return redirect('batch-detail', pk=batch.pk)
        return render(request, 'batches/form.html', {
            'form': form, 'form_title': 'New Raw Material Batch', 'submit_label': 'Create Batch'
        })


class RawMaterialBatchDeleteView(View):
    def post(self, request, pk):
        batch = get_object_or_404(RawMaterialBatch, pk=pk)
        lot = batch.lot_number
        try:
            batch.delete()
            messages.success(request, f'Batch "{lot}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete batch "{lot}".')
        return redirect('batch-list')


# ─────────────────────────────────────────────
# MANUFACTURING ORDERS
# ─────────────────────────────────────────────

class ManufacturingOrderListView(View):
    def get(self, request):
        qs = ManufacturingOrder.objects.select_related(
            'raw_material_batch__material', 'raw_material_batch__location'
        ).all()
        status_filter = request.GET.get('status')
        if status_filter == 'active':
            qs = qs.filter(is_cancelled=False)
        elif status_filter == 'cancelled':
            qs = qs.filter(is_cancelled=True)
        paginator = Paginator(qs.order_by('-created_at'), 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'manufacturing_orders/list.html', {'orders': page})


class ManufacturingOrderCreateView(View):
    def get(self, request):
        form = ManufacturingOrderForm()
        return render(request, 'manufacturing_orders/list.html', {
            'form': form, 'form_title': 'New Manufacturing Order', 'submit_label': 'Create Order',
            'orders': ManufacturingOrder.objects.select_related(
                'raw_material_batch__material', 'raw_material_batch__location'
            ).order_by('-created_at')[:25]
        })

    def post(self, request):
        form = ManufacturingOrderForm(request.POST)
        if form.is_valid():
            mo = form.save()
            messages.success(request, f'Manufacturing Order MO-{mo.id} created.')
            return redirect('manufacturing-order-detail', pk=mo.pk)
        messages.error(request, 'Could not create order. Check the form.')
        return redirect('manufacturing-order-list')


class ManufacturingOrderDetailView(View):
    def get(self, request, pk):
        order = get_object_or_404(
            ManufacturingOrder.objects.select_related(
                'raw_material_batch__material', 'raw_material_batch__location'
            ), pk=pk
        )
        return render(request, 'manufacturing_orders/detail.html', {'order': order})

    def post(self, request, pk):
        order = get_object_or_404(ManufacturingOrder, pk=pk)
        is_cancelled = request.POST.get('is_cancelled')
        if is_cancelled == 'true':
            order.is_cancelled = True
            order.save()
            messages.success(request, f'MO-{order.id} cancelled.')
        elif is_cancelled == 'false':
            order.is_cancelled = False
            order.save()
            messages.success(request, f'MO-{order.id} re-activated.')
        return redirect('manufacturing-order-detail', pk=pk)


# ─────────────────────────────────────────────
# PRODUCT BATCHES
# ─────────────────────────────────────────────

class ProductBatchListView(View):
    def get(self, request):
        qs = ProductBatch.objects.select_related('material', 'location').all()
        material_id = request.GET.get('material_id')
        location_id = request.GET.get('location_id')
        q = request.GET.get('q', '').strip()
        if material_id:
            qs = qs.filter(material_id=material_id)
        if location_id:
            qs = qs.filter(location_id=location_id)
        if q:
            qs = qs.filter(batch_number__icontains=q)
        paginator = Paginator(qs.order_by('-created_at'), 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'product_batches/list.html', {
            'batches':       page,
            'all_materials': Material.objects.filter(category='FIN').order_by('name'),
            'all_locations': Location.objects.order_by('name'),
        })


class ProductBatchDetailView(View):
    def get(self, request, pk):
        batch = get_object_or_404(
            ProductBatch.objects.select_related('material', 'location'), pk=pk
        )
        transactions = MaterialTransaction.objects.filter(
            product_batch=batch
        ).select_related('raw_material_batch__material').order_by('-created_at')

        # Build per-raw-batch consumption summary
        summary = {}
        for tx in transactions:
            rb = tx.raw_material_batch
            if rb.pk not in summary:
                summary[rb.pk] = {
                    'batch':    rb,
                    'reserved': Decimal('0'),
                    'consumed': Decimal('0'),
                }
            if tx.transaction_type == 'RESERVED':
                summary[rb.pk]['reserved'] += tx.quantity
            elif tx.transaction_type == 'CONSUMED':
                summary[rb.pk]['consumed'] += tx.quantity

        return render(request, 'product_batches/detail.html', {
            'batch':               batch,
            'transactions':        transactions,
            'consumption_summary': list(summary.values()),
        })


class ProductBatchCreateView(View):
    def get(self, request):
        form = ProductBatchForm()
        if request.GET.get('material'):
            form.initial['material'] = request.GET['material']
        return render(request, 'product_batches/form.html', {
            'form': form, 'form_title': 'New Product Batch', 'submit_label': 'Create Batch'
        })

    def post(self, request):
        form = ProductBatchForm(request.POST)
        if form.is_valid():
            pb = form.save()
            messages.success(request, f'Product batch {pb.batch_number} created.')
            return redirect('product-batch-detail', pk=pb.pk)
        return render(request, 'product_batches/form.html', {
            'form': form, 'form_title': 'New Product Batch', 'submit_label': 'Create Batch'
        })


class ProductBatchDeleteView(View):
    def post(self, request, pk):
        pb = get_object_or_404(ProductBatch, pk=pk)
        bn = pb.batch_number
        try:
            pb.delete()
            messages.success(request, f'Product batch "{bn}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete "{bn}".')
        return redirect('product-batch-list')


# ─────────────────────────────────────────────
# MATERIAL TRANSACTIONS  (read-only ledger)
# ─────────────────────────────────────────────

class MaterialTransactionListView(View):
    def get(self, request):
        qs = MaterialTransaction.objects.select_related(
            'raw_material_batch__material', 'product_batch__material'
        ).order_by('-created_at')

        batch_id         = request.GET.get('batch_id')
        product_batch_id = request.GET.get('product_batch_id')
        tx_type          = request.GET.get('transaction_type')
        reference        = request.GET.get('reference', '').strip()

        if batch_id:
            qs = qs.filter(raw_material_batch_id=batch_id)
        if product_batch_id:
            qs = qs.filter(product_batch_id=product_batch_id)
        if tx_type:
            qs = qs.filter(transaction_type=tx_type.upper())
        if reference:
            qs = qs.filter(reference__icontains=reference)

        # Summary counts for the filtered set
        summary = qs.values('transaction_type').annotate(total=Sum('quantity'))
        summary_map = {s['transaction_type']: s['total'] for s in summary}
        summary_ctx = {
            'produced': summary_map.get('PRODUCED', 0),
            'reserved': summary_map.get('RESERVED', 0),
            'consumed': summary_map.get('CONSUMED', 0),
            'released': summary_map.get('RELEASED', 0),
        }

        paginator = Paginator(qs, 50)
        page = paginator.get_page(request.GET.get('page'))

        return render(request, 'transactions/list.html', {
            'transactions':       page,
            'summary':            summary_ctx,
            'all_batches':        RawMaterialBatch.objects.select_related('material').order_by('-created_at'),
            'all_product_batches': ProductBatch.objects.select_related('material').order_by('-created_at'),
        })


# ─────────────────────────────────────────────
# SERVICE ENDPOINTS  (reserve / consume / release)
# ─────────────────────────────────────────────

class ReserveMaterialView(View):
    def post(self, request):
        form = ReserveMaterialForm(request.POST)
        if form.is_valid():
            try:
                reserve_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
                )
                messages.success(request, f"Reserved {form.cleaned_data['quantity']} units.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
        # Redirect back to the batch detail page
        batch_id = request.POST.get('batch_id')
        return redirect('batch-detail', pk=batch_id) if batch_id else redirect('batch-list')


class ConsumeMaterialView(View):
    def post(self, request):
        form = ConsumeMaterialForm(request.POST)
        if form.is_valid():
            try:
                consume_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
                )
                messages.success(request, f"Consumed {form.cleaned_data['quantity']} units.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
        batch_id = request.POST.get('batch_id')
        return redirect('batch-detail', pk=batch_id) if batch_id else redirect('batch-list')


class ReleaseMaterialView(View):
    def post(self, request):
        form = ReleaseMaterialForm(request.POST)
        if form.is_valid():
            try:
                release_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
                )
                messages.success(request, f"Released {form.cleaned_data['quantity']} units.")
            except ValidationError as e:
                messages.error(request, e.message)
        else:
            for field_errors in form.errors.values():
                for error in field_errors:
                    messages.error(request, error)
        batch_id = request.POST.get('batch_id')
        return redirect('batch-detail', pk=batch_id) if batch_id else redirect('batch-list')


# ─────────────────────────────────────────────
# WORKFLOW TASKS
# ─────────────────────────────────────────────

class WorkflowTaskListView(View):
    def get(self, request):
        qs = WorkflowTask.objects.select_related(
            'location', 'raw_material_batch', 'product_batch'
        ).all()

        status_filter   = request.GET.get('status', '').upper()
        location_id     = request.GET.get('location_id')
        q               = request.GET.get('q', '').strip()

        if status_filter:
            qs = qs.filter(status=status_filter)
        if location_id:
            qs = qs.filter(location_id=location_id)
        if q:
            qs = qs.filter(description__icontains=q)

        # Kanban buckets (unfiltered by status so all columns always populate)
        all_tasks = WorkflowTask.objects.select_related(
            'location', 'raw_material_batch', 'product_batch'
        ).all()
        tasks_pending     = all_tasks.filter(status='PENDING').order_by('expected_completion')
        tasks_in_progress = all_tasks.filter(status='IN_PROGRESS').order_by('expected_completion')
        tasks_done        = all_tasks.filter(status='DONE').order_by('-actual_completion')[:20]

        paginator = Paginator(qs.order_by('status', 'expected_completion'), 25)
        page = paginator.get_page(request.GET.get('page'))

        return render(request, 'workflow_tasks/list.html', {
            'tasks':              page,
            'tasks_pending':      tasks_pending,
            'tasks_in_progress':  tasks_in_progress,
            'tasks_done':         tasks_done,
            'all_locations':      Location.objects.order_by('name'),
        })


class WorkflowTaskCreateView(View):
    def get(self, request):
        form = WorkflowTaskForm()
        return render(request, 'workflow_tasks/form.html', {
            'form': form, 'form_title': 'New Task', 'submit_label': 'Create Task'
        })

    def post(self, request):
        form = WorkflowTaskForm(request.POST)
        if form.is_valid():
            task = form.save()
            messages.success(request, 'Task created.')
            return redirect('workflow-task-detail', pk=task.pk)
        return render(request, 'workflow_tasks/form.html', {
            'form': form, 'form_title': 'New Task', 'submit_label': 'Create Task'
        })


class WorkflowTaskDetailView(View):
    def get(self, request, pk):
        task = get_object_or_404(
            WorkflowTask.objects.select_related(
                'location', 'raw_material_batch__material', 'product_batch__material'
            ), pk=pk
        )
        return render(request, 'workflow_tasks/detail.html', {'task': task})


class WorkflowTaskEditView(View):
    def get(self, request, pk):
        task = get_object_or_404(WorkflowTask, pk=pk)
        form = WorkflowTaskForm(instance=task)
        return render(request, 'workflow_tasks/form.html', {
            'form': form, 'form_title': f'Edit Task #{task.pk}', 'submit_label': 'Save Changes'
        })

    def post(self, request, pk):
        task = get_object_or_404(WorkflowTask, pk=pk)
        form = WorkflowTaskForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            messages.success(request, 'Task updated.')
            return redirect('workflow-task-detail', pk=pk)
        return render(request, 'workflow_tasks/form.html', {
            'form': form, 'form_title': f'Edit Task #{task.pk}', 'submit_label': 'Save Changes'
        })


class WorkflowTaskDeleteView(View):
    def post(self, request, pk):
        task = get_object_or_404(WorkflowTask, pk=pk)
        task.delete()
        messages.success(request, 'Task deleted.')
        return redirect('workflow-task-list')


class WorkflowTaskStatusView(View):
    """Handles quick status updates from both table and Kanban views."""
    def post(self, request, pk):
        task = get_object_or_404(WorkflowTask, pk=pk)
        form = WorkflowTaskStatusForm(request.POST, instance=task)
        if form.is_valid():
            form.save()
            messages.success(request, f'Task marked as {task.get_status_display()}.')
        else:
            # Fallback: just update status directly
            new_status = request.POST.get('status')
            if new_status in ('PENDING', 'IN_PROGRESS', 'DONE'):
                task.status = new_status
                if new_status == 'DONE' and not task.actual_completion:
                    task.actual_completion = timezone.now()
                task.save()
                messages.success(request, f'Task marked as {task.get_status_display()}.')

        # Return to wherever the user came from
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        return redirect(next_url or 'workflow-task-list')
