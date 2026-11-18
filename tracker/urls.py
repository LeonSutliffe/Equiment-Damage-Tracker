from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("items/", views.item_list, name="item_list"),
    path("items/new/", views.item_create, name="item_create"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("items/<int:pk>/edit/", views.item_edit, name="item_edit"),
    path("items/<int:pk>/history/", views.item_timeline, name="item_timeline"),
    path("items/<int:pk>/history/<str:field>/", views.item_history, name="item_history"),
    path("items/<int:pk>/write-off/", views.item_write_off, name="item_write_off"),
    path("items/<int:pk>/reinstate/", views.item_reinstate, name="item_reinstate"),
    path("items/<int:item_pk>/tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/open/", views.open_tickets, name="open_tickets"),
    path("tickets/bulk/", views.bulk_tickets, name="bulk_tickets"),
    path("tickets/<int:number>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:number>/comments/", views.comment_add, name="comment_add"),
    path("tickets/<int:number>/history/<str:field>/", views.ticket_history, name="ticket_history"),
    path("photos/<int:pk>/", views.photo_view, name="photo_view"),
    path("photos/<int:pk>/thumb/", views.photo_thumb, name="photo_thumb"),
    path("photos/<int:pk>/remove/", views.photo_remove, name="photo_remove"),
    path("reports/", views.reports, name="reports"),
    path("item-types/", views.item_type_list, name="item_type_list"),
    path("item-types/new/", views.item_type_edit, name="item_type_create"),
    path("item-types/<int:pk>/", views.item_type_edit, name="item_type_edit"),
]
