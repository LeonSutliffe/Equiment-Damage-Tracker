from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/password/", views.user_password, name="user_password"),
    path("roles/", views.role_list, name="role_list"),
    path("roles/new/", views.role_edit, name="role_create"),
    path("roles/<int:pk>/", views.role_edit, name="role_edit"),
    path("roles/log/", views.permission_log, name="permission_log"),
    path("audit/", views.audit_log, name="audit_log"),
]
