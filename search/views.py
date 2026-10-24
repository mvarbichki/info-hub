from django.template.response import TemplateResponse

from guides.audience import visible_guides
from guides.models import GuidePage, paginate

# Longer queries are cut (stats.tracking stores searches up to the same length).
QUERY_MAX_LENGTH = 100


def matching_guides(query, guides=None):
    """Published guides (of `guides`, default all live ones) containing every word of the query.

    Bulgarian words change their endings ("принтер", "принтера", "принтерът"), so
    plain substring matching finds more of what staff are looking for than
    whole-word full-text search. Every word in the query must appear somewhere
    in the guide.
    """
    guides = GuidePage.objects.live() if guides is None else guides
    for word in query.lower().split():
        guides = guides.filter(search_text__contains=word)
    return guides


def search(request):
    """Matches in the title come first, then the most recently updated. Only posts the user may see."""
    from stats.tracking import count_search, counted_reader

    query = request.GET.get("q", "").strip()[:QUERY_MAX_LENGTH]
    words = query.lower().split()

    results = []
    if words:
        guides = matching_guides(query, visible_guides(request.user)).order_by("-last_published_at")
        results = sorted(guides, key=lambda g: not all(w in g.title.lower() for w in words))
        # Count the search once, not again for every page of results.
        me = counted_reader(request)
        if me and request.GET.get("page", "1") == "1":
            count_search(query, len(results), me)

    return TemplateResponse(
        request,
        "search/search.html",
        {"search_query": query, "result_count": len(results), "search_results": paginate(request, results)},
    )
