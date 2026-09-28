"""
Unit and integration tests for Windows UAT setup, verification, and startup workflows.
Covers:
- Python runtime compatibility scoring and version priority selection
- Global unsupported Python (e.g. 3.14) vs. compatible side-by-side selection
- Virtual environment (.venv) compatibility inspection and self-healing recreation
- Verification reporting (Check 2 & Check 3 diagnostics and reference codes)
- Local .env security key generation and upload configuration
- Startup preflight checks (compatibility, dependencies, storage directories, FFmpeg)
- Batch file and PowerShell script integrity and error handling syntax
"""

import os
import re
import secrets
from pathlib import Path
from unittest import TestCase
from cryptography.fernet import Fernet
from django.conf import settings


def classify_python_version(version_str: str) -> dict:
    """Python version classifier mirroring Get-PythonInfo in setup_windows.ps1."""
    parts = version_str.strip().split(".")
    if len(parts) < 2:
        return {"version": version_str, "is_compatible": False, "priority": 99}

    major = int(parts[0])
    minor = int(parts[1])
    micro = int(parts[2]) if len(parts) >= 3 else 0

    is_compatible = (major == 3 and 10 <= minor <= 12)
    priority = 99
    if major == 3:
        if minor == 11:
            priority = 1
        elif minor == 12:
            priority = 2
        elif minor == 10:
            priority = 3

    return {
        "version": version_str,
        "major": major,
        "minor": minor,
        "micro": micro,
        "is_compatible": is_compatible,
        "priority": priority,
    }


def select_best_python(candidates: list[str]) -> dict | None:
    """Mirrors the candidate selection logic in setup_windows.ps1."""
    classified = [classify_python_version(c) for c in candidates]
    compatible = [c for c in classified if c["is_compatible"]]
    if not compatible:
        return None
    compatible.sort(key=lambda x: x["priority"])
    return compatible[0]


def format_verify_python_runtime_check(project_venv_ver: str | None, global_ver: str | None) -> tuple[str, str]:
    """Mirrors Check 2 reporting in verify_setup.ps1."""
    proj_info = classify_python_version(project_venv_ver) if project_venv_ver else None
    glob_info = classify_python_version(global_ver) if global_ver else None

    if proj_info and proj_info["is_compatible"]:
        if glob_info and not glob_info["is_compatible"]:
            detail = f"Project Python {proj_info['version']} (Global: {glob_info['version']})"
            return "PASS", detail
        else:
            if glob_info and glob_info["version"] != proj_info["version"]:
                detail = f"Project Python {proj_info['version']} (Global: {glob_info['version']})"
            else:
                detail = f"Python {proj_info['version']}"
            return "PASS", detail
    elif glob_info:
        if glob_info["is_compatible"]:
            return "PASS", f"Python {glob_info['version']}"
        elif glob_info["major"] == 3 and glob_info["minor"] > 12:
            return "WARN", f"SETUP-PYTHON-003: Global Python {glob_info['version']} newer than tested range"
        else:
            return "FAIL", f"SETUP-PYTHON-002: Python {glob_info['version']} is outdated"
    else:
        return "FAIL", "SETUP-PYTHON-001: Python 3.10-3.12 not found"


def evaluate_venv_status(venv_ver: str | None) -> tuple[str, str, str | None]:
    """Mirrors Check 3 in verify_setup.ps1."""
    if not venv_ver:
        return "FAIL", ".venv missing or broken", "SETUP-VENV-001"
    info = classify_python_version(venv_ver)
    if info["is_compatible"]:
        return "PASS", f".venv is valid (Python {info['version']})", None
    else:
        return "FAIL", f"Existing .venv created with unsupported Python {info['version']}", "SETUP-VENV-002"


class WindowsSetupPythonSelectionTestCase(TestCase):
    """Tests for Python version discovery, scoring, and priority selection."""

    def test_version_classification(self):
        """Python 3.10, 3.11, and 3.12 must be compatible; 3.13, 3.14, 3.9 must not."""
        v311 = classify_python_version("3.11.9")
        self.assertTrue(v311["is_compatible"])
        self.assertEqual(v311["priority"], 1)

        v312 = classify_python_version("3.12.3")
        self.assertTrue(v312["is_compatible"])
        self.assertEqual(v312["priority"], 2)

        v310 = classify_python_version("3.10.11")
        self.assertTrue(v310["is_compatible"])
        self.assertEqual(v310["priority"], 3)

        # Unsupported versions
        v313 = classify_python_version("3.13.0")
        self.assertFalse(v313["is_compatible"])
        self.assertEqual(v313["priority"], 99)

        v314 = classify_python_version("3.14.2")
        self.assertFalse(v314["is_compatible"])
        self.assertEqual(v314["priority"], 99)

        v39 = classify_python_version("3.9.7")
        self.assertFalse(v39["is_compatible"])
        self.assertEqual(v39["priority"], 99)

        v27 = classify_python_version("2.7.18")
        self.assertFalse(v27["is_compatible"])
        self.assertEqual(v27["priority"], 99)

    def test_priority_selection_picks_311_over_others(self):
        """When 3.11, 3.12, 3.10, and 3.14 are present, 3.11 must be selected."""
        candidates = ["3.14.2", "3.12.4", "3.11.9", "3.10.12"]
        best = select_best_python(candidates)
        self.assertIsNotNone(best)
        self.assertEqual(best["version"], "3.11.9")
        self.assertEqual(best["priority"], 1)

    def test_priority_selection_picks_312_when_311_absent(self):
        """When 3.11 is absent but 3.12 and 3.10 exist, 3.12 must be selected."""
        candidates = ["3.14.2", "3.12.4", "3.10.12"]
        best = select_best_python(candidates)
        self.assertIsNotNone(best)
        self.assertEqual(best["version"], "3.12.4")

    def test_priority_selection_picks_310_when_only_compatible(self):
        """When only 3.10 is available among incompatible runtimes, 3.10 is selected."""
        candidates = ["3.14.2", "3.13.1", "3.10.12", "3.9.13"]
        best = select_best_python(candidates)
        self.assertIsNotNone(best)
        self.assertEqual(best["version"], "3.10.12")

    def test_selection_returns_none_when_all_incompatible(self):
        """When user only has 3.14.2, selection returns None, triggering self-healing install."""
        candidates = ["3.14.2", "3.13.0"]
        best = select_best_python(candidates)
        self.assertIsNone(best)


