from setuptools import setup, find_packages

setup(
    name="notepad-cleanup",
    version="0.1.0",
    description="Automated Notepad window/tab text extraction and organization tool",
    author="Dustin",
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
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: End Users/Desktop",
        "Programming Language :: Python :: 3",
        "Operating System :: Microsoft :: Windows",
        "Topic :: Utilities",
    ],
    python_requires=">=3.10",
)
