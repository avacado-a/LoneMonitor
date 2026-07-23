import os
import shutil
import tempfile
import subprocess

def test_and_apply_patch(diff_text: str, target_repo_dir: str = ".") -> bool:
    print("[Sandbox Runner] Spinning up isolated sandbox environment...")
    temp_dir = tempfile.mkdtemp(prefix="tier2_sandbox_")
    
    try:
        # Copy repository files to sandbox
        for item in os.listdir(target_repo_dir):
            if item in [".git", "__pycache__", "venv", ".vscode"]:
                continue
            s = os.path.join(target_repo_dir, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d)
            else:
                shutil.copy2(s, d)

        patch_file = os.path.join(temp_dir, "patch.diff")
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(diff_text)

        print("[Sandbox Runner] Applying diff in sandbox...")
        apply_res = subprocess.run(["git", "apply", "--ignore-space-at-eol", "--ignore-whitespace", "patch.diff"], cwd=temp_dir, capture_output=True, text=True)

        if apply_res.returncode != 0:
            print(f"[Sandbox Runner] Git apply failed:\n{apply_res.stderr}")
            return False

        print("[Sandbox Runner] Verifying syntax and basic compilation in sandbox...")
        # Check target_app.py syntax
        py_check = subprocess.run(["python", "-m", "py_compile", "target_app.py"], cwd=temp_dir, capture_output=True, text=True)
        if py_check.returncode != 0:
            print(f"[Sandbox Runner] Python syntax compilation failed:\n{py_check.stderr}")
            return False

        print("[Sandbox Runner] Patch verification passed! Applying patch to main repository...")
        main_patch_file = os.path.join(target_repo_dir, "patch.diff")
        with open(main_patch_file, "w", encoding="utf-8") as f:
            f.write(diff_text)
        
        apply_main = subprocess.run(["git", "apply", "--ignore-space-at-eol", "--ignore-whitespace", "patch.diff"], cwd=target_repo_dir, capture_output=True, text=True)
        if os.path.exists(main_patch_file):
            os.remove(main_patch_file)

        if apply_main.returncode == 0:
            print("[Sandbox Runner] Patch successfully merged into target application!")
            return True
        else:
            print(f"[Sandbox Runner] Merging patch to target repository failed:\n{apply_main.stderr}")
            return False

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
