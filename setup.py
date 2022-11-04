from setuptools import setup

with open("requirements.txt") as fh:
    install_requires = fh.read()

name = "sscomp"
version = "1.0.0"
release = "1.0.0"

setup(
    name=name,
    version=version,
    release=release,
    packages=["sscomp"],
    author="SeaSmoke (@SeaSmoke#0002)",
    description="SeaSmoke's comparison script",
    url="https://github.com/notSeaSmoke/ss-comp",
    package_data={
        'sscomp': ['py.typed'],
    },
    install_requires=install_requires,
    python_requires=">=3.10",
    classifiers=[
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    command_options={
        "build_sphinx": {
            "project": ("setup.py", name),
            "version": ("setup.py", version),
            "release": ("setup.py", release),
            "source_dir": ("setup.py", "docs")
        }
    }
)
