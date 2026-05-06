# forms.py

from django import forms
from django.utils import timezone
from decimal import Decimal, InvalidOperation

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ManufacturingOrder, ProductBatch, MaterialTransaction, WorkflowTask
)


# ─────────────────────────────────────────────
# UNIT
# ─────────────────────────────────────────────

class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ['name']

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError("Unit name cannot be blank.")
        qs = Unit.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"A unit named '{name}' already exists.")
        return name


# ─────────────────────────────────────────────
# LOCATION
# ─────────────────────────────────────────────

class LocationForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name', 'is_external']

    def clean_name(self):
        name = self.cleaned_data['name'].strip()
        if not name:
            raise forms.ValidationError("Location name cannot be blank.")
        return name


# ─────────────────────────────────────────────
# MATERIAL
# ─────────────────────────────────────────────

class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ['name', 'sku', 'unit', 'category']
        widgets = {
            'category': forms.Select(choices=Material.CATEGORY_CHOICES),
        }

    def clean_sku(self):
        sku = self.cleaned_data['sku'].strip()
        qs = Material.objects.filter(sku__iexact=sku)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"SKU '{sku}' is already in use.")
        return sku

    def clean_name(self):
        return self.cleaned_data['name'].strip()


# ─────────────────────────────────────────────
# RAW MATERIAL BATCH
# ─────────────────────────────────────────────

class RawMaterialBatchForm(forms.ModelForm):
    class Meta:
        model = RawMaterialBatch
        fields = ['material', 'lot_number', 'total_quantity', 'location']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only RAW and PKG materials make sense as raw material batches
        self.fields['material'].queryset = Material.objects.filter(
            category__in=('RAW', 'PKG')
        )

    def clean_lot_number(self):
        lot = self.cleaned_data['lot_number'].strip()
        qs = RawMaterialBatch.objects.filter(lot_number__iexact=lot)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Lot number '{lot}' already exists.")
        return lot

    def clean_total_quantity(self):
        qty = self.cleaned_data['total_quantity']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Total quantity must be greater than zero.")
        return qty


# ─────────────────────────────────────────────
# MANUFACTURING ORDER
# ─────────────────────────────────────────────

class ManufacturingOrderForm(forms.ModelForm):
    class Meta:
        model = ManufacturingOrder
        fields = ['raw_material_batch']

    def clean_raw_material_batch(self):
        batch = self.cleaned_data['raw_material_batch']
        qs = ManufacturingOrder.objects.filter(raw_material_batch=batch)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                "A Manufacturing Order already exists for this batch."
            )
        return batch


class ManufacturingOrderCancelForm(forms.ModelForm):
    """Dedicated form for toggling cancellation status."""
    class Meta:
        model = ManufacturingOrder
        fields = ['is_cancelled']


# ─────────────────────────────────────────────
# PRODUCT BATCH
# ─────────────────────────────────────────────

class ProductBatchForm(forms.ModelForm):
    class Meta:
        model = ProductBatch
        fields = ['material', 'batch_number', 'quantity_produced', 'location']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Only finished products can be product batches
        self.fields['material'].queryset = Material.objects.filter(category='FIN')

    def clean_batch_number(self):
        bn = self.cleaned_data['batch_number'].strip()
        qs = ProductBatch.objects.filter(batch_number__iexact=bn)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Batch number '{bn}' already exists.")
        return bn

    def clean_quantity_produced(self):
        qty = self.cleaned_data['quantity_produced']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Quantity produced must be greater than zero.")
        return qty

    def clean_material(self):
        material = self.cleaned_data['material']
        if material.category != 'FIN':
            raise forms.ValidationError("Material must be a Finished Product (FIN).")
        return material


# ─────────────────────────────────────────────
# MATERIAL TRANSACTION  (manual / admin entry)
# ─────────────────────────────────────────────

class MaterialTransactionForm(forms.ModelForm):
    class Meta:
        model = MaterialTransaction
        fields = [
            'raw_material_batch', 'product_batch',
            'transaction_type', 'quantity', 'reference'
        ]

    def clean_quantity(self):
        qty = self.cleaned_data['quantity']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Quantity must be positive.")
        return qty

    def clean(self):
        cleaned = super().clean()
        tx_type = cleaned.get('transaction_type')
        product_batch = cleaned.get('product_batch')
        raw_batch = cleaned.get('raw_material_batch')

        # Mirror MaterialTransaction.clean() rules
        if tx_type in ('RESERVED', 'CONSUMED') and not product_batch:
            self.add_error(
                'product_batch',
                "Product batch is required for RESERVED and CONSUMED transactions."
            )

        if tx_type == 'PRODUCED' and product_batch:
            self.add_error(
                'product_batch',
                "PRODUCED transactions must not reference a product batch."
            )

        # Guard: RESERVED — check available stock
        if tx_type == 'RESERVED' and raw_batch and cleaned.get('quantity'):
            qty = cleaned['quantity']
            if raw_batch.available_quantity < qty:
                raise forms.ValidationError(
                    f"Insufficient available stock. "
                    f"Available: {raw_batch.available_quantity}, requested: {qty}."
                )

        # Guard: CONSUMED — check remaining reserved for this product batch
        if tx_type == 'CONSUMED' and raw_batch and product_batch and cleaned.get('quantity'):
            qty = cleaned['quantity']
            from django.db.models import Sum
            from django.db.models.functions import Coalesce

            reserved = raw_batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            consumed = raw_batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            remaining = reserved - consumed
            if qty > remaining:
                raise forms.ValidationError(
                    f"Cannot consume more than remaining reserved. "
                    f"Remaining reserved: {remaining}, requested: {qty}."
                )

        # Guard: RELEASED — check remaining reserved minus consumed and already released
        if tx_type == 'RELEASED' and raw_batch and product_batch and cleaned.get('quantity'):
            qty = cleaned['quantity']
            from django.db.models import Sum
            from django.db.models.functions import Coalesce

            reserved = raw_batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            consumed = raw_batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            released = raw_batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='RELEASED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            remaining = reserved - consumed - released
            if qty > remaining:
                raise forms.ValidationError(
                    f"Cannot release more than remaining reserved. "
                    f"Remaining: {remaining}, requested: {qty}."
                )

        return cleaned


