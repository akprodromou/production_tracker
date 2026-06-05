from django import forms
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from django.db.models import Sum
from django.db.models.functions import Coalesce
from django.db.models import DecimalField

from .models import (
    Unit, Location, Material, RawMaterialBatch,
    ProductBatch, MaterialTransaction,
    Client, ClientOrder, ClientOrderLine,
    ProductionRun, ProductionRunAllocation, ProductionComponent
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
        self.fields['material'].queryset = Material.objects.filter(
            category__in=('RAW', 'PKG')
        )

    def clean_lot_number(self):
        lot = self.cleaned_data['lot_number'].strip()
        material = self.cleaned_data.get('material')
        if material:
            qs = RawMaterialBatch.objects.filter(
                lot_number__iexact=lot, material=material
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(
                    f"Lot number '{lot}' already exists for this material."
                )
        return lot

    def clean_total_quantity(self):
        qty = self.cleaned_data['total_quantity']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Total quantity must be greater than zero.")
        return qty


# ─────────────────────────────────────────────
# PRODUCT BATCH
# ─────────────────────────────────────────────

class ProductBatchForm(forms.ModelForm):
    class Meta:
        model = ProductBatch
        fields = ['material', 'batch_number', 'quantity_produced', 'location']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
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
# MATERIAL TRANSACTION
# ─────────────────────────────────────────────

class MaterialTransactionForm(forms.ModelForm):
    class Meta:
        model = MaterialTransaction
        fields = ['product_batch', 'transaction_type', 'quantity', 'reference']

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

        if tx_type in ('RESERVED', 'CONSUMED') and not product_batch:
            self.add_error('product_batch', "Product batch is required for RESERVED and CONSUMED transactions.")
        if tx_type == 'PRODUCED' and product_batch:
            self.add_error('product_batch', "PRODUCED transactions must not reference a product batch.")

        if tx_type == 'RESERVED' and raw_batch and cleaned.get('quantity'):
            qty = cleaned['quantity']
            if raw_batch.available_quantity < qty:
                raise forms.ValidationError(
                    f"Insufficient available stock. Available: {raw_batch.available_quantity}, requested: {qty}."
                )

        if tx_type == 'CONSUMED' and raw_batch and product_batch and cleaned.get('quantity'):
            qty = cleaned['quantity']
            reserved = raw_batch.transactions.filter(
                product_batch=product_batch, transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            consumed = raw_batch.transactions.filter(
                product_batch=product_batch, transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            if qty > (reserved - consumed):
                raise forms.ValidationError(f"Cannot consume more than remaining reserved ({reserved - consumed}).")

        if tx_type == 'RELEASED' and raw_batch and product_batch and cleaned.get('quantity'):
            qty = cleaned['quantity']
            reserved = raw_batch.transactions.filter(
                product_batch=product_batch, transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            consumed = raw_batch.transactions.filter(
                product_batch=product_batch, transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            released = raw_batch.transactions.filter(
                product_batch=product_batch, transaction_type='RELEASED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            if qty > (reserved - consumed - released):
                raise forms.ValidationError("Cannot release more than remaining reserved.")

        return cleaned


# ─────────────────────────────────────────────
# SERVICE ACTION FORMS
# ─────────────────────────────────────────────

class ReserveMaterialForm(forms.Form):
    batch_id = forms.IntegerField(min_value=1)
    product_batch_id = forms.IntegerField(min_value=1)
    quantity = forms.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('batch_id') and cleaned.get('quantity'):
            try:
                batch = RawMaterialBatch.objects.get(pk=cleaned['batch_id'])
            except RawMaterialBatch.DoesNotExist:
                raise forms.ValidationError("Raw material batch not found.")
            if batch.available_quantity < cleaned['quantity']:
                raise forms.ValidationError(
                    f"Not enough stock. Available: {batch.available_quantity}, requested: {cleaned['quantity']}."
                )
            cleaned['batch'] = batch
        if cleaned.get('product_batch_id'):
            try:
                cleaned['product_batch'] = ProductBatch.objects.get(pk=cleaned['product_batch_id'])
            except ProductBatch.DoesNotExist:
                raise forms.ValidationError("Product batch not found.")
        return cleaned


class ConsumeMaterialForm(forms.Form):
    batch_id = forms.IntegerField(min_value=1)
    product_batch_id = forms.IntegerField(min_value=1)
    quantity = forms.DecimalField(max_digits=15, decimal_places=3, min_value=Decimal('0.001'))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('batch_id') and cleaned.get('product_batch_id') and cleaned.get('quantity'):
            try:
                batch = RawMaterialBatch.objects.get(pk=cleaned['batch_id'])
            except RawMaterialBatch.DoesNotExist:
                raise forms.ValidationError("Raw material batch not found.")
            try:
                product_batch = ProductBatch.objects.get(pk=cleaned['product_batch_id'])
            except ProductBatch.DoesNotExist:
                raise forms.ValidationError("Product batch not found.")
            reserved = batch.transactions.filter(
                product_batch=product_batch, transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            consumed = batch.transactions.filter(
                product_batch=product_batch, transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            remaining = reserved - consumed
            if cleaned['quantity'] > remaining:
                raise forms.ValidationError(
                    f"Cannot consume more than remaining reserved ({remaining})."
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
        if cleaned.get('batch_id') and cleaned.get('product_batch_id') and cleaned.get('quantity'):
            try:
                batch = RawMaterialBatch.objects.get(pk=cleaned['batch_id'])
            except RawMaterialBatch.DoesNotExist:
                raise forms.ValidationError("Raw material batch not found.")
            try:
                product_batch = ProductBatch.objects.get(pk=cleaned['product_batch_id'])
            except ProductBatch.DoesNotExist:
                raise forms.ValidationError("Product batch not found.")
            reserved = batch.transactions.filter(
                product_batch=product_batch, transaction_type='RESERVED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            consumed = batch.transactions.filter(
                product_batch=product_batch, transaction_type='CONSUMED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            released = batch.transactions.filter(
                product_batch=product_batch, transaction_type='RELEASED'
            ).aggregate(total=Coalesce(Sum('quantity'), Decimal('0'), output_field=DecimalField()))['total']
            remaining = reserved - consumed - released
            if cleaned['quantity'] > remaining:
                raise forms.ValidationError(f"Cannot release more than remaining reserved ({remaining}).")
            cleaned['batch'] = batch
            cleaned['product_batch'] = product_batch
        return cleaned


# ─────────────────────────────────────────────
# CLIENT & ORDERS
# ─────────────────────────────────────────────

class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['code', 'name', 'tin', 'country', 'notes']

    def clean_name(self):
        return self.cleaned_data['name'].strip()

    def clean_code(self):
        return self.cleaned_data['code'].strip()

class ClientOrderForm(forms.ModelForm):
    class Meta:
        model = ClientOrder
        fields = ['reference', 'client', 'order_date', 'required_by', 'notes']
        widgets = {
            'order_date':  forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'required_by': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def clean_reference(self):
        ref = self.cleaned_data['reference'].strip()
        qs = ClientOrder.objects.filter(reference__iexact=ref)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Order reference '{ref}' already exists.")
        return ref


class ClientOrderLineForm(forms.ModelForm):
    class Meta:
        model = ClientOrderLine
        fields = ['material', 'quantity_ordered', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material'].queryset = Material.objects.filter(category='FIN')

    def clean_quantity_ordered(self):
        qty = self.cleaned_data['quantity_ordered']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Quantity must be positive.")
        return qty


ClientOrderLineFormSet = forms.inlineformset_factory(
    ClientOrder,
    ClientOrderLine,
    form=ClientOrderLineForm,
    extra=0,
    can_delete=True,
    min_num=0,
    validate_min=False,
)


# ─────────────────────────────────────────────
# PRODUCTION RUNS
# ─────────────────────────────────────────────

class ProductionRunForm(forms.ModelForm):
    class Meta:
        model = ProductionRun
        fields = [
            'reference', 'material', 'planned_quantity',
            'planned_start', 'planned_end',
            'actual_start', 'actual_end', 'actual_quantity',
            'location', 'notes'
        ]
        widgets = {
            'planned_start': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'planned_end':   forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'actual_start':  forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'actual_end':    forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material'].queryset = Material.objects.filter(category='FIN')
        self.fields['actual_start'].required = False
        self.fields['actual_end'].required = False
        self.fields['actual_quantity'].required = False
        # Default planned_start to today on new runs only
        if not self.instance.pk:
            from django.utils import timezone
            self.fields['planned_start'].initial = timezone.now().date()

    def clean_reference(self):
        ref = self.cleaned_data['reference'].strip()
        qs = ProductionRun.objects.filter(reference__iexact=ref)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f"Production run reference '{ref}' already exists.")
        return ref

    def clean_planned_quantity(self):
        qty = self.cleaned_data['planned_quantity']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Planned quantity must be positive.")
        return qty


class ProductionRunAllocationForm(forms.ModelForm):
    class Meta:
        model = ProductionRunAllocation
        fields = ['order_line', 'quantity_allocated', 'notes']

    def __init__(self, *args, production_run=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.production_run = production_run
        # Only show lines for the matching finished product that still need fulfilment
        if production_run:
            self.fields['order_line'].queryset = ClientOrderLine.objects.filter(
                material=production_run.material
            ).exclude(status='FULFILLED').select_related('order__client')
            self.fields['order_line'].label_from_instance = lambda obj: (
                f"{obj.order.reference} / {obj.order.client.name} "
                f"— {obj.material.name} × {obj.quantity_remaining}"
            )

    def clean_quantity_allocated(self):
        qty = self.cleaned_data['quantity_allocated']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Allocated quantity must be positive.")
        return qty


class ProductionComponentForm(forms.ModelForm):
    class Meta:
        model = ProductionComponent
        fields = [
            'material', 'quantity_required',
            'expected_date', 'notes'
        ]
        widgets = {
            'expected_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material'].queryset = Material.objects.filter(category__in=['RAW', 'PKG'])
        self.fields['expected_date'].required = False

    def clean_quantity_required(self):
        qty = self.cleaned_data['quantity_required']
        if qty <= Decimal('0'):
            raise forms.ValidationError("Required quantity must be positive.")
        return qty


ProductionComponentFormSet = forms.inlineformset_factory(
    ProductionRun,
    ProductionComponent,
    form=ProductionComponentForm,
    extra=1,
    can_delete=True,
)


