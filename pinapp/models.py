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


class PendingPin(models.Model):
    """Stores a product and generated AI copy while waiting for the user to reply with their affiliate link."""
    chat_id = models.CharField(max_length=64, db_index=True)
    asin = models.CharField(max_length=20)
    title = models.CharField(max_length=500)
    original_url = models.URLField(max_length=1000)
    image_url = models.URLField(max_length=1000)
    topic = models.CharField(max_length=200, blank=True, default="")
    # AI generated copy
    pin_title = models.CharField(max_length=200)
    pin_description = models.TextField()
    pin_alt_text = models.TextField()
    board_name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pending for {self.chat_id}: {self.asin}"