# ─────────────────────────────────────────────
# SERVICE ACTION FORMS  (thin, no ModelForm)
# ─────────────────────────────────────────────

class ReserveMaterialForm(forms.Form):
    batch_id = forms.IntegerField(min_value=1)
    product_batch_id = forms.IntegerField(min_value=1)
    quantity = forms.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))

    def clean(self):
        cleaned = super().clean()
        batch_id = cleaned.get('batch_id')
        qty = cleaned.get('quantity')

        if batch_id and qty:
            try:
                batch = RawMaterialBatch.objects.get(pk=batch_id)
            except RawMaterialBatch.DoesNotExist:
                raise forms.ValidationError("Raw material batch not found.")
            if batch.available_quantity < qty:
                raise forms.ValidationError(
                    f"Not enough stock. Available: {batch.available_quantity}, requested: {qty}."
                )
            cleaned['batch'] = batch  # attach object for convenience

        if cleaned.get('product_batch_id'):
            try:
                cleaned['product_batch'] = ProductBatch.objects.get(
                    pk=cleaned['product_batch_id']
                )
            except ProductBatch.DoesNotExist:
                raise forms.ValidationError("Product batch not found.")

        return cleaned


class ConsumeMaterialForm(forms.Form):
    batch_id = forms.IntegerField(min_value=1)
    product_batch_id = forms.IntegerField(min_value=1)
    quantity = forms.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))

    def clean(self):
        cleaned = super().clean()
        batch_id = cleaned.get('batch_id')
        product_batch_id = cleaned.get('product_batch_id')
        qty = cleaned.get('quantity')

        if batch_id and product_batch_id and qty:
            try:
                batch = RawMaterialBatch.objects.get(pk=batch_id)
            except RawMaterialBatch.DoesNotExist:
                raise forms.ValidationError("Raw material batch not found.")

            try:
                product_batch = ProductBatch.objects.get(pk=product_batch_id)
            except ProductBatch.DoesNotExist:
                raise forms.ValidationError("Product batch not found.")

            from django.db.models import Sum
            from django.db.models.functions import Coalesce

            reserved = batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            consumed = batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            remaining = reserved - consumed
            if qty > remaining:
                raise forms.ValidationError(
                    f"Cannot consume more than remaining reserved. "
                    f"Remaining: {remaining}, requested: {qty}."
                )

            cleaned['batch'] = batch
            cleaned['product_batch'] = product_batch

        return cleaned


class ReleaseMaterialForm(forms.Form):
    batch_id = forms.IntegerField(min_value=1)
    product_batch_id = forms.IntegerField(min_value=1)
    quantity = forms.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))

    def clean(self):
        cleaned = super().clean()
        batch_id = cleaned.get('batch_id')
        product_batch_id = cleaned.get('product_batch_id')
        qty = cleaned.get('quantity')

        if batch_id and product_batch_id and qty:
            try:
                batch = RawMaterialBatch.objects.get(pk=batch_id)
            except RawMaterialBatch.DoesNotExist:
                raise forms.ValidationError("Raw material batch not found.")

            try:
                product_batch = ProductBatch.objects.get(pk=product_batch_id)
            except ProductBatch.DoesNotExist:
                raise forms.ValidationError("Product batch not found.")

            from django.db.models import Sum
            from django.db.models.functions import Coalesce

            reserved = batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            consumed = batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            released = batch.transactions.filter(
                product_batch=product_batch,
                transaction_type='RELEASED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0')))['total']

            remaining = reserved - consumed - released
            if qty > remaining:
                raise forms.ValidationError(
                    f"Cannot release more than remaining reserved. "
                    f"Remaining: {remaining}, requested: {qty}."
                )

            cleaned['batch'] = batch
            cleaned['product_batch'] = product_batch

        return cleaned


# ─────────────────────────────────────────────
# WORKFLOW TASK
# ─────────────────────────────────────────────

class WorkflowTaskForm(forms.ModelForm):
    class Meta:
        model = WorkflowTask
        fields = [
            'description', 'raw_material_batch', 'product_batch',
            'location', 'status', 'expected_completion', 'actual_completion'
        ]
        widgets = {
            'expected_completion': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'actual_completion': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get('status')
        actual_completion = cleaned.get('actual_completion')
        expected_completion = cleaned.get('expected_completion')

        # At least one batch context should be set
        if not cleaned.get('raw_material_batch') and not cleaned.get('product_batch'):
            raise forms.ValidationError(
                "A task must be linked to at least one batch "
                "(raw material batch or product batch)."
            )

        # Completion date logic
        if status == 'DONE' and not actual_completion:
            cleaned['actual_completion'] = timezone.now()

        if actual_completion and expected_completion:
            if actual_completion < expected_completion:
                # Allowed — just informational, not an error
                pass

        return cleaned


class WorkflowTaskStatusForm(forms.ModelForm):
    """Lightweight form for status-only updates (e.g. a Kanban move)."""
    class Meta:
        model = WorkflowTask
        fields = ['status', 'actual_completion']
        widgets = {
            'actual_completion': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
        }

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('status') == 'DONE' and not cleaned.get('actual_completion'):
            cleaned['actual_completion'] = timezone.now()
        return cleaned