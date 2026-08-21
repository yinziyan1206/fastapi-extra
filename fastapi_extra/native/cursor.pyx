# cython: language_level=3
# cython: boundscheck=False
# cython: wraparound=False
# cython: initializedcheck=False
# cython: nonecheck=False

cimport cython
from cpython cimport time
from libc.stdint cimport int64_t

DEF _sequence_length = 10
DEF max_count = 1 << _sequence_length
cdef int64_t _start_point = 157780800000


@cython.no_gc
cdef class Cursor:
    __slots__ = "cursor", "last_point", "seed"
    cdef:
        int cursor
        int seed
        int64_t last_point

    def __init__(self, seed: int):
        self.seed = seed % 16 
        self.cursor = 0
        self.last_point = 0

    cdef inline long long fetch(self, int step = 0):
        cdef:
            int count = 0
            int64_t point = <int64_t>(time.time() * 100) - _start_point + step
        
        if point <= self.last_point:
            point = self.last_point
            count = self.cursor
            if count >= max_count:
                return self.fetch(step + 1)
        else:
            self.last_point = point
        self.cursor = count + 1
        return <long long>((point << (_sequence_length + 4)) + (self.seed << _sequence_length) + count)

    def next_val(self) -> int:
        return self.fetch(0)
