from setuptools import setup, find_packages

# Read version from _version.py (canonical source)
# Use get_pip_version() for PEP 440 compliance
_version_vars = {}
with open("notepad_cleanup/_version.py") as f:
    exec(f.read(), _version_vars)
version = _version_vars["PIP_VERSION"]

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="notepad-cleanup",
    version=version,
    description="Extract and organize text from Windows 11 Notepad tabs using AI",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="djdarcy",
    author_email="6962246+djdarcy@users.noreply.github.com",
    url="https://github.com/DazzleTools/notepad-cleanup",
    project_urls={
        "Bug Tracker": "https://github.com/DazzleTools/notepad-cleanup/issues",
        "Discussions": "https://github.com/DazzleTools/notepad-cleanup/discussions",
        "Changelog": "https://github.com/DazzleTools/notepad-cleanup/blob/main/CHANGELOG.md",
    },
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
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: Microsoft :: Windows",
        "Topic :: Utilities",
        "Topic :: Text Processing",
    ],
    python_requires=">=3.10",
)
