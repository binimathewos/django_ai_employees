import queue

subscribers = {}  # {25: [queue1, queue2], 27: [queue3]}


def subscribe(conversation_id):
    q = queue.Queue()

    if conversation_id not in subscribers:
        subscribers[conversation_id] = []

    subscribers[conversation_id].append(q)

    return q


def unsubscribe(conversation_id, q):
    if conversation_id in subscribers:
        subscribers[conversation_id].remove(q)
        if not subscribers[conversation_id]:
            del subscribers[conversation_id]


def publish(conversation_id, event):
    if conversation_id in subscribers:
        for q in subscribers[conversation_id]:
            q.put(event)


# Sentinal value - it tells SSE stream to stop
DONE = {"type": "done"}
