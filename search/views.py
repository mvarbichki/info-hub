from functools import reduce
from operator import or_

from django.db.models import Q
from django.template.response import TemplateResponse

from guides.audience import visible_guides
from guides.models import GuidePage, paginate

from .variants import close_words, spellings, vocabulary

# Longer queries are cut (stats.tracking stores searches up to the same length).
QUERY_MAX_LENGTH = 100


def matching_guides(query, guides=None):
    """Published guides (of `guides`, default all live ones) containing every word of the query.

    Bulgarian words change their endings ("принтер", "принтера", "принтерът"), so
    plain substring matching finds more of what staff are looking for than
    whole-word full-text search. Every word in the query must appear somewhere
    in the guide (as typed, or as meant: see search_terms).
    """
    guides = GuidePage.objects.live() if guides is None else guides
    for options in search_terms(query, guides):
        guides = guides.filter(_contains_any(options))
    return guides


def search_terms(query, guides):
    """For every word of the query, what to look for. The word as typed if any of `guides` has it;
    else how it reads in the other keyboard layout or in Cyrillic ("ghbynth", "printer" -> "принтер");
    else close words from the posts (typos: "принетр" -> "принтер…")."""
    terms, words = [], None
    for word in query.lower().split():
        if guides.filter(search_text__contains=word).exists():
            terms.append([word])
            continue
        options = [w for w in spellings(word)[1:] if guides.filter(search_text__contains=w).exists()]
        if not options:
            if words is None:
                words = vocabulary(guides.values_list("search_text", flat=True))
            options = [close for w in spellings(word) for close in close_words(w, words)]
        terms.append(list(dict.fromkeys(options)) or [word])
    return terms


def _contains_any(options):
    return reduce(or_, (Q(search_text__contains=option) for option in options))


def search(request):
    """Matches in the title come first, then the most recently updated. Only posts the user may see."""
    from stats.tracking import count_search, counted_reader

    query = request.GET.get("q", "").strip()[:QUERY_MAX_LENGTH]
    words = query.lower().split()

    results, meant = [], ""
    if words:
        visible = visible_guides(request.user)
        terms = search_terms(query, visible)
        guides = visible
        for options in terms:
            guides = guides.filter(_contains_any(options))
        guides = guides.order_by("-last_published_at")
        results = sorted(guides, key=lambda g: not all(any(o in g.title.lower() for o in options) for options in terms))
        if results and [options[0] for options in terms] != words:
            meant = " ".join(options[0] for options in terms)  # „Показани са резултати за …“
        # Count the search once, not again for every page of results.
        me = counted_reader(request)
        if me and request.GET.get("page", "1") == "1":
            count_search(query, len(results), me)

    return TemplateResponse(
        request,
        "search/search.html",
        {"search_query": query, "meant": meant, "result_count": len(results), "search_results": paginate(request, results)},
    )
