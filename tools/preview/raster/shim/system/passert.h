#pragma once
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>

#define PASSERT_FAIL(msg) do { \
    fprintf(stderr, "pebble assert: %s at %s:%d\n", (msg), __FILE__, __LINE__); \
    abort(); \
  } while (0)

#define PBL_ASSERTN(expr)      do { if (!(expr)) PASSERT_FAIL(#expr); } while (0)
#define PBL_ASSERT(expr, ...)  do { if (!(expr)) PASSERT_FAIL(#expr); } while (0)
#define PBL_ASSERT_RUNTIME(expr, ...) PBL_ASSERTN(expr)
#define WTF                    PASSERT_FAIL("WTF")
#define PBL_CROAK(...)         PASSERT_FAIL("croak")
