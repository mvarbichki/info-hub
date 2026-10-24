def navigation(request):
    """Departments for the site header. Lazy, so admin pages don't pay for the query."""

    def departments():
        from .models import DepartmentPage

        return DepartmentPage.objects.live().order_by("path")

    return {"nav_departments": departments}