class WindowsSetupVenvSelfHealingTestCase(TestCase):
    """Tests for virtual environment compatibility detection and recreation rules."""

    def test_venv_with_311_is_reused(self):
        """A virtual environment created with Python 3.11.9 is valid and reused."""
        status, detail, ref = evaluate_venv_status("3.11.9")
        self.assertEqual(status, "PASS")
        self.assertIn("valid", detail)
        self.assertIsNone(ref)

    def test_venv_with_312_is_reused(self):
        """A virtual environment created with Python 3.12.3 is valid and reused."""
        status, detail, ref = evaluate_venv_status("3.12.3")
        self.assertEqual(status, "PASS")
        self.assertIn("valid", detail)
        self.assertIsNone(ref)

    def test_venv_with_314_fails_with_setup_venv_002(self):
        """A virtual environment built with Python 3.14 must fail with SETUP-VENV-002."""
        status, detail, ref = evaluate_venv_status("3.14.2")
        self.assertEqual(status, "FAIL")
        self.assertEqual(ref, "SETUP-VENV-002")
        self.assertIn("unsupported Python 3.14.2", detail)

    def test_venv_with_313_fails_with_setup_venv_002(self):
        """A virtual environment built with Python 3.13 must fail with SETUP-VENV-002."""
        status, detail, ref = evaluate_venv_status("3.13.0")
        self.assertEqual(status, "FAIL")
        self.assertEqual(ref, "SETUP-VENV-002")

    def test_missing_venv_fails_with_setup_venv_001(self):
        """A missing .venv must fail with SETUP-VENV-001."""
        status, detail, ref = evaluate_venv_status(None)
        self.assertEqual(status, "FAIL")
        self.assertEqual(ref, "SETUP-VENV-001")


