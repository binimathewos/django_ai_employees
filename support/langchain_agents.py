from django.conf import settings
from langchain_anthropic import ChatAnthropic
from langchain.agents import create_agent

from support.event_queue import publish, DONE
from .langchain_tools import get_order_details, get_refund_history, check_delivery_status, search_knowledge_base, get_customer_risk_profile
from .agents import SUPPORT_SYSTEM_PROMPT, MANAGER_SYSTEM_PROMPT, RISK_SYSTEM_PROMPT
from langgraph.checkpoint.memory import InMemorySaver
from support.models import Conversation, AgentLog
from langchain.agents.middleware import wrap_tool_call
from langchain.tools import tool

# init Anthropic Client
llm = ChatAnthropic(
    model=settings.ANTHROPIC_MODEL,
    api_key=settings.ANTHROPIC_API_KEY)


checkpointer = InMemorySaver()


def run_support_agent_langchain(user_message, conversation_id, order_id, user_id):
    conversation = Conversation.objects.get(id=conversation_id)

    @tool
    def escalate_to_manager(case_summary: str) -> dict:
        """Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately."""
        return run_manager_agent_langchain(case_summary, conversation_id)

    config = {"configurable": {"thread_id": str(conversation_id)}}

    context_message = f"[Context: This conversation is about Order #{order_id}, user: {user_id}] {user_message}"

    @wrap_tool_call
    def log_tool_calls_middleware(request, handler):
        tool_name = request.tool_call["name"]
        tool_args = request.tool_call["args"]

        # Before tool call
        tool_message = f"Calling tool {tool_name} with {tool_args}."
        publish(conversation_id, {
            "type": "tool_call", "message": tool_message})

        AgentLog.objects.create(conversation=conversation,
                                event_type="tool_call", message=tool_message)

        # Tool call
        result = handler(request)

        # After tool call
        tool_message = f"{tool_name} returned {str(result.content)[:200]}."

        publish(conversation_id, {
                "type": "tool_result", "message": tool_message})

        AgentLog.objects.create(conversation=conversation, event_type="tool_result",
                                message=tool_message)
        return result

    support_agent = create_agent(
        model=llm,
        tools=[get_order_details, get_refund_history, check_delivery_status,
               search_knowledge_base, escalate_to_manager],
        system_prompt=SUPPORT_SYSTEM_PROMPT,
        checkpointer=checkpointer,
        middleware=[log_tool_calls_middleware]
    )

    response = support_agent.invoke(
        {"messages": [{"role": "user", "content": context_message}]},
        config=config,
    )

    final_reply = extract_text(response["messages"][-1])

    publish(conversation_id, {"type": "final", "message": final_reply})

    AgentLog.objects.create(conversation=conversation,
                            event_type="final", message=final_reply)

    publish(conversation_id, DONE)
    return final_reply


def run_manager_agent_langchain(case_summary, conversation_id):
    conversation = Conversation.objects.get(id=conversation_id)

    AgentLog.objects.create(conversation=conversation,
                            event_type="manager", message=f"Case received for review: {case_summary[:200]}")

    publish(conversation_id, {
            "type": "manager", "message": f"Case received for review: {case_summary[:200]}"})

    @tool
    def assess_fraud_risk(user_id: int) -> dict:
        """Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict."""
        return run_risk_agent_langchain(user_id, conversation_id)

    @wrap_tool_call
    def log_tool_calls_middleware(request, handler):
        publish(conversation_id, {
                "type": "manager", "message": "Consulting risk agent for fraud assessment..."})
        AgentLog.objects.create(conversation=conversation, event_type="manager",
                                message="Consulting risk agent for fraud assessment...")

        return handler(request)

    manager_agent = create_agent(
        model=llm,
        tools=[assess_fraud_risk],
        system_prompt=MANAGER_SYSTEM_PROMPT,
        middleware=[log_tool_calls_middleware]
    )

    response = manager_agent.invoke(
        {"messages": [{"role": "user", "content": case_summary}]}
    )

    decision = extract_text(response["messages"][-1])

    publish(conversation_id, {"type": "manager",
                              "message": f"Decision: {decision[:200]}"})

    AgentLog.objects.create(conversation=conversation,
                            event_type="manager", message=f"Decision: {decision[:200]}")

    return decision


def run_risk_agent_langchain(user_id, conversation_id):
    conversation = Conversation.objects.get(id=conversation_id)

    publish(conversation_id, {"type": "risk",
                              "message": f"Started fraud risk assement for user: {user_id}"})

    AgentLog.objects.create(conversation=conversation,
                            event_type="risk", message=f"Started fraud risk assement for user: {user_id}")

    @wrap_tool_call
    def log_tool_calls_middleware(request, handler):
        tool_name = request.tool_call["name"]
        tool_args = request.tool_call["args"]

        publish(conversation_id, {"type": "risk",
                                  "message": f"Calling tool {tool_name} with {tool_args}."})

        AgentLog.objects.create(conversation=conversation, event_type="risk",
                                message=f"Calling tool {tool_name} with {tool_args}.")

        return handler(request)

    risk_agent = create_agent(
        model=llm,
        tools=[get_customer_risk_profile],
        system_prompt=RISK_SYSTEM_PROMPT,
        middleware=[log_tool_calls_middleware]
    )

    response = risk_agent.invoke(
        {"messages": [{"role": "user", "content": f"Please assess the fraud risk for user ID {user_id}. Use your tools to get their profile and return a verdict."}]},
    )

    verdict = extract_text(response["messages"][-1])

    publish(conversation_id, {"type": "risk",
                              "message": f"Verdict: {verdict[:200]}"})

    AgentLog.objects.create(conversation=conversation,
                            event_type="risk", message=f"Verdict: {verdict[:200]}")

    return verdict


def extract_text(message):
    content = message.content

    # Simple case: already a string
    if isinstance(content, str):
        return content

    # List of content blocks case
    if isinstance(content, list):
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)
        return "".join(text_parts)

    return str(content)
