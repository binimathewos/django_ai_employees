import json
import time
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from orders.models import Order
from support.agents import run_support_agent
from .models import Conversation, Message
from django.contrib.admin.views.decorators import staff_member_required


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


@staff_member_required
def dashboard(request):
    conversations = Conversation.objects.all().order_by("-created_at")
    context = {
        "conversations": conversations
    }
    return render(request, "support/dashboard.html", context)


def conversation_detail(request, conversation_id):
    conversation = get_object_or_404(Conversation, id=conversation_id)
    messages = conversation.messages.order_by("created_at")
    agent_logs = conversation.agent_logs.order_by("created_at")

    context = {
        "conversation": conversation,
        "messages": messages,
        "agentLogs": agent_logs
    }

    return render(request, "support/conversation_detail.html", context)
