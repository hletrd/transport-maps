"""Global travel-time isochrone map: the build pipeline.

The console entry point is transport_maps.cli:main (see pyproject.toml).
"""

import os

# numpy madvises transparent huge pages for every large array. On a host whose
# memory is fragmented the kernel then tries, and fails, to compact memory on
# each allocation: rebuild 28's first start on h200 (2026-10-05) spent its
# workers' time there -- 415 of 415 compactions failed in 20 s, user CPU 3% and
# system 21% -- and finished one origin in half an hour. It must be set before
# numpy is first imported, which this package import always precedes; an
# operator who wants the old behaviour can still set it to 1.
os.environ.setdefault("NUMPY_MADVISE_HUGEPAGE", "0")
