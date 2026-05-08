from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.views import View
from django.db.models import Sum, Q, Prefetch
from django.db.models.functions import Coalesce
from django.db.models import DecimalField
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.utils import timezone
from decimal import Decimal

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ProductBatch, MaterialTransaction, WorkflowTask,
    Client, ClientOrder, ClientOrderLine,
    ProductionRun, ProductionRunAllocation, ProductionComponent
)
from .forms import (
    UnitForm, LocationForm, MaterialForm, RawMaterialBatchForm,
    ProductBatchForm, WorkflowTaskForm, WorkflowTaskStatusForm,
    ReserveMaterialForm, ConsumeMaterialForm, ReleaseMaterialForm,
    ClientForm, ClientOrderForm, ClientOrderLineFormSet,
    ProductionRunForm, ProductionRunAllocationForm,
    ProductionComponentForm, ProductionComponentFormSet,
)
from .services import reserve_material, consume_material, release_material


# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

class DashboardView(View):
    def get(self, request):
        all_batches = list(RawMaterialBatch.objects.select_related('material', 'location'))
        low_stock_batches = sorted(
            [b for b in all_batches if b.available_quantity <= (b.total_quantity * Decimal('0.2'))],
            key=lambda b: b.available_quantity
        )[:8]

        return render(request, 'dashboard.html', {
            'total_materials':       Material.objects.count(),
            'raw_materials':         Material.objects.filter(category__in=['RAW', 'PKG']).count(),
            'finished_materials':    Material.objects.filter(category='FIN').count(),
            'active_batches':        RawMaterialBatch.objects.count(),
            'open_orders':           ClientOrder.objects.exclude(status__in=['FULFILLED', 'CANCELLED']).count(),
            'active_production_runs': ProductionRun.objects.filter(status__in=['PLANNED', 'ACTIVE']).count(),
            'pending_tasks':         WorkflowTask.objects.filter(status='PENDING').count(),
            'in_progress_tasks':     WorkflowTask.objects.filter(status='IN_PROGRESS').count(),
            'low_stock_batches':     low_stock_batches,
            'recent_transactions':   MaterialTransaction.objects.select_related(
                                         'raw_material_batch__material', 'product_batch'
                                     ).order_by('-created_at')[:8],
            'upcoming_tasks':        WorkflowTask.objects.select_related('location').exclude(
                                         status='DONE'
                                     ).order_by('expected_completion')[:6],
            'recent_orders':         ClientOrder.objects.select_related('client').order_by('-created_at')[:6],
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
            qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
        paginator = Paginator(qs.order_by('name'), 25)
        return render(request, 'materials/list.html', {
            'materials': paginator.get_page(request.GET.get('page'))
        })


class MaterialDetailView(View):
    def get(self, request, pk):
        m = get_object_or_404(Material.objects.select_related('unit'), pk=pk)
        return render(request, 'materials/detail.html', {
            'material':       m,
            'raw_batches':    RawMaterialBatch.objects.filter(material=m).select_related('location') if m.category in ('RAW', 'PKG') else [],
            'product_batches': ProductBatch.objects.filter(material=m).select_related('location') if m.category == 'FIN' else [],
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
        return render(request, 'batches/list.html', {
            'batches':       paginator.get_page(request.GET.get('page')),
            'all_materials': Material.objects.filter(category__in=['RAW', 'PKG']).order_by('name'),
            'all_locations': Location.objects.order_by('name'),
        })


class RawMaterialBatchDetailView(View):
    def get(self, request, pk):
        batch = get_object_or_404(
            RawMaterialBatch.objects.select_related('material', 'location'), pk=pk
        )
        return render(request, 'batches/detail.html', {
            'batch':            batch,
            'transactions':     MaterialTransaction.objects.filter(
                                    raw_material_batch=batch
                                ).select_related('product_batch').order_by('-created_at'),
            'product_batches':  ProductBatch.objects.select_related('material').order_by('-created_at'),
            'production_runs':  ProductionRun.objects.filter(
                                    status__in=['PLANNED', 'ACTIVE']
                                ).select_related('material').order_by('-created_at'),
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
        return render(request, 'product_batches/list.html', {
            'batches':       paginator.get_page(request.GET.get('page')),
            'all_materials': Material.objects.filter(category='FIN').order_by('name'),
            'all_locations': Location.objects.order_by('name'),
        })


class ProductBatchDetailView(View):
    def get(self, request, pk):
        batch = get_object_or_404(ProductBatch.objects.select_related('material', 'location'), pk=pk)
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
# TRANSACTIONS
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
# SERVICE ACTIONS
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
                consume_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
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
                release_material(
                    form.cleaned_data['batch'].id,
                    form.cleaned_data['product_batch'],
                    form.cleaned_data['quantity'],
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
        client  = request.GET.get('client_id')
        q       = request.GET.get('q', '').strip()
        if status:
            qs = qs.filter(status=status)
        if client:
            qs = qs.filter(client_id=client)
        if q:
            qs = qs.filter(Q(reference__icontains=q) | Q(client__name__icontains=q))
        paginator = Paginator(qs.order_by('-order_date'), 25)
        return render(request, 'client_orders/order_list.html', {
            'orders':      paginator.get_page(request.GET.get('page')),
            'all_clients': Client.objects.order_by('name'),
            'status_choices': ClientOrder.STATUS_CHOICES,
        })


class ClientOrderDetailView(View):
    def get(self, request, pk):
        order = get_object_or_404(
            ClientOrder.objects.select_related('client').prefetch_related(
                Prefetch('lines', queryset=ClientOrderLine.objects.select_related('material').prefetch_related(
                    Prefetch('allocations', queryset=ProductionRunAllocation.objects.select_related('production_run'))
                ))
            ), pk=pk
        )
        return render(request, 'client_orders/order_detail.html', {'order': order})

    def post(self, request, pk):
        order = get_object_or_404(ClientOrder, pk=pk)
        new_status = request.POST.get('status')
        if new_status in dict(ClientOrder.STATUS_CHOICES):
            order.status = new_status
            order.save()
            messages.success(request, f'Order status updated to {order.get_status_display()}.')
        return redirect('order-detail', pk=pk)


class ClientOrderCreateView(View):
    def get(self, request):
        return render(request, 'client_orders/order_form.html', {
            'form':     ClientOrderForm(),
            'formset':  ClientOrderLineFormSet(),
            'form_title': 'New Client Order', 'submit_label': 'Create Order'
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
        return render(request, 'client_orders/order_form.html', {
            'form':     form,
            'formset':  formset,
            'form_title': 'New Client Order', 'submit_label': 'Create Order'
        })


class ClientOrderEditView(View):
    def get(self, request, pk):
        order = get_object_or_404(ClientOrder, pk=pk)
        return render(request, 'client_orders/order_form.html', {
            'form':     ClientOrderForm(instance=order),
            'formset':  ClientOrderLineFormSet(instance=order),
            'form_title': f'Edit Order: {order.reference}', 'submit_label': 'Save Changes',
            'order': order,
        })

    def post(self, request, pk):
        order   = get_object_or_404(ClientOrder, pk=pk)
        form    = ClientOrderForm(request.POST, instance=order)
        formset = ClientOrderLineFormSet(request.POST, instance=order)
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Order updated.')
            return redirect('order-detail', pk=pk)
        return render(request, 'client_orders/order_form.html', {
            'form': form, 'formset': formset,
            'form_title': f'Edit Order: {order.reference}', 'submit_label': 'Save Changes',
            'order': order,
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
        status      = request.GET.get('status')
        material_id = request.GET.get('material_id')
        q           = request.GET.get('q', '').strip()
        if status:
            qs = qs.filter(status=status)
        if material_id:
            qs = qs.filter(material_id=material_id)
        if q:
            qs = qs.filter(reference__icontains=q)
        paginator = Paginator(qs.order_by('-created_at'), 25)
        return render(request, 'production_runs/list.html', {
            'runs':          paginator.get_page(request.GET.get('page')),
            'all_materials': Material.objects.filter(category='FIN').order_by('name'),
            'status_choices': ProductionRun.STATUS_CHOICES,
        })


class ProductionRunDetailView(View):
    def get(self, request, pk):
        run = get_object_or_404(
            ProductionRun.objects.select_related('material', 'location', 'product_batch').prefetch_related(
                Prefetch('components', queryset=ProductionComponent.objects.select_related(
                    'material', 'raw_material_batch'
                )),
                Prefetch('allocations', queryset=ProductionRunAllocation.objects.select_related(
                    'order_line__order__client', 'order_line__material'
                )),
            ), pk=pk
        )
        allocation_form = ProductionRunAllocationForm(production_run=run)
        component_formset = ProductionComponentFormSet(instance=run, prefix='comp')
        return render(request, 'production_runs/detail.html', {
            'run':               run,
            'allocation_form':   allocation_form,
            'component_formset': component_formset,
        })

    def post(self, request, pk):
        run = get_object_or_404(ProductionRun, pk=pk)
        action = request.POST.get('action')

        if action == 'update_status':
            new_status = request.POST.get('status')
            if new_status in dict(ProductionRun.STATUS_CHOICES):
                if new_status == 'ACTIVE' and not run.actual_start:
                    run.actual_start = timezone.now().date()
                if new_status == 'COMPLETED' and not run.actual_end:
                    run.actual_end = timezone.now().date()
                run.status = new_status
                run.save()
                messages.success(request, f'Run status updated to {run.get_status_display()}.')

        elif action == 'add_allocation':
            form = ProductionRunAllocationForm(request.POST, production_run=run)
            if form.is_valid():
                allocation = form.save(commit=False)
                allocation.production_run = run
                try:
                    allocation.save()
                    messages.success(request, 'Allocation added.')
                except ValidationError as e:
                    messages.error(request, e.message)
            else:
                for errs in form.errors.values():
                    for e in errs:
                        messages.error(request, e)

        elif action == 'save_components':
            formset = ProductionComponentFormSet(request.POST, instance=run, prefix='comp')
            if formset.is_valid():
                formset.save()
                messages.success(request, 'Components saved.')
            else:
                for form in formset:
                    for errs in form.errors.values():
                        for e in errs:
                            messages.error(request, e)

        return redirect('production-run-detail', pk=pk)


class ProductionRunCreateView(View):
    def get(self, request):
        form      = ProductionRunForm()
        formset   = ProductionComponentFormSet(prefix='comp')
        # Pre-fill material if coming from an order line
        if request.GET.get('material'):
            form.initial['material'] = request.GET['material']
        return render(request, 'production_runs/form.html', {
            'form': form, 'formset': formset,
            'form_title': 'New Production Run', 'submit_label': 'Create Run'
        })

    def post(self, request):
        form    = ProductionRunForm(request.POST)
        formset = ProductionComponentFormSet(request.POST, prefix='comp')
        if form.is_valid() and formset.is_valid():
            run = form.save()
            formset.instance = run
            formset.save()
            messages.success(request, f'Production run {run.reference} created.')
            return redirect('production-run-detail', pk=run.pk)
        return render(request, 'production_runs/form.html', {
            'form': form, 'formset': formset,
            'form_title': 'New Production Run', 'submit_label': 'Create Run'
        })


class ProductionRunEditView(View):
    def get(self, request, pk):
        run = get_object_or_404(ProductionRun, pk=pk)
        return render(request, 'production_runs/form.html', {
            'form': ProductionRunForm(instance=run),
            'formset': ProductionComponentFormSet(instance=run, prefix='comp'),
            'form_title': f'Edit Run: {run.reference}', 'submit_label': 'Save Changes',
            'run': run,
        })

    def post(self, request, pk):
        run     = get_object_or_404(ProductionRun, pk=pk)
        form    = ProductionRunForm(request.POST, instance=run)
        formset = ProductionComponentFormSet(request.POST, instance=run, prefix='comp')
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, 'Production run updated.')
            return redirect('production-run-detail', pk=pk)
        return render(request, 'production_runs/form.html', {
            'form': form, 'formset': formset,
            'form_title': f'Edit Run: {run.reference}', 'submit_label': 'Save Changes',
            'run': run,
        })


class ProductionRunDeleteView(View):
    def post(self, request, pk):
        run = get_object_or_404(ProductionRun, pk=pk)
        ref = run.reference
        try:
            run.delete()
            messages.success(request, f'Production run "{ref}" deleted.')
        except Exception:
            messages.error(request, f'Cannot delete "{ref}".')
        return redirect('production-run-list')


class ProductionRunAllocationDeleteView(View):
    def post(self, request, pk):
        alloc = get_object_or_404(ProductionRunAllocation, pk=pk)
        run_pk = alloc.production_run.pk
        alloc.delete()
        messages.success(request, 'Allocation removed.')
        return redirect('production-run-detail', pk=run_pk)


class ProductionComponentUpdateView(View):
    """Quick status update for a single component — used from the run detail page."""
    def post(self, request, pk):
        component = get_object_or_404(ProductionComponent, pk=pk)
        new_status = request.POST.get('status')
        if new_status in dict(ProductionComponent.STATUS_CHOICES):
            component.status = new_status
            if new_status in ('IN_WAREHOUSE', 'RESERVED', 'CONSUMED') and not component.actual_date:
                component.actual_date = timezone.now().date()
            component.save()
            messages.success(request, f'{component.material.name} status updated to {component.get_status_display()}.')
        return redirect('production-run-detail', pk=component.production_run.pk)


# ─────────────────────────────────────────────
# WORKFLOW TASKS
# ─────────────────────────────────────────────

class WorkflowTaskListView(View):
    def get(self, request):
        qs = WorkflowTask.objects.select_related(
            'location', 'raw_material_batch', 'product_batch', 'production_run'
        ).all()
        status_filter = request.GET.get('status', '').upper()
        location_id   = request.GET.get('location_id')
        q             = request.GET.get('q', '').strip()
        if status_filter:
            qs = qs.filter(status=status_filter)
        if location_id:
            qs = qs.filter(location_id=location_id)
        if q:
            qs = qs.filter(description__icontains=q)
        paginator = Paginator(qs.order_by('status', 'expected_completion'), 25)
        return render(request, 'workflow_tasks/list.html', {
            'tasks':         paginator.get_page(request.GET.get('page')),
            'all_locations': Location.objects.order_by('name'),
        })


class WorkflowTaskCreateView(View):
    def get(self, request):
        return render(request, 'workflow_tasks/form.html', {
            'form': WorkflowTaskForm(), 'form_title': 'New Task', 'submit_label': 'Create Task'
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
                'location', 'raw_material_batch__material',
                'product_batch__material', 'production_run'
            ), pk=pk
        )
        return render(request, 'workflow_tasks/detail.html', {'task': task})


class WorkflowTaskEditView(View):
    def get(self, request, pk):
        task = get_object_or_404(WorkflowTask, pk=pk)
        return render(request, 'workflow_tasks/form.html', {
            'form': WorkflowTaskForm(instance=task),
            'form_title': f'Edit Task #{task.pk}', 'submit_label': 'Save Changes'
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
    def post(self, request, pk):
        task = get_object_or_404(WorkflowTask, pk=pk)
        new_status = request.POST.get('status')
        if new_status in ('PENDING', 'IN_PROGRESS', 'DONE'):
            task.status = new_status
            if new_status == 'DONE' and not task.actual_completion:
                task.actual_completion = timezone.now().date()
            task.save()
            messages.success(request, f'Task marked as {task.get_status_display()}.')
        next_url = request.POST.get('next') or request.META.get('HTTP_REFERER')
        return redirect(next_url or 'workflow-task-list')
