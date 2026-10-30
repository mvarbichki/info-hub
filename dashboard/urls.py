from django.urls import path
from django.views.generic import RedirectView

from .views import accounts, categories, departments, history, posts, stats, users, venues

app_name = "dashboard"

urlpatterns = [
    path("", posts.index, name="index"),
    path("new/", posts.edit, name="new"),
    path("upload/", posts.upload, name="upload"),
    path("<int:pk>/", posts.edit, name="update"),
    path("<int:pk>/preview/", posts.preview, name="preview"),
    path("<int:pk>/reads/", posts.reads, name="reads"),
    path("<int:pk>/history/", history.history, name="history"),
    path("activity/", history.activity, name="activity"),
    path("<int:pk>/toggle/", posts.toggle, name="toggle"),
    path("<int:pk>/delete/", posts.delete, name="delete"),
    path("categories/", categories.categories, name="categories"),
    path("categories/<int:pk>/rename/", categories.rename_category, name="rename_category"),
    path("categories/<int:pk>/publish/", categories.publish_category, name="publish_category"),
    path("categories/<int:pk>/delete/", categories.delete_category, name="delete_category"),
    path("stats/", stats.stats, name="stats"),
    path("departments/", departments.departments, name="departments"),
    path("departments/<int:pk>/", departments.edit_department, name="edit_department"),
    path("departments/<int:pk>/move/", departments.reorder_department, name="move_department"),
    path("departments/<int:pk>/delete/", departments.remove_department, name="delete_department"),
    path("venues/", venues.venues, name="venues"),
    path("venues/<int:pk>/", venues.edit_venue, name="edit_venue"),
    path("venues/<int:pk>/toggle/", venues.toggle_venue, name="toggle_venue"),
    path("venues/<int:pk>/delete/", venues.remove_venue, name="delete_venue"),
    path("venues/passwords/", venues.password_sheet, name="password_sheet"),
    path("venues/<int:pk>/passwords/", venues.password_sheet, name="venue_password_sheet"),
    path("users/", users.users, name="users"),
    path("users/<int:pk>/", users.edit_user, name="edit_user"),
    path("users/<int:pk>/password/", users.user_password, name="user_password"),
    path("users/<int:pk>/reset-password/", users.reset_password, name="reset_password"),
    path("users/<int:pk>/toggle/", users.toggle_user, name="toggle_user"),
    path("users/<int:pk>/delete/", users.delete_user, name="delete_user"),
    path("password/", accounts.PasswordChange.as_view(), name="password"),
    # The login moved to /login/ (one login for venues and departments).
    path("login/", RedirectView.as_view(pattern_name="login", query_string=True)),
    path("logout/", accounts.Logout.as_view(), name="logout"),
]
