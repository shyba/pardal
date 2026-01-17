from setuptools import Extension, setup
from Cython.Build import cythonize

extensions = [
    Extension(
        "pcb_tool.fastpath._astar",
        ["pcb_tool/fastpath/_astar.pyx"],
    )
]

setup(
    ext_modules=cythonize(
        extensions,
        compiler_directives={"language_level": "3"},
    ),
)
