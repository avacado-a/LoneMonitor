import json
import re
import ai

# Circuit breaker tracking: module -> attempt count
CIRCUIT_BREAKER = {}
MAX_PATCH_ATTEMPTS = 2
MAX_DIFF_LINES = 50

SYSTEM_PROMPT = """SYSTEM INSTRUCTION: You are an autonomous software engineering and security agent.
Your objective is to fix a production issue using the minimum necessary code changes.

RULES:
1. Output ONLY a valid Unified Git Diff inside a ```diff code block. Do not include markdown conversational explanations outside code blocks.
2. Do NOT rewrite unrelated code, refactor existing structures, or add new features.
3. Modify at most 50 lines of code across all files.
4. Ensure the patch handles edge cases, null inputs, or state cleanup safely.
5. In your diff, use standard relative file paths like `--- a/target_app.py` and `+++ b/target_app.py`.
"""

def extract_diff(ai_response: str) -> str:
    # Extract diff block
    match = re.search(r"```(?:diff)?\n(diff --git.*?)```", ai_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    
    # Fallback search for unified diff header
    match_fallback = re.search(r"(--- a/.*?\n\+\+\+ b/.*?\n@@.*)", ai_response, re.DOTALL)
    if match_fallback:
        return match_fallback.group(1).strip()
        
    return ai_response.strip()

def validate_diff_size(diff_text: str) -> bool:
    lines = diff_text.splitlines()
    changed_lines = [l for l in lines if l.startswith('+') or l.startswith('-')]
    # Exclude header lines
    changed_lines = [l for l in changed_lines if not (l.startswith('+++') or l.startswith('---'))]
    return len(changed_lines) <= MAX_DIFF_LINES

def analyze_and_patch(payload: dict) -> dict:
    module = payload.get("affected_files", ["target_app.py"])[0]
    
    attempts = CIRCUIT_BREAKER.get(module, 0)
    if attempts >= MAX_PATCH_ATTEMPTS:
        print(f"[Tier 2 Circuit Breaker] Max patch attempts ({MAX_PATCH_ATTEMPTS}) reached for module '{module}'. Freezing auto-remediation.")
        return {"status": "circuit_breaker_tripped", "module": module}

    CIRCUIT_BREAKER[module] = attempts + 1

    # Fetch source code of affected file to assist reasoning
    file_content = ""
    if os.path.exists(module):
        with open(module, "r", encoding="utf-8") as f:
            file_content = f.read()

    prompt_content = f"DIAGNOSTIC PAYLOAD:\n{json.dumps(payload, indent=2)}\n\nFILE CONTENT OF {module}:\n```python\n{file_content}\n```"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt_content}
    ]

    print(f"[Tier 2 Engine] Invoking AI model via ai.py (Attempt {CIRCUIT_BREAKER[module]}/{MAX_PATCH_ATTEMPTS})...")
    ai_response = ai.request(messages, temperature=0.1)

    diff = extract_diff(ai_response)

    if not validate_diff_size(diff):
        print(f"[Tier 2 Engine] Generated patch exceeded {MAX_DIFF_LINES} changed lines limit.")
        return {"status": "failed", "reason": "diff_too_large"}

    return {
        "status": "patch_generated",
        "diff": diff,
        "module": module,
        "attempt": CIRCUIT_BREAKER[module]
    }

import os
