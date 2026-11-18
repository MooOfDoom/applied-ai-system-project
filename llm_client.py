import os
from typing import Optional


class MockClient:
    """
    Offline stand-in for an LLM client.
    This lets the app run without an API key.
    """

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        # Very small, predictable behavior for demos.
        if "Return ONLY valid JSON" in system_prompt:
            # Purposely not JSON to force fallback unless students change behavior.
            return "I found some issues, but I'm not returning JSON right now."
        return "# MockClient: no rewrite available in offline mode.\n"


class GeminiClient:
    """
    Minimal Gemini API wrapper with added error resilience.

    Requirements:
    - google-genai installed
    - GEMINI_API_KEY set in environment (or loaded via python-dotenv)
    """

    def __init__(self, model_name: str = "gemini-flash-lite-latest", temperature: float = 0.2):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "Missing GEMINI_API_KEY. Create a .env file and set GEMINI_API_KEY=..."
            )

        # Import here so heuristic mode doesn't require the dependency at import time.
        from google import genai

        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name
        self.temperature = float(temperature)
        self.last_error = None  # reason for the most recent failed complete() call

    # -----------------------------------------------------------
    # Phase 0: naive generation over full docs
    # -----------------------------------------------------------

    def naive_answer_over_full_docs(self, query, all_text):
        # We ignore all_text and send a generic prompt instead
        prompt = f"""
    You are a documentation assistant. 
    Answer this developer question: {query}
    """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return (response.text or "").strip()
        except Exception as e:
            return f"Unable to generate an answer. ({type(e).__name__}: {e})"

    # -----------------------------------------------------------
    # Phase 2: RAG style generation over retrieved snippets
    # -----------------------------------------------------------

    def answer_from_snippets(self, query, snippets):
        """
        Phase 2:
        Generate an answer using only the retrieved snippets.

        snippets: list of (filename, text) tuples selected by DocuBot.retrieve

        The prompt:
        - Shows each snippet with its filename
        - Instructs the model to rely only on these snippets
        - Requires an explicit "I do not know" refusal when needed
        """

        if not snippets:
            return "I do not know based on the docs I have."

        context_blocks = []
        for filename, text in snippets:
            block = f"File: {filename}\n{text}\n"
            context_blocks.append(block)

        context = "\n\n".join(context_blocks)

        prompt = f"""
You are a cautious documentation assistant helping developers understand a codebase.

You will receive:
- A developer question
- A small set of snippets from project files

Your job:
- Answer the question using only the information in the snippets.
- If the snippets do not provide enough evidence, refuse to guess.

Snippets:
{context}

Developer question:
{query}

Rules:
- Use only the information in the snippets. Do not invent new functions,
  endpoints, or configuration values.
- If the snippets are not enough to answer confidently, reply exactly:
  "I do not know based on the docs I have."
- When you do answer, briefly mention which files you relied on.
"""

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt
            )
            return (response.text or "").strip()
        except Exception as e:
            return f"API error — could not generate answer. ({type(e).__name__}: {e})"


    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """
        Sends a single request to Gemini.

        If an error occurs, it returns an empty string, triggering the agent's
        heuristic fallback logic.
        """
        self.last_error = None
        try:
            merged_prompt = f"{system_prompt}\n\n{user_prompt}".strip()
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=merged_prompt,
            )

            # Defensive: response.text can be None or raise an error if blocked by filters.
            text = response.text or ""
            if not text:
                self.last_error = "The response contained no text (it may have been blocked by a safety filter)."
            return text

        except Exception as e:
            # Returning empty string allows the agent to detect the failure
            # and switch to offline rules. The reason is kept in last_error so it can be shown.
            self.last_error = _describe_error(e)
            return ""

    # -----------------------------------------------------------
    # Diagnostics used by the app
    # -----------------------------------------------------------

    def check_connection(self) -> tuple:
        """Send a one-word prompt. Returns (ok, message) with the real error text on failure."""
        try:
            response = self.client.models.generate_content(
                model=self.model_name, contents="Reply with the single word: ok"
            )
            return True, f"{self.model_name} replied: {(response.text or '').strip()[:40] or '(empty)'}"
        except Exception as e:
            return False, _describe_error(e)


def _describe_error(e: Exception) -> str:
    """Short one-line description of an API exception."""
    return f"{type(e).__name__}: {str(e)[:300]}"


def list_gemini_models(api_key: str) -> list:
    """
    Names of models (without the 'models/' prefix) that support generateContent for this key,
    sorted. Returns [] if the API cannot be reached; callers should have a fallback list.
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)
        names = [
            m.name.split("/", 1)[-1]
            for m in client.models.list()
            if "generateContent" in (m.supported_actions or [])
        ]
        return sorted(names)
    except Exception:
        return []
