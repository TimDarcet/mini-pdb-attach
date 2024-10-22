import setuptools

setuptools.setup(
    name="pdb-attach",
    py_modules=["pdb_attach"],
    python_requires=">=3.3, <4",
    entry_points="""
        [console_scripts]
        pdb_attach=pdb_attach:main
    """,
)
