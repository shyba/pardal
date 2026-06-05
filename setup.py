from setuptools import Extension, setup
from Cython.Build import cythonize

extensions = [
    Extension(
        "pardal.fastpath._astar",
        ["pardal/fastpath/_astar.pyx"],
    )
]

setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
)
