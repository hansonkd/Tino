#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import re

from setuptools import setup


def get_version(package):
    """
    Return package version as listed in `__version__` in `init.py`.
    """
    with open(os.path.join(package, "__init__.py")) as f:
        return re.search("__version__ = ['\"]([^'\"]+)['\"]", f.read()).group(1)


def get_long_description():
    """
    Return the README.
    """
    with open("README.md", encoding="utf8") as f:
        return f.read()


def get_packages(package):
    """
    Return root package and all sub-packages.
    """
    return [
        dirpath
        for dirpath, dirnames, filenames in os.walk(package)
        if os.path.exists(os.path.join(dirpath, "__init__.py"))
    ]


setup(
    name="tino",
    version=get_version("tino"),
    python_requires=">=3.8",
    url="https://github.com/hansonkd/tino",
    license="MIT",
    description="MsgPack Redis Protocol API",
    long_description=get_long_description(),
    long_description_content_type="text/markdown",
    author="Kyle Hanson",
    author_email="me@khanson.io",
    packages=get_packages("tino"),
    package_data={"tino": ["py.typed"]},
    data_files=[("", ["LICENSE"])],
    install_requires=[
        "pydantic>=1.5.1",
        "msgpack>=1.0.0",
        "aioredis>=1.3.1",
        'aiocontextvars;python_version<"3.7"',
    ],
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3.8",
    ],
    zip_safe=False,
)
