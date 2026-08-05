import json
from anthropic import Anthropic
from django.conf import settings
from support.models import Conversation, Message, AgentLog
from .tools import get_order_details, get_refund_history, check_delivery_status, get_customer_risk_profile
from .event_queue import publish, DONE

client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

anthropic_model = settings.ANTHROPIC_MODEL

# Support System Prompt --> Maya's job description
SUPPORT_SYSTEM_PROMPT = """
You are Maya, a customer support agent at CoolBreeze AC.
You help customers with issues related to their AC orders.

Your responsibilities:
- Always use your tools to gather facts before responding
- Check order details when customer mentions their order
- Check refund history before making and refund decisions
- Be empathetic but honest

Your Personality:
- Friendly and professional
- Patient even when customer is angry
- Clear and concise in your replies
- No emojies

Important rules:
- Alwyas check order details first before responging
- Never approve or deny a refund yourself
- If refund decision is needed, tell customer you are checking with your team
- Never use bold text, bullet points or any markdown formatting. Plain text only.
- Keep your response concise and professional. Maximum 3-4 sentences. No long paragraphs.

Context:
- Use Order #{order_id} associated with User ID {user_id}.

"""

MANAGER_SYSTEM_PROMPT = """
You are a senior support manager at CoolBreeze AC.
A support agent has escalated a customer case to you for a refund decision.

Your responsibilities:
- Review the case summary carefully
- Consider the customer's refund history
- Make a fair and final refund decision
- Give a clear reason for your decision

Your decision options:
- Approve refund — if the case is genuine and within policy
- Deny refund — if the case is suspicious or outside policy
- Escalate to risk team — if you suspect fraud

Important rules:
- Be fair but firm
- Base decision on facts — not emotions
- Always give a specific reason for your decision
- Keep your response concise and professional
"""

RISK_SYSTEM_PROMPT = """
You are a fraud risk analyst at CoolBreeze AC.
A support manager has sent you a customer profile for risk assessment.

Your job:
- Analyse the customer's order and refund patterns
- Identify suspicious behaviour
- Return a clear risk verdict

Risk levels:
- LOW — genuine customer, normal behaviour
- MEDIUM — some suspicious signals, proceed with caution
- HIGH — clear fraud pattern, recommend denial

Your response format:
- Risk Level: LOW / MEDIUM / HIGH
- Key Signals: what you found suspicious or genuine
- Recommendation: what manager should do

Important:
- Be objective — base verdict on data only
- One bad refund does not make someone fraudulent
- Look for patterns — not isolated incidents
"""

# SUPPORT TOOLS --> Tool schemas, that ai agent will read
SUPPORT_TOOLS = [
    {
        "name": "get_order_details",
        "description": "Fetch complete order details including status, carrier, tracking number, and days since order was placed. Use this when customer mentions their order or compains about delivery.",
        "input_schema": {
            "type": "object",
            "properties": {
                "order_id": {
                    "type": "integer",
                    "description": "The unique identifier of the order to look up.",
                }
            },
            "required": ["order_id"],
        },
    },
    {
        "name": "get_refund_history",
        "description": "Get complete refund history for a user. Use this before making any refund related decisions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The unique identifier of the user to check refund history.",
                }
            },
            "required": ["user_id"],
        },
    },
    {
        "name": "check_delivery_status",
        "description": "Check current delivery status using tracking number and carrier. Use this when custome complains about delayed or missing delivery.",
        "input_schema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "The tracking number of the order to check.",
                },
                "carrier": {
                    "type": "string",
                    "description": "The carrier responsible for delivering the order (e.g., BlueDart or Delhivery).",
                },
            },
            "required": ["tracking_number", "carrier"],
        }
    },
    {
        "name": "escalate_to_manager",
        "description": "Escalate the case to manager for refund decision. Always include customer's user_id in the case summary so manager can assess fraud risk accurately.",
        "input_schema": {
            "type": "object",
            "properties": {
                "case_summary": {
                    "type": "string",
                    "description": "Complete case summary. Must include: customer user_id, order details, refund history and complaint. Format: Start with 'Customer User ID: X' on the first line."
                }
            },
            "required": ["case_summary"]
        }
    }
]

MANAGER_TOOLS = [
    {
        "name": "assess_fraud_risk",
        "description": "Consult the risk agent to assess fraud risk for a customer. Use this when refund request looks suspicious or customer has multiple refund requests. Pass the user_id to get a risk verdict.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess fraud risk for"
                }
            },
            "required": ["user_id"]
        }
    }
]

RISK_TOOLS = [
    {
        "name": "get_customer_risk_profile",
        "description": "Get complete risk profile for a customer including order history, refund patterns and ratio. Use this to assess fraud risk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "integer",
                    "description": "The user ID to assess risk for"
                }
            },
            "required": ["user_id"]
        }
    }
]

# EXECUTE TOOLS --> The bridge beteween claude and the tool.


