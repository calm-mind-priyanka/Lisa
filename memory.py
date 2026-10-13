from collections import defaultdict, deque
from threading import RLock

class ConversationMemory:
    """Temporary conversation history keyed by Telegram user ID."""
    def __init__(self, max_turns: int = 12):
        self.max_items = max(4, max_turns * 2)
        self._history = defaultdict(lambda: deque(maxlen=self.max_items))
        self._lock = RLock()

    def get(self, user_id: int) -> list[dict]:
        with self._lock:
            return list(self._history[int(user_id)])

    def add(self, user_id: int, user_text: str, assistant_text: str):
        with self._lock:
            history = self._history[int(user_id)]
            history.append({"role": "user", "text": user_text[:6000]})
            history.append({"role": "assistant", "text": assistant_text[:6000]})

    def clear(self, user_id: int):
        with self._lock:
            self._history.pop(int(user_id), None)

    def clear_all(self):
        with self._lock:
            self._history.clear()
