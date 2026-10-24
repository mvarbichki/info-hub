from django.conf import settings
from django.urls import include, path, re_path
from django.contrib.auth.decorators import login_not_required
from django.views.generic import RedirectView

from wagtail.admin import urls as wagtailadmin_urls
from wagtail import urls as wagtail_urls
from wagtail.documents import urls as wagtaildocs_urls

from dashboard.views.accounts import Login, Logout
from infohub.access import robots_txt, serve_media
from search import views as search_views
from stats import views as stats_views

urlpatterns = [
    path("login/", Login.as_view(), name="login"),
    path("robots.txt", robots_txt),
    # Uploaded pictures, videos and files: only for logged-in users (also on the server).
    re_path(r"^media/(?P<path>.+)$", serve_media, name="media"),
    # Logging out of the Wagtail admin also lands on the site's login (before the admin's own URL).
    path("admin/logout/", Logout.as_view()),
    # One login page for everything, also for the Wagtail admin.
    path("admin/login/", login_not_required(RedirectView.as_view(pattern_name="login", query_string=True))),
    path("admin/", include(wagtailadmin_urls)),
    path("documents/", include(wagtaildocs_urls)),
    path("search/", search_views.search, name="search"),
    path("feedback/<int:pk>/", stats_views.feedback, name="guide_feedback"),
    path("read/<int:pk>/", stats_views.acknowledge, name="guide_ack"),
    path("manage/", include("dashboard.urls")),
]


if settings.DEBUG:
    from django.contrib.staticfiles.urls import staticfiles_urlpatterns

    # Serve static files from development server
    urlpatterns += staticfiles_urlpatterns()

urlpatterns = urlpatterns + [
    # For anything not caught by a more specific rule above, hand over to
    # Wagtail's page serving mechanism. This should be the last pattern in
    # the list:
    path("", include(wagtail_urls)),
    # Alternatively, if you want Wagtail pages to be served from a subpath
    # of your site, rather than the site root:
    #    path("pages/", include(wagtail_urls)),
]