def execute_tool(tool_name, tool_input, conversation_id=None):
    if tool_name == "get_order_details":
        return get_order_details(tool_input["order_id"])

    if tool_name == "get_refund_history":
        return get_refund_history(tool_input["user_id"])

    if tool_name == "check_delivery_status":
        return check_delivery_status(tool_input["tracking_number"], tool_input["carrier"])

    if tool_name == "get_customer_risk_profile":
        return get_customer_risk_profile(tool_input["user_id"])

    if tool_name == "escalate_to_manager":
        case_summary = tool_input["case_summary"]
        return run_manager_agent(case_summary, conversation_id)

    if tool_name == "assess_fraud_risk":
        user_id = tool_input["user_id"]
        return run_risk_agent(user_id, conversation_id)

    return {"error": f"Tool '{tool_name}' not found."}

# AGENT LOOP --> The loop that will keep the agent running until the task is completed.


def run_support_agent(conversation_id, order_id, user_id):
    conversation = Conversation.objects.get(id=conversation_id)

    messages = []
    for message in conversation.messages.order_by("created_at"):
        messages.append(
            {
                "role": message.role,
                "content": message.content
            })

    while True:
        response = client.messages.create(
            model=anthropic_model,
            max_tokens=1024,
            system=SUPPORT_SYSTEM_PROMPT.format(
                order_id=order_id, user_id=user_id),
            tools=SUPPORT_TOOLS,
            messages=messages,
        )

        messages.append({
            "role": "assistant",
            "content": response.content
        })

        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if (block.type != "tool_use"):
                    continue

                message = f"Calling tool {block.name} with {block.input}."
                publish(conversation_id, {
                        "type": "tool_call", "message": message})

                AgentLog.objects.create(
                    conversation=conversation, event_type="tool_call", message=message)

                result = execute_tool(block.name, block.input, conversation_id)

                message = f"{block.name} returned: {str(result)[:200]}."
                publish(conversation_id, {
                        "type": "tool_result", "message": message})

                AgentLog.objects.create(conversation=conversation, event_type="tool_result",
                                        message=message)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                })

            messages.append({
                "role": "user",
                "content": tool_results
            })

            continue

        final_reply = "".join(
            block.text
            for block in response.content
            if block.type == "text")

        # publish event to queue
        publish(conversation_id, {"type": "final", "message": final_reply})

        AgentLog.objects.create(conversation=conversation,
                                event_type="final", message=final_reply)

        publish(conversation_id, DONE)

        return final_reply


def run_manager_agent(case_summary, conversation_id):
    conversation = Conversation.objects.get(id=conversation_id)

    publish(conversation_id, {
            "type": "manager", "message": f"Case received for review: {case_summary[:200]}"})

    AgentLog.objects.create(conversation=conversation,
                            event_type="manager", message=f"Case received for review: {case_summary[:200]}")

    messages = [
        {
            "role": "user",
            "content": case_summary
        }
    ]

    while True:
        response = client.messages.create(
            model=anthropic_model,
            max_tokens=1024,
            system=MANAGER_SYSTEM_PROMPT,
            tools=MANAGER_TOOLS,
            messages=messages,
        )

        messages.append({
            "role": "assistant",
            "content": response.content
        })

        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if (block.type != "tool_use"):
                    continue

                publish(conversation_id, {
                        "type": "manager", "message": "Consulting risk agent for fraud assessment..."})

                AgentLog.objects.create(conversation=conversation, event_type="manager",
                                        message="Consulting risk agent for fraud assessment...")

                result = execute_tool(block.name, block.input, conversation_id)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                })

            messages.append({
                "role": "user",
                "content": tool_results
            })

            continue

        decision = "".join(
            block.text
            for block in response.content
            if block.type == "text")

        publish(conversation_id, {"type": "manager",
                "message": f"Decision: {decision[:200]}"})

        AgentLog.objects.create(conversation=conversation,
                                event_type="manager", message=f"Decision: {decision[:200]}")

        return decision


def run_risk_agent(user_id, conversation_id):
    conversation = Conversation.objects.get(id=conversation_id)

    publish(conversation_id, {"type": "risk",
                              "message": f"Started fraud risk assement for user: {user_id}"})

    AgentLog.objects.create(conversation=conversation,
                            event_type="risk", message=f"Started fraud risk assement for user: {user_id}")

    messages = [
        {
            "role": "user",
            "content": f"Please assess the fraud risk for user ID {user_id}. Use your tools to get their profile and return a verdict."
        }
    ]

    while True:
        response = client.messages.create(
            model=anthropic_model,
            max_tokens=1024,
            system=RISK_SYSTEM_PROMPT,
            tools=RISK_TOOLS,
            messages=messages,
        )

        messages.append({
            "role": "assistant",
            "content": response.content
        })

        if response.stop_reason == "tool_use":
            tool_results = []

            for block in response.content:
                if (block.type != "tool_use"):
                    continue

                publish(conversation_id, {"type": "risk",
                                          "message": f"Calling tool {block.name} with {block.input}."})

                AgentLog.objects.create(conversation=conversation, event_type="risk",
                                        message=f"Calling tool {block.name} with {block.input}.")

                result = execute_tool(block.name, block.input, conversation_id)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result)
                })

            messages.append({
                "role": "user",
                "content": tool_results
            })

            continue

        final_answer = "".join(
            block.text
            for block in response.content
            if block.type == "text")

        publish(conversation_id, {"type": "risk",
                                  "message": f"Verdict: {final_answer[:200]}"})

        AgentLog.objects.create(conversation=conversation,
                                event_type="risk", message=f"Verdict: {final_answer[:200]}")

        return final_answer
