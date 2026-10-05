"""numpy must not madvise transparent huge pages in a build process."""

import subprocess
import sys


def test_importing_the_package_turns_numpy_hugepage_madvise_off():
    """Run in a fresh interpreter: the variable only matters if it is set
    before numpy's first import, which is exactly what this checks.

    Mutation performed and reverted: delete the setdefault line -> red.
    """
    code = ("import os; os.environ.pop('NUMPY_MADVISE_HUGEPAGE', None); "
            "import transport_maps, numpy; "
            "print(os.environ.get('NUMPY_MADVISE_HUGEPAGE'))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "0"