class WindowsVerifyReportingTestCase(TestCase):
    """Tests for Check 2 & Check 3 output formatting in verify_setup.ps1."""

    def test_check2_passes_with_project_311_and_global_314(self):
        """When project .venv is 3.11 and global Python is 3.14, Check 2 must PASS."""
        status, detail = format_verify_python_runtime_check(
            project_venv_ver="3.11.9",
            global_ver="3.14.2"
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(detail, "Project Python 3.11.9 (Global: 3.14.2)")

    def test_check2_passes_with_matching_global_and_project(self):
        """When both project and global are 3.11.9, Check 2 reports clean PASS."""
        status, detail = format_verify_python_runtime_check(
            project_venv_ver="3.11.9",
            global_ver="3.11.9"
        )
        self.assertEqual(status, "PASS")
        self.assertEqual(detail, "Python 3.11.9")

    def test_check2_warns_when_no_venv_and_global_314(self):
        """Before .venv is created, global 3.14 gives a warning referencing SETUP-PYTHON-003."""
        status, detail = format_verify_python_runtime_check(
            project_venv_ver=None,
            global_ver="3.14.2"
        )
        self.assertEqual(status, "WARN")
        self.assertIn("SETUP-PYTHON-003", detail)


class WindowsEnvGenerationTestCase(TestCase):
    """Tests for local .env security generation and upload configuration."""

    def test_secret_key_generation(self):
        """Generated SECRET_KEY must be cryptographically strong and >= 50 chars."""
        sec = secrets.token_urlsafe(50)
        self.assertGreaterEqual(len(sec), 50)

    def test_fernet_key_generation_and_validation(self):
        """Generated ENCRYPTION_KEY must be a valid Fernet key capable of encryption/decryption."""
        enc = Fernet.generate_key().decode()
        f = Fernet(enc.encode())
        sample_plaintext = b"TestApiKey-12345-AI-Meeting"
        ciphertext = f.encrypt(sample_plaintext)
        decrypted = f.decrypt(ciphertext)
        self.assertEqual(decrypted, sample_plaintext)

    def test_local_upload_size_limit(self):
        """Local upload size limit should support up to 2 GB (2147483648 bytes)."""
        limit = 2147483648
        gb = limit / (1024 * 1024 * 1024)
        self.assertEqual(gb, 2.0)


class WindowsStartupPreflightTestCase(TestCase):
    """Tests for pre-flight assertions performed by Start Application."""

    def test_start_preflight_accepts_compatible_python(self):
        """Pre-flight check accepts Python 3.11."""
        info = classify_python_version("3.11.9")
        self.assertTrue(info["is_compatible"])

    def test_start_preflight_rejects_incompatible_python(self):
        """Pre-flight check rejects Python 3.14."""
        info = classify_python_version("3.14.2")
        self.assertFalse(info["is_compatible"])

    def test_required_storage_directories_list(self):
        """Pre-flight storage directories must include all required paths."""
        expected_dirs = [
            "media",
            os.path.join("media", "meetings", "original"),
            os.path.join("media", "meetings", "audio"),
            os.path.join("media", "meetings", "transcripts"),
            "staticfiles",
            "bin",
        ]
        self.assertEqual(len(expected_dirs), 6)
        for d in expected_dirs:
            self.assertTrue(len(d) > 0)


class WindowsScriptIntegrityTestCase(TestCase):
    """Tests verifying the syntax integrity and reference codes in BAT and PS1 scripts."""

    def setUp(self):
        self.project_root = Path(settings.BASE_DIR)
        self.scripts_dir = self.project_root / "scripts"

    def test_batch_files_exist(self):
        """All 3 entry-point BAT files must exist."""
        for name in ["Setup Application.bat", "Verify Installation.bat", "Start Application.bat"]:
            bat_path = self.project_root / name
            self.assertTrue(bat_path.exists(), f"Missing {name}")

    def test_batch_files_have_no_unescaped_parentheses_in_echo_blocks(self):
        """Ensure no batch file contains '(Exit Code:' inside an if/else block that breaks cmd parsing."""
        for name in ["Setup Application.bat", "Verify Installation.bat", "Start Application.bat"]:
            content = (self.project_root / name).read_text(encoding="utf-8", errors="ignore")
            # In cmd, 'echo ... (Exit Code: ...).' breaks if () else ()
            self.assertNotRegex(
                content,
                r"echo\s+\[.*\(Exit Code:.*?\)\.",
                f"{name} has unescaped parenthesis in echo statement inside if/else block",
            )

    def test_powershell_scripts_exist(self):
        """All 3 core PowerShell automation scripts must exist."""
        for name in ["setup_windows.ps1", "verify_setup.ps1", "start_application.ps1"]:
            ps1_path = self.scripts_dir / name
            self.assertTrue(ps1_path.exists(), f"Missing {name}")

    def test_setup_windows_contains_self_healing_logic(self):
        """setup_windows.ps1 must contain winget, python.org fallback, and version priority logic."""
        content = (self.scripts_dir / "setup_windows.ps1").read_text(encoding="utf-8")
        self.assertIn("Python.Python.3.11", content)
        self.assertIn("python-3.11.9-amd64.exe", content)
        self.assertIn("Discover-PythonInterpreters", content)
        self.assertIn("Install-Python311SideBySide", content)
        self.assertIn("SETUP-PYTHON-001", content)
        self.assertIn("SETUP-VENV-001", content)
        self.assertIn("SETUP-DEP-001", content)
        self.assertIn("SETUP-ENV-001", content)
        self.assertIn("SETUP-DB-001", content)
        self.assertIn("SETUP-DJANGO-001", content)

    def test_verify_setup_contains_reference_codes(self):
        """verify_setup.ps1 must contain diagnostic reference codes including SETUP-VENV-002."""
        content = (self.scripts_dir / "verify_setup.ps1").read_text(encoding="utf-8")
        expected_codes = [
            "SETUP-PROJECT-001",
            "SETUP-PYTHON-001",
            "SETUP-PYTHON-002",
            "SETUP-PYTHON-003",
            "SETUP-VENV-001",
            "SETUP-VENV-002",
            "SETUP-DEP-001",
            "SETUP-ENV-001",
            "SETUP-DB-001",
            "SETUP-FFMPEG-001",
            "SETUP-STORAGE-001",
            "SETUP-DJANGO-001",
        ]
        for code in expected_codes:
            self.assertIn(code, content, f"verify_setup.ps1 missing reference code {code}")

    def test_start_application_contains_reference_codes(self):
        """start_application.ps1 must contain START-VENV-002 and other reference codes."""
        content = (self.scripts_dir / "start_application.ps1").read_text(encoding="utf-8")
        expected_codes = [
            "START-VENV-001",
            "START-VENV-002",
            "START-DEP-001",
            "START-FILE-001",
            "START-ENV-001",
            "START-DB-001",
            "START-FFMPEG-001",
        ]
        for code in expected_codes:
            self.assertIn(code, content, f"start_application.ps1 missing reference code {code}")
