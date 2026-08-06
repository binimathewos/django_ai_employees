import json
import time
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from orders.models import Order
from .agents import run_support_agent
from .event_queue import publish, subscribe, unsubscribe
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

        publish(conversation.id, {
                "type": "user_message", "message": user_message, "name": request.user.first_name})

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


@staff_member_required
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


@staff_member_required
def conversation_stream(request, conversation_id):
    def event_stream(conversation_id):
        q = subscribe(conversation_id)

        try:
            while True:
                event = q.get()  # wait for the next event

                yield f"data: {json.dumps(event)}\n\n"
        finally:
            unsubscribe(conversation_id, q)

    response = StreamingHttpResponse(event_stream(
        conversation_id), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"

    return response
