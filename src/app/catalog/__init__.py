"""WhatsApp catalog ordering — a SEPARATE flow from the conversation engine.

A customer browses the connected Meta Commerce catalog inside WhatsApp, adds items
to the cart, and sends it. Meta delivers that as an ``order`` message which the
webhook routes here (never to ``conversation.engine``). This module turns the cart
into a draft order and replies asking for the delivery location.
"""
