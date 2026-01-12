# this is for the app, not for scheduled_runs
from setuptools import find_packages, setup

setup(
    name="ally",
    package_dir={"": "."},
    packages=find_packages(where="."),
    version="1.0.0",
    python_requires=">=3.8",
)
