from django.conf import settings
from django.db import models

class CalendarEvent(models.Model):
    title = models.CharField(max_length=200)
    start = models.DateTimeField()
    end = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True, default="")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="calendar_events"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title
