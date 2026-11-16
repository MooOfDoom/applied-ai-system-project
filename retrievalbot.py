"""
Core RetrievalBot class responsible for:
- Loading source code from the correct folder
- Building a simple retrieval index (Phase 1)
- Retrieving relevant snippets (Phase 1)
- Supporting retrieval only answers
- Supporting RAG answers when paired with Gemini (Phase 2)
"""

import os
import ast
import glob
import re

class RetrievalBot:
    def __init__(self, src_folder="game", llm_client=None):
        """
        src_folder: directory containing project source files
        llm_client: optional Gemini client for LLM based answers
        """
        self.src_folder = src_folder
        self.llm_client = llm_client

        # Load source code into memory
        self.source_code = self.load_source()  # List of (filename, text)

        # Split files into small retrievable sections: List of (label, text)
        self.chunks = self.chunk_source(self.source_code)

        # Build a retrieval index over the chunks (implemented in Phase 1)
        self.index = self.build_index(self.chunks)

    # -----------------------------------------------------------
    # Document Loading
    # -----------------------------------------------------------

    def load_source(self):
        """
        Loads all .py, .md and .txt files inside src_folder.
        Returns a list of tuples: (filename, text)
        """
        code = []
        pattern = os.path.join(self.src_folder, "*.*")
        for path in glob.glob(pattern):
            if path.endswith(".py") or path.endswith(".md") or path.endswith(".txt"):
                with open(path, "r", encoding="utf8") as f:
                    text = f.read()
                filename = os.path.basename(path)
                code.append((filename, text))
        return code

    # -----------------------------------------------------------
    # Chunking
    # -----------------------------------------------------------

    def chunk_source(self, source_code):
        """
        Splits each file into smaller sections.
        - .py files: one chunk per function/method; any remaining code
          (imports, class headers, constants) is kept as separate chunks.
        - .md/.txt files: one chunk per paragraph (blocks separated by blank lines).
        Returns a list of (label, text), e.g. ("auth.py (login)", "def login(): ...").
        """
        chunks = []
        for filename, text in source_code:
            if filename.endswith(".py"):
                chunks.extend(self._chunk_python(filename, text))
            else:
                chunks.extend(self._chunk_paragraphs(filename, text))
        return chunks

    @staticmethod
    def _chunk_paragraphs(filename, text):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text)]
        return [
            (f"{filename} (paragraph {n})", p)
            for n, p in enumerate((p for p in paragraphs if p), start=1)
        ]

    def _chunk_python(self, filename, text):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return self._chunk_paragraphs(filename, text)

        # Collect functions at module level and directly inside classes
        defs = []

        def visit(body, prefix):
            for node in body:
                if isinstance(node, ast.ClassDef):
                    visit(node.body, f"{prefix}{node.name}.")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    defs.append((start, node.end_lineno, f"{prefix}{node.name}"))

        visit(tree.body, "")
        defs.sort()

        lines = text.splitlines()
        chunks = []
        cursor = 1  # next unconsumed line (1-indexed)

        def add_gap(end):
            gap = "\n".join(lines[cursor - 1:end - 1]).strip()
            if gap:
                chunks.append((f"{filename} (module/class level)", gap))

        for start, end, name in defs:
            add_gap(start)
            chunks.append((f"{filename} ({name})", "\n".join(lines[start - 1:end])))
            cursor = end + 1
        add_gap(len(lines) + 1)
        return chunks

    # -----------------------------------------------------------
    # Index Construction (Phase 1)
    # -----------------------------------------------------------

    def build_index(self, chunks):
        """
        Builds a tiny inverted index mapping lowercase words to the chunks
        they appear in. Chunks are identified by their position in `chunks`.

        Example structure:
        {
            "token": [0, 4],
            "database": [7]
        }
        """
        index = {}
        for chunk_id, (_, text) in enumerate(chunks):
            for token in self._tokenize(text):
                ids = index.setdefault(token, [])
                if not ids or ids[-1] != chunk_id:
                    ids.append(chunk_id)
        return index

    @staticmethod
    def _tokenize(text):
        """Lowercase and split text into word tokens, ignoring punctuation."""
        return re.findall(r"\w+", text.lower())

    # -----------------------------------------------------------
    # Scoring and Retrieval (Phase 1)
    # -----------------------------------------------------------

    def score_file(self, query, text):
        """
        TODO (Phase 1):
        Return a simple relevance score for how well the text matches the query.

        Suggested baseline:
        - Convert query into lowercase words
        - Count how many appear in the text
        - Return the count as the score
        """
        text_tokens = set(self._tokenize(text))
        query_tokens = set(self._tokenize(query))
        return sum(1 for token in query_tokens if token in text_tokens)

    def retrieve(self, query, top_k=3):
        """
        TODO (Phase 1):
        Use the index and scoring function to select top_k relevant document snippets.

        Return a list of (filename, text) sorted by score descending.
        """
        # Use the index to narrow down to chunks containing at least one query word
        candidates = set()
        for token in set(self._tokenize(query)):
            candidates.update(self.index.get(token, []))

        scored = []
        for chunk_id in candidates:
            score = self.score_file(query, self.chunks[chunk_id][1])
            if score > 0:
                scored.append((score, chunk_id))

        # Highest score first; chunk order breaks ties deterministically
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = [self.chunks[chunk_id] for _, chunk_id in scored]
        return results[:top_k]

    # -----------------------------------------------------------
    # Answering Modes
    # -----------------------------------------------------------

    def answer_retrieval_only(self, query, top_k=3):
        """
        Phase 1 retrieval only mode.
        Returns raw snippets and filenames with no LLM involved.
        """
        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        formatted = []
        for filename, text in snippets:
            formatted.append(f"[{filename}]\n{text}\n")

        return "\n---\n".join(formatted)

    def answer_rag(self, query, top_k=3):
        """
        Phase 2 RAG mode.
        Uses student retrieval to select snippets, then asks Gemini
        to generate an answer using only those snippets.
        """
        if self.llm_client is None:
            raise RuntimeError(
                "RAG mode requires an LLM client. Provide a GeminiClient instance."
            )

        snippets = self.retrieve(query, top_k=top_k)

        if not snippets:
            return "I do not know based on these docs."

        return self.llm_client.answer_from_snippets(query, snippets)

    # -----------------------------------------------------------
    # Bonus Helper: concatenated docs for naive generation mode
    # -----------------------------------------------------------

    def full_corpus_text(self):
        """
        Returns all documents concatenated into a single string.
        This is used in Phase 0 for naive 'generation only' baselines.
        """
        return "\n\n".join(text for _, text in self.source_code)
