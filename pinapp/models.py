from django.db import models


class SentProduct(models.Model):
    """Tracks products that have already been sent via the bot to avoid duplicates."""

    asin = models.CharField(
        max_length=20,
        unique=True,
        db_index=True,
        help_text="Amazon Standard Identification Number (10-char product ID).",
    )
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=500, blank=True, default="")
    topic = models.CharField(
        max_length=200,
        blank=True,
        default="",
        help_text="The trend topic that led to this product.",
    )
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.asin}: {self.title[:60]}"
