import re
from setuptools import setup, find_packages

# Read version from _version.py (canonical source)
# Use get_pip_version() for PEP 440 compliance
_version_vars = {}
with open("notepad_cleanup/_version.py") as f:
    exec(f.read(), _version_vars)
version = _version_vars["PIP_VERSION"]

setup(
    name="notepad-cleanup",
    version=version,
    description="Automated Notepad window/tab text extraction and organization tool",
    author="djdarcy",
    author_email="6962246+djdarcy@users.noreply.github.com",
    packages=find_packages(),
    package_data={
        "notepad_cleanup": ["prompts/*.md"],
    },
    install_requires=[
        "pywinauto>=0.6.9",
        "pywin32>=306",
        "psutil>=5.9.0",
        "click>=8.1.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "notepad-cleanup=notepad_cleanup.cli:main",
        ],
    },
    license="GPL-3.0-or-later",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "License :: OSI Approved :: GNU General Public License v3 (GPLv3)",
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
        "Topic :: Utilities",
    ],
    python_requires=">=3.10",
)
