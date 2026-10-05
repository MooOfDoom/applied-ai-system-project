# 💭 Reflection: Game Glitch Investigator

Answer each question in 3 to 5 sentences. Be specific and honest about what actually happened while you worked. This is about your process, not trying to sound perfect.

## 1. What was broken when you started?

- What did the game look like the first time you ran it?
  - It asked me to guess a number between 1 and 100, listed my attempts left, let me enter a guess and had buttons to submit a guess, start a new game, and show a hint.
- List at least two concrete bugs you noticed at the start  
  (for example: "the hints were backwards").
  - The hits were backwards
  - Enter did not submit my guess

**Bug Reproduction Log**

Document at least 3 bugs you found. Add rows as needed.

| Input | Expected Behavior | Actual Behavior | Console Output / Error | Suspected Code Location |
|-------|-------------------|-----------------|------------------------|-------------------------|
| Typed a guess and pressed Enter | The guess is submitted | The guess was not submitted until I clicked the submit button| None | app.py |
| Submitted a guess | The hint directs me towards the solution | The hint directs me away from the solution | None | check_guess() |
| Submitted 7 guesses | I have one guess left | It says "Out of attempts!" and tells me the secret and score. | None | app.py |
| Started a new game after running out of attempts | My attempts are reset and a new secret is picked | It says "Game over. Start a new game to try again." | None | app.py |

---

## 2. How did you use AI as a teammate?

- Which AI tools did you use on this project (for example: ChatGPT, Gemini, Copilot)?
  - Claude Code
- Give one example of an AI suggestion that was correct (including what the AI suggested and how you verified the result).

I accepted this AI suggestion:

```
Hints point the wrong way
The messages in check_guess are swapped (lines 37-40). guess > secret returns "Go HIGHER!" and guess < secret returns "Go LOWER!". They should be reversed.

There's a second cause on lines 158-161. On every even attempt, secret is converted to a string. check_guess then compares an int to a str, which raises TypeError. The except branch compares str(guess) to the string secret, which is a lexicographic comparison ("9" > "50"). That gives wrong outcomes on every other guess. Remove the string conversion and always pass st.session_state.secret as an int.
```

Playing the game a few times after the fix makes me confident that the behavior is now correct.

- Give one example of an AI suggestion you did not accept as written (including what the AI suggested, why you rejected or changed it, and how you verified your version). It does not have to be a suggestion that was wrong: over-engineered, out of scope, harder to read, or a poor fit for this codebase all count.

The following AI suggestion was incomplete, as the attempts display still did not behave correctly.

```
"Out of attempts" with one guess left
attempts starts at 1 (line 96) instead of 0. After the first guess it's 2, so after 7 guesses it's 8, which equals the Normal limit of 8 (line 182). The "Attempts left" display (line 111) is also off by one for the same reason. Initialize attempts to 0.
```

I asked the AI to take another attempt at fixing it, and it stated that the counter was drawn before attempts is updated. I had it change the code, and it ran fine after a few tests.

---

## 3. Debugging and testing your fixes

- How did you decide whether a bug was really fixed?
  - Reading the fixed code, and testing the behavior by running the app.
- Describe at least one test you ran (manual or using pytest)  
  and what it showed you about your code.
  - Submit wrong guesses until out of attempts to see if the number of attempts left displayed correctly the entire time.
- Did AI help you design or understand any tests? How?
  - It made regression tests for the Attempts left display

---

## 4. What did you learn about Streamlit and state?

- How would you explain Streamlit "reruns" and session state to a friend who has never used Streamlit?

Streamlit has no event handlers. Every time you interact with the page, it runs your whole Python script again from the top.

Reruns

Think of a whiteboard that gets wiped clean and redrawn on every interaction. Clicking a button, typing in a box, or moving a slider all re-execute the file from line 1 to the end. Streamlit then shows whatever that run produced. Nothing is kept from the last run. The script doesn't "wait" for a click. It just runs again, and the button's value is True for that one run.

---

## 5. Looking ahead: your developer habits

- What is one habit or strategy from this project that you want to reuse in future labs or projects?
  - This could be a testing habit, a prompting strategy, or a way you used Git.
    - Letting the AI compose commit messages
- What is one thing you would do differently next time you work with AI on a coding task?
  - More carefully peruse its changes before accepting
- In one or two sentences, describe how this project changed the way you think about AI generated code.
  - It gave me more confidence in the ability for AI to find and apply fixes to bugs.