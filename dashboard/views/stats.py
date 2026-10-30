"""The Статистика tab."""

from functools import reduce
from operator import or_

from django.core.paginator import Paginator
from django.template.response import TemplateResponse

from guides.models import GuidePage
from stats.reports import failed_searches, guide_report, no_reasons, top_searches, venue_report
from venues.models import Venue

from .common import editor_required, head_context


STATS_PERIODS = (7, 30, 90)


@editor_required
def stats(request):
    """What staff search for (also what they don't find) and how the department's posts are doing."""
    days = next((d for d in STATS_PERIODS if request.GET.get("days") == str(d)), 30)
    context = head_context(request)
    departments = context["departments"]
    guides = GuidePage.objects.live()
    if not request.user.is_superuser:
        guides = guides.filter(reduce(or_, (guides.descendant_of_q(d) for d in departments)))
    department_id = request.GET.get("department", "")
    department = next((d for d in departments if str(d.pk) == department_id), None)
    if department:
        guides = guides.descendant_of(department)
    venues = list(Venue.objects.filter(is_training=False))
    venue_id = request.GET.get("venue", "")
    venue = next((v for v in venues if str(v.pk) == venue_id), None)

    context.update({
        "days": days,
        "periods": STATS_PERIODS,
        "department_id": department_id,
        "venues": venues,
        "venue": venue,
        "venue_id": venue_id,
        "venue_rows": None if venue else venue_report(venues, days, None if request.user.is_superuser else guides),
        "failed": failed_searches(days, venue=venue),
        "searches": top_searches(days, limit=15, venue=venue),
        "reasons": no_reasons(guides, days, venue),
        "guides": Paginator(guide_report(guides, days, venue), 50).get_page(request.GET.get("page")),
        "page_params": f"days={days}&department={department_id}&venue={venue_id}",
    })
    return TemplateResponse(request, "dashboard/stats.html", context)
