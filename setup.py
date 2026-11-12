from setuptools import setup, find_packages

setup(
    name="pilldrops",
    version="1.1.1",
    description="Python SDK for PillDrops — AI-native sandboxes (secure code execution + app hosting)",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/pilldrops-oss/pilldrops-python",
    project_urls={"Engine": "https://github.com/pilldrops-oss/pilldrops"},
    license="MIT",
    packages=find_packages(include=["pilldrops", "pilldrops.*", "sandforge", "sandforge.*",
                                    "yoursandbox", "yoursandbox.*"]),
    python_requires=">=3.8",
    install_requires=["requests>=2.28"],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
    ],
)
