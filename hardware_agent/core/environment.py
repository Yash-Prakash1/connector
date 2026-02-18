"""Environment detection — OS, Python, packages, USB, VISA."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Optional

from hardware_agent.core.models import OS, Environment


class EnvironmentDetector:
    """Detects everything about the user's system."""

    @staticmethod
    def detect_current() -> Environment:
        """Detect the current environment."""
        detected_os = _detect_os()
        os_version = _detect_os_version()
        python_version = platform.python_version()
        python_path = sys.executable
        pip_path = _detect_pip_path()
        env_type, env_path, env_name = _detect_env()
        installed_packages = _detect_installed_packages(pip_path)
        usb_devices = _detect_usb_devices(detected_os)
        visa_resources = _detect_visa_resources()

        return Environment(
            os=detected_os,
            os_version=os_version,
            python_version=python_version,
            python_path=python_path,
            pip_path=pip_path,
            env_type=env_type,
            env_path=env_path,
            name=env_name,
            installed_packages=installed_packages,
            usb_devices=usb_devices,
            visa_resources=visa_resources,
        )

    @staticmethod
    def detect_available_environments() -> list[Environment]:
        """Check for common virtual environments."""
        envs: list[Environment] = []
        candidates = [
            Path("./venv"),
            Path("./.venv"),
            Path("./env"),
        ]
        home = Path.home()
        virtualenvs_dir = home / ".virtualenvs"
        if virtualenvs_dir.is_dir():
            candidates.extend(virtualenvs_dir.iterdir())

        for candidate in candidates:
            python = candidate / "bin" / "python"
            if not python.exists():
                python = candidate / "Scripts" / "python.exe"
            if python.exists():
                try:
                    result = subprocess.run(
                        [str(python), "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if result.returncode == 0:
                        version = result.stdout.strip().replace("Python ", "")
                        envs.append(Environment(
                            os=_detect_os(),
                            os_version=_detect_os_version(),
                            python_version=version,
                            python_path=str(python),
                            pip_path=str(candidate / "bin" / "pip"),
                            env_type="venv",
                            env_path=str(candidate),
                            name=candidate.name,
                        ))
                except Exception:
                    pass
        return envs

    @staticmethod
    def create_venv(path: str) -> Environment:
        """Create a new venv and return its Environment."""
        subprocess.run(
            [sys.executable, "-m", "venv", path],
            check=True, capture_output=True, text=True,
        )
        venv = Path(path)
        python = str(venv / "bin" / "python")
        pip = str(venv / "bin" / "pip")
        result = subprocess.run(
            [python, "--version"],
            capture_output=True, text=True, timeout=5,
        )
        version = result.stdout.strip().replace("Python ", "")
        return Environment(
            os=_detect_os(),
            os_version=_detect_os_version(),
            python_version=version,
            python_path=python,
            pip_path=pip,
            env_type="venv",
            env_path=path,
            name=venv.name,
        )


def _detect_os() -> OS:
    system = platform.system().lower()
    if system == "linux":
        return OS.LINUX
    elif system == "darwin":
        return OS.MACOS
    elif system == "windows":
        return OS.WINDOWS
    return OS.LINUX


def _detect_os_version() -> str:
    try:
        if platform.system() == "Linux":
            result = subprocess.run(
                ["lsb_release", "-ds"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().strip('"')
        return platform.platform()
    except Exception:
        return platform.platform()


def _detect_pip_path() -> str:
    pip = os.path.join(os.path.dirname(sys.executable), "pip")
    if os.path.exists(pip):
        return pip
    return f"{sys.executable} -m pip"


def _detect_env() -> tuple[str, Optional[str], str]:
    """Return (env_type, env_path, env_name)."""
    if os.environ.get("CONDA_DEFAULT_ENV"):
        return (
            "conda",
            os.environ.get("CONDA_PREFIX"),
            os.environ["CONDA_DEFAULT_ENV"],
        )
    if os.environ.get("VIRTUAL_ENV"):
        venv = os.environ["VIRTUAL_ENV"]
        return "venv", venv, os.path.basename(venv)
    if hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    ):
        return "venv", sys.prefix, os.path.basename(sys.prefix)
    return "system", None, "system"


def _detect_installed_packages(pip_path: str) -> dict[str, str]:
    """Return {package_name: version} dict."""
    try:
        cmd = pip_path.split() if " " in pip_path else [pip_path]
        result = subprocess.run(
            cmd + ["list", "--format=json"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            packages = json.loads(result.stdout)
            return {p["name"].lower(): p["version"] for p in packages}
    except Exception:
        pass
    return {}


def _detect_usb_devices(detected_os: OS) -> list[str]:
    """List USB devices using OS-specific commands."""
    try:
        if detected_os == OS.LINUX:
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                return [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip()
                ]
        elif detected_os == OS.MACOS:
            result = subprocess.run(
                ["system_profiler", "SPUSBDataType"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip()
                ]
        elif detected_os == OS.WINDOWS:
            result = subprocess.run(
                ["powershell", "-Command", "Get-PnpDevice -Class USB | Format-List"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [
                    line.strip()
                    for line in result.stdout.splitlines()
                    if line.strip()
                ]
    except Exception:
        pass
    return []


def _detect_visa_resources() -> list[str]:
    """List VISA resources if pyvisa is available."""
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             "import pyvisa; rm = pyvisa.ResourceManager('@py'); "
             "print('\\n'.join(rm.list_resources()))"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return [
                line.strip()
                for line in result.stdout.splitlines()
                if line.strip()
            ]
    except Exception:
        pass
    return []
