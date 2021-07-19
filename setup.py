import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="docker-machine-api",
    version="1.0.0",
    author="Arno Duvenhage",
    author_email="aduvenhage@gmail.com",
    description="Docker-machine CLI wrapper that can be used from within Python applications to create and manage remote/cloud VM services using docker-machine",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/aduvenhage/docker-machine-api",
    project_urls={
    },
    classifiers=[
        "Programming Language :: Python :: 3",
    ],
    packages=setuptools.find_packages(),
    include_package_data=True,
    python_requires=">=3.6",
    install_requires=[

    ],
    setup_requires=[

    ]
)