from django.urls import path
from . import views

urlpatterns = [

    # Dashboard
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Units
    path('units/',                views.UnitListView.as_view(),   name='unit-list'),
    path('units/create/',         views.UnitCreateView.as_view(), name='unit-create'),
    path('units/<int:pk>/edit/',  views.UnitEditView.as_view(),   name='unit-edit'),
    path('units/<int:pk>/delete/',views.UnitDeleteView.as_view(), name='unit-delete'),

    # Locations
    path('locations/',                  views.LocationListView.as_view(),   name='location-list'),
    path('locations/create/',           views.LocationCreateView.as_view(), name='location-create'),
    path('locations/<int:pk>/edit/',    views.LocationEditView.as_view(),   name='location-edit'),
    path('locations/<int:pk>/delete/',  views.LocationDeleteView.as_view(), name='location-delete'),

    # Materials
    path('materials/',                  views.MaterialListView.as_view(),   name='material-list'),
    path('materials/create/',           views.MaterialCreateView.as_view(), name='material-create'),
    path('materials/<int:pk>/',         views.MaterialDetailView.as_view(), name='material-detail'),
    path('materials/<int:pk>/edit/',    views.MaterialEditView.as_view(),   name='material-edit'),
    path('materials/<int:pk>/delete/',  views.MaterialDeleteView.as_view(), name='material-delete'),

    # Service actions — must come BEFORE batches/<int:pk>/ to avoid ambiguity
    path('batches/reserve/',  views.ReserveMaterialView.as_view(), name='reserve-material'),
    path('batches/consume/',  views.ConsumeMaterialView.as_view(), name='consume-material'),
    path('batches/release/',  views.ReleaseMaterialView.as_view(), name='release-material'),

    # Raw Material Batches
    path('batches/',                  views.RawMaterialBatchListView.as_view(),   name='batch-list'),
    path('batches/create/',           views.RawMaterialBatchCreateView.as_view(), name='batch-create'),
    path('batches/<int:pk>/',         views.RawMaterialBatchDetailView.as_view(), name='batch-detail'),
    path('batches/<int:pk>/delete/',  views.RawMaterialBatchDeleteView.as_view(), name='batch-delete'),

    # Manufacturing Orders
    path('manufacturing-orders/',               views.ManufacturingOrderListView.as_view(),   name='manufacturing-order-list'),
    path('manufacturing-orders/create/',        views.ManufacturingOrderCreateView.as_view(), name='manufacturing-order-create'),
    path('manufacturing-orders/<int:pk>/',      views.ManufacturingOrderDetailView.as_view(), name='manufacturing-order-detail'),

    # Product Batches
    path('product-batches/',                views.ProductBatchListView.as_view(),   name='product-batch-list'),
    path('product-batches/create/',         views.ProductBatchCreateView.as_view(), name='product-batch-create'),
    path('product-batches/<int:pk>/',       views.ProductBatchDetailView.as_view(), name='product-batch-detail'),
    path('product-batches/<int:pk>/delete/',views.ProductBatchDeleteView.as_view(), name='product-batch-delete'),

    # Transactions (read-only ledger)
    path('transactions/', views.MaterialTransactionListView.as_view(), name='transaction-list'),

    # Workflow Tasks
    path('tasks/',                      views.WorkflowTaskListView.as_view(),   name='workflow-task-list'),
    path('tasks/create/',               views.WorkflowTaskCreateView.as_view(), name='workflow-task-create'),
    path('tasks/<int:pk>/',             views.WorkflowTaskDetailView.as_view(), name='workflow-task-detail'),
    path('tasks/<int:pk>/edit/',        views.WorkflowTaskEditView.as_view(),   name='workflow-task-edit'),
    path('tasks/<int:pk>/delete/',      views.WorkflowTaskDeleteView.as_view(), name='workflow-task-delete'),
    path('tasks/<int:pk>/status/',      views.WorkflowTaskStatusView.as_view(), name='workflow-task-status'),
]
