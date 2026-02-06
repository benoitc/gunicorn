#
# This file is part of gunicorn released under the MIT license.
# See the NOTICE for more information.

import time
import random
from gunicorn.dirty.app import DirtyApp


class ChatApp(DirtyApp):
    """Simulated LLM chat application demonstrating streaming responses.

    This app mimics LLM token-by-token generation without requiring
    heavy ML dependencies. Each response is streamed word-by-word
    with realistic timing delays.
    """

    def init(self):
        """Initialize canned responses for different prompts."""
        self.responses = {
            "hello": (
                "Hello! I'm a simulated AI assistant running on Gunicorn's "
                "dirty workers. I can demonstrate streaming responses just "
                "like a real LLM, but without the heavy ML dependencies. "
                "How can I help you today?"
            ),
            "explain": (
                "Dirty workers are separate processes that handle long-running "
                "tasks like ML inference. They keep models loaded in memory "
                "across requests, avoiding expensive reload times. HTTP workers "
                "remain lightweight and responsive while dirty workers handle "
                "the heavy computation. This architecture is inspired by "
                "Erlang's dirty schedulers."
            ),
            "streaming": (
                "Streaming works by yielding chunks from a generator function. "
                "Each yield sends a chunk message through the IPC socket. The "
                "client receives chunks as they're produced, enabling real-time "
                "token-by-token display. This is perfect for LLM applications "
                "where users expect to see responses appear gradually."
            ),
            "code": (
                "Here's a simple example:\n\n"
                "```python\n"
                "from gunicorn.dirty import get_dirty_client\n\n"
                "client = get_dirty_client()\n"
                "for token in client.stream('app:ChatApp', 'generate', prompt):\n"
                "    print(token, end='', flush=True)\n"
                "```\n\n"
                "This streams tokens directly to the console as they arrive."
            ),
            "default": (
                "I understand your question. Let me think about that for a "
                "moment. The key insight here is that streaming responses "
                "provide a much better user experience for long-running "
                "operations. Instead of waiting for the complete response, "
                "users see content appearing in real-time, which feels more "
                "interactive and responsive."
            ),
        }
        self.min_delay = 0.03  # Minimum delay between tokens (30ms)
        self.max_delay = 0.08  # Maximum delay between tokens (80ms)

    def generate(self, prompt):
        """Generate a streaming response for the given prompt.

        Yields tokens (words) one at a time with realistic delays
        to simulate LLM inference.

        Args:
            prompt: User's input prompt

        Yields:
            str: Individual tokens (words with trailing space)
        """
        response = self._get_response(prompt)
        words = response.split()

        for i, word in enumerate(words):
            # Simulate variable inference time
            delay = random.uniform(self.min_delay, self.max_delay)
            time.sleep(delay)

            # Add space after word (except last word)
            if i < len(words) - 1:
                yield word + " "
            else:
                yield word

    def generate_with_thinking(self, prompt):
        """Generate response with visible 'thinking' phase.

        First yields thinking indicators, then streams the response.
        Demonstrates multi-phase streaming.

        Args:
            prompt: User's input prompt

        Yields:
            str: Thinking indicators followed by response tokens
        """
        # Thinking phase
        yield "[thinking"
        for _ in range(3):
            time.sleep(0.3)
            yield "."
        yield "]\n\n"

        # Response phase
        yield from self.generate(prompt)

    def _get_response(self, prompt):
        """Match prompt to a canned response.

        Args:
            prompt: User's input prompt

        Returns:
            str: Matched response text
        """
        prompt_lower = prompt.lower().strip()

        # Check for keyword matches
        for key, response in self.responses.items():
            if key in prompt_lower:
                return response

        # Greeting patterns
        if any(g in prompt_lower for g in ["hi", "hey", "greetings"]):
            return self.responses["hello"]

        return self.responses["default"]

    def close(self):
        """Cleanup on shutdown."""
        pass
