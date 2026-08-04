import json
import time
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from orders.models import Order
from support.agents import run_support_agent
from .models import Conversation, Message


def chat(request, order_id):
    # Render the chat interface template and pass the order_id to it
    if request.method == "POST":
        data = json.loads(request.body)
        user_message = data.get("message", "")

        if not user_message:
            return JsonResponse({"error": "No message provided"}, status=400)

        order = get_object_or_404(Order, id=order_id, user=request.user)

        conversation, created = Conversation.objects.get_or_create(
            user=request.user, order=order)
        Message.objects.create(conversation=conversation,
                               role="user", content=user_message)

        # Send the user message to the AI agent for processing and get a response
        reply = run_support_agent(conversation.id, order.id, request.user.id)

        # Store the AI agent's response in the database
        Message.objects.create(conversation=conversation,
                               role="assistant", content=reply)

        return JsonResponse({"reply": reply})
