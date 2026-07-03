from django.urls import path
from . import views

urlpatterns = [
    # Client Order Board
    path('client-order-board/', views.ClientOrderBoardView.as_view(), name='client-order-board'),

    # Carriers
    path('carriers/', views.CarrierListView.as_view(), name='carrier-list'),
    path('carriers/create/', views.CarrierCreateView.as_view(), name='carrier-create'),
    path('carriers/<int:pk>/edit/', views.CarrierEditView.as_view(), name='carrier-edit'),
    path('carriers/<int:pk>/delete/', views.CarrierDeleteView.as_view(), name='carrier-delete'),

    # Suppliers
    path('suppliers/', views.SupplierListView.as_view(), name='supplier-list'),
    path('suppliers/create/', views.SupplierCreateView.as_view(), name='supplier-create'),
    path('suppliers/<int:pk>/edit/', views.SupplierEditView.as_view(), name='supplier-edit'),
    path('suppliers/<int:pk>/delete/', views.SupplierDeleteView.as_view(), name='supplier-delete'),

    # Supply Orders
    path('supply-orders/', views.SupplyOrderListView.as_view(), name='supply-order-list'),
    path('supply-order-board/', views.SupplyOrderBoardView.as_view(), name='supply-order-board'),
    path('supply-orders/create/', views.SupplyOrderCreateView.as_view(), name='supply-order-create'),
    path('supply-orders/<int:pk>/', views.SupplyOrderDetailView.as_view(), name='supply-order-detail'),
    path('supply-orders/<int:pk>/edit/', views.SupplyOrderEditView.as_view(), name='supply-order-edit'),
    path('supply-orders/<int:pk>/delete/', views.SupplyOrderDeleteView.as_view(), name='supply-order-delete'),


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
    path('batches/<int:pk>/edit/',     views.RawMaterialBatchEditView.as_view(),   name='batch-edit'),
    path('batches/<int:pk>/delete/',   views.RawMaterialBatchDeleteView.as_view(), name='batch-delete'),

    # Product Batches
    path('product-batches/',                  views.ProductBatchListView.as_view(),   name='product-batch-list'),
    path('product-batches/create/',           views.ProductBatchCreateView.as_view(), name='product-batch-create'),
    path('product-batches/<int:pk>/',         views.ProductBatchDetailView.as_view(), name='product-batch-detail'),
    path('product-batches/<int:pk>/edit/',   views.ProductBatchEditView.as_view(),   name='product-batch-edit'),
    path('product-batches/<int:pk>/delete/',  views.ProductBatchDeleteView.as_view(), name='product-batch-delete'),

    # Transactions (read-only ledger)

    # Clients
    path('clients/',                  views.ClientListView.as_view(),   name='client-list'),
    path('clients/<int:pk>/',         views.ClientDetailView.as_view(),  name='client-detail'),
    path('clients/create/',           views.ClientCreateView.as_view(), name='client-create'),
    path('clients/<int:pk>/edit/',    views.ClientEditView.as_view(),   name='client-edit'),
    path('clients/<int:pk>/delete/',  views.ClientDeleteView.as_view(), name='client-delete'),

    # Client Orders
    path('shipped/', views.ShippedOrdersListView.as_view(), name='shipped-orders'),
    path('orders/',                  views.ClientOrderListView.as_view(),   name='order-list'),
    path('orders/create/',           views.ClientOrderCreateView.as_view(), name='order-create'),
    path('orders/<int:pk>/',         views.ClientOrderDetailView.as_view(), name='order-detail'),
    path('orders/<int:pk>/edit/',    views.ClientOrderEditView.as_view(),   name='order-edit'),
    path('orders/<int:pk>/delete/',  views.ClientOrderDeleteView.as_view(), name='order-delete'),

    # Production Runs
    path('production-runs/',                views.ProductionRunListView.as_view(),   name='production-run-list'),
    path('production-runs/template-lookup/', views.ProductionTemplateLookupView.as_view(), name='production-template-lookup'),
    path('production-runs/create/',         views.ProductionRunCreateView.as_view(), name='production-run-create'),
    path('production-runs/<int:pk>/',       views.ProductionRunDetailView.as_view(), name='production-run-detail'),
    path('production-runs/<int:pk>/edit/',  views.ProductionRunEditView.as_view(),   name='production-run-edit'),
    path('production-runs/<int:pk>/copy/',   views.ProductionRunCopyView.as_view(),   name='production-run-copy'),
    path('production-runs/<int:pk>/delete/', views.ProductionRunDeleteView.as_view(), name='production-run-delete'),

    # Production sub-resources
    path('production-runs/allocations/<int:pk>/delete/',
         views.ProductionRunAllocationDeleteView.as_view(), name='allocation-delete'),
    path('production-runs/components/<int:pk>/delete/',
         views.ProductionComponentDeleteView.as_view(), name='component-delete'),
    path('production-runs/components/<int:pk>/status/',
         views.ProductionComponentUpdateView.as_view(), name='component-status'),


    # Production Board (Kanban) + Shipment history
    path('board/',    views.ProductionBoardView.as_view(),   name='production-board'),
    path('shipped/',  views.ShipmentHistoryView.as_view(),   name='shipment-history'),
]
