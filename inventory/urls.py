from django.urls import path
from . import views

urlpatterns = [

    # Dashboard
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Units
    path('units/',                 views.UnitListView.as_view(),   name='unit-list'),
    path('units/create/',          views.UnitCreateView.as_view(), name='unit-create'),
    path('units/<int:pk>/edit/',   views.UnitEditView.as_view(),   name='unit-edit'),
    path('units/<int:pk>/delete/', views.UnitDeleteView.as_view(), name='unit-delete'),

    # Locations
    path('locations/',                  views.LocationListView.as_view(),   name='location-list'),
    path('locations/create/',           views.LocationCreateView.as_view(), name='location-create'),
    path('locations/<int:pk>/',         views.LocationDetailView.as_view(), name='location-detail'),
    path('locations/<int:pk>/edit/',    views.LocationEditView.as_view(),   name='location-edit'),
    path('locations/<int:pk>/delete/',  views.LocationDeleteView.as_view(), name='location-delete'),

    # Materials
    path('materials/',                  views.MaterialListView.as_view(),   name='material-list'),
    path('materials/create/',           views.MaterialCreateView.as_view(), name='material-create'),
    path('materials/<int:pk>/',         views.MaterialDetailView.as_view(), name='material-detail'),
    path('materials/<int:pk>/edit/',    views.MaterialEditView.as_view(),   name='material-edit'),
    path('materials/<int:pk>/delete/',  views.MaterialDeleteView.as_view(), name='material-delete'),

    # Service actions — before batches/<int:pk>/ to avoid conflict
    path('batches/reserve/',  views.ReserveMaterialView.as_view(), name='reserve-material'),
    path('batches/consume/',  views.ConsumeMaterialView.as_view(), name='consume-material'),
    path('batches/release/',  views.ReleaseMaterialView.as_view(), name='release-material'),

    # Raw Material Batches
    path('batches/',                   views.RawMaterialBatchListView.as_view(),   name='batch-list'),
    path('batches/create/',            views.RawMaterialBatchCreateView.as_view(), name='batch-create'),
    path('batches/<int:pk>/',          views.RawMaterialBatchDetailView.as_view(), name='batch-detail'),
    path('batches/<int:pk>/delete/',   views.RawMaterialBatchDeleteView.as_view(), name='batch-delete'),

    # Product Batches
    path('product-batches/',                  views.ProductBatchListView.as_view(),   name='product-batch-list'),
    path('product-batches/create/',           views.ProductBatchCreateView.as_view(), name='product-batch-create'),
    path('product-batches/<int:pk>/',         views.ProductBatchDetailView.as_view(), name='product-batch-detail'),
    path('product-batches/<int:pk>/delete/',  views.ProductBatchDeleteView.as_view(), name='product-batch-delete'),

    # Transactions (read-only ledger)
    path('transactions/', views.MaterialTransactionListView.as_view(), name='transaction-list'),

    # Clients
    path('clients/',                  views.ClientListView.as_view(),   name='client-list'),
    path('clients/create/',           views.ClientCreateView.as_view(), name='client-create'),
    path('clients/<int:pk>/edit/',    views.ClientEditView.as_view(),   name='client-edit'),
    path('clients/<int:pk>/delete/',  views.ClientDeleteView.as_view(), name='client-delete'),

    # Client Orders
    path('orders/',                  views.ClientOrderListView.as_view(),   name='order-list'),
    path('orders/create/',           views.ClientOrderCreateView.as_view(), name='order-create'),
    path('orders/<int:pk>/',         views.ClientOrderDetailView.as_view(), name='order-detail'),
    path('orders/<int:pk>/edit/',    views.ClientOrderEditView.as_view(),   name='order-edit'),
    path('orders/<int:pk>/delete/',  views.ClientOrderDeleteView.as_view(), name='order-delete'),

    # Production Runs
    path('production-runs/',                views.ProductionRunListView.as_view(),   name='production-run-list'),
    path('production-runs/create/',         views.ProductionRunCreateView.as_view(), name='production-run-create'),
    path('production-runs/<int:pk>/',       views.ProductionRunDetailView.as_view(), name='production-run-detail'),
    path('production-runs/<int:pk>/edit/',  views.ProductionRunEditView.as_view(),   name='production-run-edit'),
    path('production-runs/<int:pk>/delete/', views.ProductionRunDeleteView.as_view(), name='production-run-delete'),

    # Production sub-resources
    path('production-runs/allocations/<int:pk>/delete/',
         views.ProductionRunAllocationDeleteView.as_view(), name='allocation-delete'),
    path('production-runs/components/<int:pk>/status/',
         views.ProductionComponentUpdateView.as_view(), name='component-status'),

    # Allocations table
    path('allocations/', views.AllocationListView.as_view(), name='allocation-list'),

    # Production Board (Kanban) + Shipment history
    path('board/',    views.ProductionBoardView.as_view(),   name='production-board'),
    path('shipped/',  views.ShipmentHistoryView.as_view(),   name='shipment-history'),
]
