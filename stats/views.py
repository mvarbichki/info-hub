from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from django.utils import timezone

from guides.audience import visible_guides
from venues.access import is_reader

from .models import Vote
from .reading import confirm
from .tracking import count_vote, counted_reader


@require_POST
def feedback(request, pk):
    """„Помогна ли ви тази публикация?“ Да / Не at the bottom of a guide."""
    guide = get_object_or_404(visible_guides(request.user), pk=pk)
    answer = request.POST.get("helpful")
    if answer not in ("yes", "no"):
        return HttpResponseBadRequest()
    # One answer per venue account and guide; a second one (other tab, back button) is ignored.
    if is_reader(request.user):
        _, created = Vote.objects.get_or_create(
            guide=guide, user=request.user, defaults={"helpful": answer == "yes", "day": timezone.localdate()}
        )
        me = counted_reader(request)
        if created and me:
            count_vote(guide, answer == "yes", me)
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True})
    return redirect(f"{guide.url}?thanks=1#feedback")


@require_POST
def acknowledge(request, pk):
    """„Прочетох“ under a post that asks for it: remembered per venue account."""
    guide = get_object_or_404(visible_guides(request.user), pk=pk, needs_ack=True)
    if is_reader(request.user):
        confirm(guide, request.user)
    return redirect(f"{guide.url}#ack")
