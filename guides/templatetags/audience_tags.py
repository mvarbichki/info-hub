from django import template

from guides import audience

register = template.Library()


@register.simple_tag(takes_context=True)
def audience_badge(context, guide):
    """„За вашия обект“ / „Само за управители“ (or "" for posts for everybody), for the viewing user."""
    request = context.get("request")
    return audience.badge(request.user, guide) if request else ""


@register.simple_tag(takes_context=True)
def fresh_badge(context, guide):
    """(css modifier, text) of the freshness label, or None. A venue account sees „Ново“ until it
    opens the post and „Потвърдете прочитане“ until it presses „Прочетох“ (stats.reading.unread);
    editors see „Ново“ for 7 days. „Обновено“ for 7 days after a later change, for everybody."""
    from stats.reading import unread_ids
    from venues.access import is_reader

    request = context.get("request")
    if request is not None and is_reader(request.user):
        if guide.pk in unread_ids(request):
            return ("ack", "Потвърдете прочитане") if guide.needs_ack else ("new", "Ново")
    elif guide.is_new:
        return "new", "Ново"
    return ("updated", "Обновено") if guide.is_updated else None


@register.filter
def audience_summary(guide):
    return audience.summary(guide)
