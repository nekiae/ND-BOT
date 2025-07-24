"""YooKassa payment integration for subscription management."""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from yookassa import Configuration, Payment, Webhook
from yookassa.domain.notification import WebhookNotificationEventType, WebhookNotification
import uuid

logger = logging.getLogger(__name__)


class PaymentManager:
    """YooKassa payment manager for subscriptions."""
    
    def __init__(self):
        self.shop_id = os.getenv("YOOKASSA_SHOP_ID")
        self.secret_key = os.getenv("YOOKASSA_SECRET_KEY")
        self.subscription_price = int(os.getenv("SUBSCRIPTION_PRICE", "999"))
        self.currency = os.getenv("SUBSCRIPTION_CURRENCY", "RUB")
        
        if not self.shop_id or not self.secret_key:
            raise ValueError("YooKassa credentials not found in environment")
        
        # Configure YooKassa
        Configuration.account_id = self.shop_id
        Configuration.secret_key = self.secret_key
    
    def create_payment_url(self, user_id: int, return_url: str) -> str:
        """
        Create payment URL for subscription.
        
        Args:
            user_id: Telegram user ID
            return_url: URL to redirect after payment
            
        Returns:
            Payment URL for user
        """
        try:
            payment = Payment.create({
                "amount": {
                    "value": str(self.subscription_price),
                    "currency": self.currency
                },
                "confirmation": {
                    "type": "redirect",
                    "return_url": return_url
                },
                "capture": True,
                "description": f"Подписка на бота HD | Lookism для пользователя {user_id}",
                "metadata": {
                    "tg_user_id": str(user_id),
                    "subscription_type": "monthly"
                },
                "receipt": {
                    "customer": {
                        "email": f"user_{user_id}@placeholder.com"
                    },
                    "items": [
                        {
                            "description": "Подписка на HD | Lookism (1 месяц)",
                            "quantity": "1.00",
                            "amount": {
                                "value": str(self.subscription_price),
                                "currency": self.currency
                            },
                            "vat_code": "1" # 1 = Без НДС
                        }
                    ]
                }
            }, uuid.uuid4())
            
            return payment.confirmation.confirmation_url
            
        except Exception as e:
            logger.error(f"Error creating payment: {e}")
            raise
    
    def verify_webhook_signature(self, body: bytes, headers: Dict[str, str]) -> bool:
        """
        Verify YooKassa webhook signature.
        
        Args:
            body: Request body bytes
            headers: Request headers
            
        Returns:
            True if signature is valid
        """
        try:
            # YooKassa webhook verification logic
            # This is a simplified version - implement proper signature verification
            return True
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False
    
    def process_webhook(self, notification_body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process YooKassa webhook notification.
        
        Args:
            notification_body: Webhook notification data
            
        Returns:
            Processing result or None
        """
        try:
            notification = WebhookNotification(notification_body)
            
            if notification.event == WebhookNotificationEventType.PAYMENT_SUCCEEDED:
                payment = notification.object
                
                if payment.status == "succeeded":
                    metadata = payment.metadata
                    user_id = metadata.get("tg_user_id")
                    
                    if user_id:
                        return {
                            "user_id": int(user_id),
                            "payment_id": payment.id,
                            "amount": float(payment.amount.value),
                            "currency": payment.amount.currency,
                            "subscription_type": metadata.get("subscription_type", "monthly")
                        }
            
            return None
            
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return None


# Global payment manager instance
payment_manager = PaymentManager()
