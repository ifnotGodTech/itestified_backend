from django.db import models


class HomeEventType(models.TextChoices):
    # A testimony was the current item for `duration_ms` (only time it was
    # actually on screen -- not while covered or on another tab).
    ITEM_VIEWED = "item_viewed", "Item viewed"
    # The viewer swiped to another item themselves (not auto-advance).
    SWIPED = "swiped", "Swiped"
    SEARCH_RUN = "search_run", "Search run"
    RESULT_OPENED = "result_opened", "Search result opened"
    # A reaction or a comment on a testimony, from the Home feed.
    RESPONDED = "responded", "Responded"
