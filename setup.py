from pathlib import Path

from setuptools import find_packages, setup

THIS_DIR = Path(__file__).parent
LONG_DESCRIPTION = (THIS_DIR / "README.md").read_text(encoding="utf-8")

setup(
    name="lead-scoring-engine",
    version="0.1.0",
    description=(
        "AI-powered lead extraction, deduplication, and scoring: Claude "
        "extracts structured fields from messy lead text and scores "
        "conversion likelihood, on top of this portfolio's existing "
        "validation and deduplication libraries."
    ),
    long_description=LONG_DESCRIPTION,
    long_description_content_type="text/markdown",
    author="Matt",
    license="MIT",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.8",
    install_requires=[
        "anthropic>=0.121.0,<1.0.0",
        "pandas>=3.0.5,<4.0.0",
        "click>=8.4.2,<9.0.0",
        "python-dotenv>=1.2.2,<2.0.0",
        "email-phone-validator @ git+https://github.com/Matthew-Cassin/"
        "email-phone-validator.git@v0.1.0",
        "contact-deduplicator @ git+https://github.com/Matthew-Cassin/"
        "contact-deduplicator.git@v0.1.0",
    ],
    entry_points={
        "console_scripts": [
            "lead-scoring-engine=lead_scoring_engine.cli:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Programming Language :: Python :: 3 :: Only",
        "Environment :: Console",
        "Topic :: Software Development :: Libraries :: Python Modules",
        "Topic :: Office/Business",
    ],
    keywords="lead-scoring lead-generation claude-api ai-extraction crm sales-automation",
)
