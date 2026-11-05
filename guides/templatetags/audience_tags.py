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
    opens the post (after an important change: a strong „Обновено“ until it opens it again); a venue
    manager sees „Потвърдете прочитане“ until the venue confirms it (stats.reading.unread); editors
    see „Ново“ for 7 days. A light „Обновено“ for 7 days after a later change, for everybody."""
    from stats.reading import confirms, unread_ids
    from venues.access import is_reader

    from ..changes import recent

    request = context.get("request")
    if request is not None and is_reader(request.user):
        if guide.pk in unread_ids(request):
            if guide.needs_ack and confirms(request.user):
                return "ack", "Потвърдете прочитане"
            return ("new", "Обновено") if guide.pk in recent(request) else ("new", "Ново")
    elif guide.is_new:
        return "new", "Ново"
    return ("updated", "Обновено") if guide.is_updated else None


@register.simple_tag(takes_context=True)
def important_change(context, guide):
    """The post's important change of the last UNREAD_DAYS (GuideChange: note, at), or None."""
    from ..changes import recent

    request = context.get("request")
    return recent(request).get(guide.pk) if request is not None else None


@register.filter
def audience_summary(guide):
    return audience.summary(guide)
