from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from django.utils import timezone

from guides.audience import visible_guides
from venues.access import is_reader

from .models import Vote
from .reading import confirm, confirms
from .tracking import count_vote, counted_reader

# „Не“ is only taken with a few words on what was missing (also checked in infohub.js).
REASON_MIN_LENGTH = 5
REASON_MAX_LENGTH = 500
REASON_NEEDED = "Напишете накратко какво липсваше или не беше ясно – без това отговорът „Не“ не се изпраща."


@require_POST
def feedback(request, pk):
    """„Помогна ли ви тази публикация?“ Да / Не at the bottom of a guide. „Не“ needs a reason."""
    guide = get_object_or_404(visible_guides(request.user), pk=pk)
    answer = request.POST.get("helpful")
    if answer not in ("yes", "no"):
        return HttpResponseBadRequest()
    ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
    reason = " ".join(request.POST.get("reason", "").split())[:REASON_MAX_LENGTH] if answer == "no" else ""
    if answer == "no" and len(reason) < REASON_MIN_LENGTH:
        if ajax:
            return JsonResponse({"error": REASON_NEEDED}, status=400)
        return redirect(f"{guide.url}?feedback=no#feedback")  # without JavaScript: the reason box, open
    # One answer per venue account and guide; a second one (other tab, back button) is ignored.
    if is_reader(request.user):
        _, created = Vote.objects.get_or_create(
            guide=guide, user=request.user,
            defaults={"helpful": answer == "yes", "reason": reason, "day": timezone.localdate()},
        )
        me = counted_reader(request)
        if created and me:
            count_vote(guide, answer == "yes", me)
    if ajax:
        return JsonResponse({"ok": True})
    return redirect(f"{guide.url}?thanks={answer}#feedback")


@require_POST
def acknowledge(request, pk):
    """„Прочетох и запознах екипа“ under a post that asks for it: a venue manager confirms for the venue."""
    guide = get_object_or_404(visible_guides(request.user), pk=pk, needs_ack=True)
    if confirms(request.user):  # staff (the shared account) and editors have no button: ignored
        confirm(guide, request.user)
    return redirect(f"{guide.url}#ack")
