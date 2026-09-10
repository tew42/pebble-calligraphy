#include <pebble.h>

/*
 * Calligraph: A minimalist calligraphic analog watchface for Pebble
 *
 * Design & Implementation: Thomas Winkler
 * Acknowledgment: Lell ("Minimal" watchface)
 * Assisted by: GPT-5.6 Sol
 * 
 * This watchface represents the hour and minute hands as a single
 * continuous calligraphic stroke. Radial sections at both ends are
 * joined by a dynamically shaped minimum-bending spline, with the
 * stroke width varying along its arc length.
 *
 * The visual concept was inspired by "Minimal", a watchface for
 * earlier-generation Pebble watches by Lell. This implementation,
 * including its spline geometry, pivot shaping, width profile, and
 * polygonal stroke construction, was developed independently.
 *
 * This is an independent application for the Pebble platform.
 */

/* Development controls when compiled as a watchapp:
 *   UP   = advance one minute
 *   DOWN = advance one hour
 */
#define ENABLE_DEBUG_TIME 0

#define DRAW_ANTIALIASED_OUTLINE 1
#define DRAW_MINUTE_PIXEL_CORE 1

#define HOUR_STEM_SEGMENTS 8
#define CONNECTOR_SEGMENTS 30
#define MINUTE_STEM_SEGMENTS 10

#if HOUR_STEM_SEGMENTS < 1
#error HOUR_STEM_SEGMENTS must be at least 1
#endif

#if MINUTE_STEM_SEGMENTS < 1
#error MINUTE_STEM_SEGMENTS must be at least 1
#endif

#if CONNECTOR_SEGMENTS < 4
#error CONNECTOR_SEGMENTS must be at least 4
#endif

#define CENTERLINE_POINT_COUNT \
  (HOUR_STEM_SEGMENTS + CONNECTOR_SEGMENTS + \
   MINUTE_STEM_SEGMENTS + 1)

#define POLYGON_POINT_COUNT \
  (CENTERLINE_POINT_COUNT * 2)

#if CENTERLINE_POINT_COUNT > 255
#error CENTERLINE_POINT_COUNT must fit in uint8_t
#endif

#define HOUR_LENGTH_RATIO 0.60f
#define MINUTE_LENGTH_RATIO 0.90f

#define HOUR_STEM_RATIO 0.25f
#define MINUTE_STEM_RATIO 0.4f

#define HOUR_TIP_WIDTH 3.0f
#define HOUR_BODY_WIDTH 6.0f
#define MIDDLE_WIDTH 3.0f
#define MINUTE_TIP_WIDTH 1.0f

/* The narrowest the stroke is ever drawn. Not a design parameter: one pixel is
   the floor the display imposes. It coincides with MINUTE_TIP_WIDTH only by
   arithmetic accident, so it is named separately. */
#define MINIMUM_STROKE_WIDTH 1.0f

#define HOUR_SWELL_POSITION 0.05f
#define PRESSURE_VARIATION 0.20f

#if DRAW_ANTIALIASED_OUTLINE
#define OUTLINE_WIDTH_COMPENSATION 1.0f
#else
#define OUTLINE_WIDTH_COMPENSATION 0.0f
#endif

#define VECTOR_EPSILON 0.0001f
#define SOLVER_EPSILON 0.00001f
#define MIN_PARAMETER_LENGTH 0.001f
#define SOLVER_REGULARIZATION 0.0001f
#define MAX_SOLVER_RESULT_MAGNITUDE 100.0f

#define SOLVER_VARIABLE_COUNT 4
#define SOLVER_AUGMENTED_COLUMN_COUNT 5

typedef struct {
  float x;
  float y;
} Vec2;

typedef struct {
  int32_t hour;
  int32_t minute;
} ClockAngles;

typedef struct {
  Vec2 point;
  float waist_opening;
} PivotResult;

typedef struct {
  uint8_t pivot_index;
  float waist_opening;
} CenterlineResult;

typedef struct {
  GRect bounds;
  uint16_t time_key;
  uint8_t pivot_index;
  bool valid;
} GeometryState;

typedef struct {
  /*
   * Columns 0 through 3 contain the coefficient matrix.
   * Column 4 contains the right-hand side and, after solving,
   * the solution.
   */
  float augmented
    [SOLVER_VARIABLE_COUNT]
    [SOLVER_AUGMENTED_COLUMN_COUNT];

  /*
   * These coefficient arrays have a fixed sparse structure.
   * Their constant entries are initialized once during init().
   * Only the two radial entries change for each geometry rebuild.
   */
  Vec2 hour_start_coefficients
    [SOLVER_VARIABLE_COUNT];

  Vec2 hour_end_coefficients
    [SOLVER_VARIABLE_COUNT];

  Vec2 minute_start_coefficients
    [SOLVER_VARIABLE_COUNT];

  Vec2 minute_end_coefficients
    [SOLVER_VARIABLE_COUNT];
} SolverWorkspace;

static Window *s_main_window;
static Layer *s_canvas_layer;
static GPath *s_stroke_path;

static bool s_tick_timer_subscribed;
static struct tm s_current_time;

#if ENABLE_DEBUG_TIME
static int32_t s_debug_offset_minutes;
#endif

static Vec2 s_centerline[CENTERLINE_POINT_COUNT];
static float s_cumulative_length[CENTERLINE_POINT_COUNT];
static GPoint s_polygon_points[POLYGON_POINT_COUNT];

static GeometryState s_geometry_state;
static SolverWorkspace s_solver_workspace;

static GPathInfo s_path_info = {
  .num_points = POLYGON_POINT_COUNT,
  .points = s_polygon_points
};

static const Vec2 UNIT_X_VECTOR = {
  .x = 1.0f,
  .y = 0.0f
};

static const Vec2 UNIT_Y_VECTOR = {
  .x = 0.0f,
  .y = 1.0f
};

/* ------------------------------------------------------------------------- */
/* Math                                                                      */
/* ------------------------------------------------------------------------- */

static float clamp_float(
    float value,
    float minimum,
    float maximum
) {
  if (value < minimum) {
    return minimum;
  }

  if (value > maximum) {
    return maximum;
  }

  return value;
}

static float absolute_float(float value) {
  return value < 0.0f
    ? -value
    : value;
}

/*
 * IEEE-754 exponent estimate followed by three Newton refinements.
 * This is retained to avoid depending on firmware-specific floating-point
 * square-root availability.
 */
static float square_root_float(float value) {
  if (value <= 0.0f) {
    return 0.0f;
  }

  union {
    float value;
    uint32_t bits;
  } estimate = {
    .value = value
  };

  estimate.bits =
    (estimate.bits >> 1) +
    0x1FC00000u;

  for (int iteration = 0; iteration < 3; ++iteration) {
    estimate.value =
      0.5f *
      (
        estimate.value +
        value / estimate.value
      );
  }

  return estimate.value;
}

static float interpolate_float(
    float a,
    float b,
    float amount
) {
  return a + (b - a) * amount;
}

static float smooth_unit(float value) {
  const float position =
    clamp_float(value, 0.0f, 1.0f);

  return
    position *
    position *
    (3.0f - 2.0f * position);
}

static float safe_parameter_length(float length) {
  return length > MIN_PARAMETER_LENGTH
    ? length
    : MIN_PARAMETER_LENGTH;
}

static Vec2 make_vec2(float x, float y) {
  return (Vec2) {
    .x = x,
    .y = y
  };
}

static Vec2 add_vec2(Vec2 a, Vec2 b) {
  return make_vec2(
    a.x + b.x,
    a.y + b.y
  );
}

static Vec2 subtract_vec2(Vec2 a, Vec2 b) {
  return make_vec2(
    a.x - b.x,
    a.y - b.y
  );
}

static Vec2 multiply_vec2(Vec2 vector, float amount) {
  return make_vec2(
    vector.x * amount,
    vector.y * amount
  );
}

static float dot_vec2(Vec2 a, Vec2 b) {
  return
    a.x * b.x +
    a.y * b.y;
}

static float length_vec2(Vec2 vector) {
  return square_root_float(
    vector.x * vector.x +
    vector.y * vector.y
  );
}

static float distance_between(Vec2 a, Vec2 b) {
  return length_vec2(
    subtract_vec2(b, a)
  );
}

static Vec2 normalize_vec2(Vec2 vector) {
  const float length =
    length_vec2(vector);

  if (length < VECTOR_EPSILON) {
    return make_vec2(0.0f, -1.0f);
  }

  return multiply_vec2(
    vector,
    1.0f / length
  );
}

static Vec2 direction_between(Vec2 from, Vec2 to) {
  return normalize_vec2(
    subtract_vec2(to, from)
  );
}

static int16_t round_coordinate(float value) {
  return value >= 0.0f
    ? (int16_t)(value + 0.5f)
    : (int16_t)(value - 0.5f);
}

static GPoint vec2_to_gpoint(Vec2 point) {
  return GPoint(
    round_coordinate(point.x),
    round_coordinate(point.y)
  );
}

/* ------------------------------------------------------------------------- */
/* Clock geometry                                                            */
/* ------------------------------------------------------------------------- */

static Vec2 point_on_clock(
    Vec2 center,
    int32_t pebble_angle,
    float length
) {
  const float coordinate_scale =
    length / (float)TRIG_MAX_RATIO;

  return make_vec2(
    center.x +
      (float)sin_lookup(pebble_angle) *
      coordinate_scale,

    center.y -
      (float)cos_lookup(pebble_angle) *
      coordinate_scale
  );
}

static int32_t minute_to_pebble_angle(int minutes) {
  return (int32_t)(
    ((int64_t)TRIG_MAX_ANGLE * minutes) /
    60
  );
}

static int32_t hour_to_pebble_angle(
    int hours,
    int minutes
) {
  const int total_minutes =
    (hours % 12) * 60 + minutes;

  return (int32_t)(
    ((int64_t)TRIG_MAX_ANGLE * total_minutes) /
    (12 * 60)
  );
}

static ClockAngles get_current_clock_angles(void) {
  const int hours =
    s_current_time.tm_hour % 12;

  const int minutes =
    s_current_time.tm_min;

  return (ClockAngles) {
    .hour = hour_to_pebble_angle(
      hours,
      minutes
    ),

    .minute = minute_to_pebble_angle(
      minutes
    )
  };
}

static uint16_t get_current_time_key(void) {
  return (uint16_t)(
    (s_current_time.tm_hour % 12) * 60 +
    s_current_time.tm_min
  );
}

/* ------------------------------------------------------------------------- */
/* Pivot                                                                     */
/* ------------------------------------------------------------------------- */

/*
 * The pivot sits on the hands' angle bisector, at
 *
 *   s = min(r_h, r_m) * cos(d/2) * sin(d/2) / (1 + sin(d/2))
 *
 * where d is the angle between the hands and r_h, r_m are the radii at which
 * the two straight stems end.
 *
 * Both stem tangent lines are radial, so they always meet at the watch centre
 * and the connector is always a rounded corner of the triangle (A, centre, B).
 * The deepest such rounding is a circular arc tangent to both radial lines,
 * and the circle tangent to one of them at radius r, centred on the bisector,
 * crosses the bisector at r * cos(d/2) / (1 + sin(d/2)).  Tangency to both
 * radials at unequal radii is impossible, so the shorter stem governs and that
 * expression is a ceiling on how far out the pivot can sit before the
 * curvature flattens at the pivot instead of peaking there.
 *
 * The sin(d/2) factor spends that ceiling according to how open the hands are.
 * It goes to zero at overlap, where the connector has to fold through the true
 * centre, and approaches the full ceiling near opposition, where the connector
 * is nearly straight and the ceiling itself has collapsed.
 *
 * Written as cos/(1 + sin) rather than the algebraically identical
 * (1 - sin)/cos so that there is no 0/0 at opposition, and so that the whole
 * rule needs nothing but square roots -- no atan, no division by a vanishing
 * cosine.
 *
 * Two properties this has and its predecessor did not.  It carries no tuned
 * constants: every term is either a half-angle of the hand separation or a
 * stem radius.  And it scales with the stems rather than with the face, so
 * changing a stem ratio moves the pivot with the curve instead of leaving it
 * behind; the previous rule was anchored to the face radius, so the pivot sat
 * 12.6 px from the centre at quadrature no matter what the stems were doing.
 */
static PivotResult calculate_pivot_point(
    Vec2 center,
    Vec2 hour_connector_point,
    Vec2 minute_connector_point
) {
  const Vec2 hour_radial =
    direction_between(
      center,
      hour_connector_point
    );

  const Vec2 minute_radial =
    direction_between(
      center,
      minute_connector_point
    );

  const Vec2 direction_sum =
    add_vec2(
      hour_radial,
      minute_radial
    );

  const float direction_sum_length =
    length_vec2(direction_sum);

  /*
   * Hands exactly opposed: there is no bisector, and no offset is wanted.  The
   * stems are also as far apart as they ever get, so the waist is wide open.
   */
  if (direction_sum_length < VECTOR_EPSILON) {
    return (PivotResult) { center, 1.0f };
  }

  const float radial_dot =
    clamp_float(
      dot_vec2(
        hour_radial,
        minute_radial
      ),
      -1.0f,
      1.0f
    );

  const float cosine_half_angle =
    square_root_float(
      clamp_float(
        0.5f *
        (1.0f + radial_dot),
        0.0f,
        1.0f
      )
    );

  const float sine_half_angle =
    square_root_float(
      clamp_float(
        0.5f *
        (1.0f - radial_dot),
        0.0f,
        1.0f
      )
    );

  const float hour_inner_radius =
    distance_between(
      center,
      hour_connector_point
    );

  const float minute_inner_radius =
    distance_between(
      center,
      minute_connector_point
    );

  const float smaller_inner_radius =
    hour_inner_radius < minute_inner_radius
      ? hour_inner_radius
      : minute_inner_radius;

  const float pivot_offset =
    smaller_inner_radius *
    cosine_half_angle *
    sine_half_angle /
    (1.0f + sine_half_angle);

  /*
   * How far apart the two stems end, measured across rather than along: the
   * chord subtended at the shorter stem's radius.  It goes to zero as the hands
   * close, whatever the two stem lengths are, which is what the waist wants --
   * the straight-line distance between the stem ends would not, since they sit
   * at different radii and stay MINUTE_STEM - HOUR_STEM apart at overlap.
   *
   * Computed here rather than in build_centerline because every term it needs
   * is already in hand for the pivot offset above.  Deriving it there a second
   * time cost a dot product and three square roots -- nine divisions, since
   * square_root_float is three Newton iterations -- on every rebuild.
   */
  const float stem_separation =
    2.0f *
    smaller_inner_radius *
    sine_half_angle;

  return (PivotResult) {
    add_vec2(
      center,
      multiply_vec2(
        direction_sum,
        pivot_offset / direction_sum_length
      )
    ),
    clamp_float(
      stem_separation /
      MIDDLE_WIDTH,
      0.0f,
      1.0f
    )
  };
}

/* ------------------------------------------------------------------------- */
/* Four-by-four linear solver                                                */
/* ------------------------------------------------------------------------- */

static void clear_augmented_system(
    float augmented
      [SOLVER_VARIABLE_COUNT]
      [SOLVER_AUGMENTED_COLUMN_COUNT]
) {
  for (
      int row = 0;
      row < SOLVER_VARIABLE_COUNT;
      ++row
  ) {
    for (
        int column = 0;
        column < SOLVER_AUGMENTED_COLUMN_COUNT;
        ++column
    ) {
      augmented[row][column] = 0.0f;
    }
  }
}

static bool solve_augmented_system_4x4(
    float augmented
      [SOLVER_VARIABLE_COUNT]
      [SOLVER_AUGMENTED_COLUMN_COUNT]
) {
  for (
      int pivot_column = 0;
      pivot_column < SOLVER_VARIABLE_COUNT;
      ++pivot_column
  ) {
    int pivot_row =
      pivot_column;

    float largest_value =
      absolute_float(
        augmented[pivot_row][pivot_column]
      );

    for (
        int row = pivot_column + 1;
        row < SOLVER_VARIABLE_COUNT;
        ++row
    ) {
      const float candidate =
        absolute_float(
          augmented[row][pivot_column]
        );

      if (candidate > largest_value) {
        largest_value = candidate;
        pivot_row = row;
      }
    }

    if (largest_value < SOLVER_EPSILON) {
      return false;
    }

    if (pivot_row != pivot_column) {
      for (
          int column = pivot_column;
          column < SOLVER_AUGMENTED_COLUMN_COUNT;
          ++column
      ) {
        const float temporary =
          augmented[pivot_column][column];

        augmented[pivot_column][column] =
          augmented[pivot_row][column];

        augmented[pivot_row][column] =
          temporary;
      }
    }

    const float pivot_value =
      augmented[pivot_column][pivot_column];

    /*
     * Retain per-element division rather than reciprocal
     * multiplication to preserve floating-point behavior.
     */
    for (
        int column = pivot_column;
        column < SOLVER_AUGMENTED_COLUMN_COUNT;
        ++column
    ) {
      augmented[pivot_column][column] /=
        pivot_value;
    }

    for (
        int row = 0;
        row < SOLVER_VARIABLE_COUNT;
        ++row
    ) {
      if (row == pivot_column) {
        continue;
      }

      const float factor =
        augmented[row][pivot_column];

      if (absolute_float(factor) < SOLVER_EPSILON) {
        continue;
      }

      for (
          int column = pivot_column;
          column < SOLVER_AUGMENTED_COLUMN_COUNT;
          ++column
      ) {
        augmented[row][column] -=
          factor *
          augmented[pivot_column][column];
      }
    }
  }

  return true;
}

static bool solver_result_is_valid(
    float augmented
      [SOLVER_VARIABLE_COUNT]
      [SOLVER_AUGMENTED_COLUMN_COUNT]
) {
  for (
      int index = 0;
      index < SOLVER_VARIABLE_COUNT;
      ++index
  ) {
    const float value =
      augmented[index][SOLVER_VARIABLE_COUNT];

    if (
      value != value ||
      absolute_float(value) >
        MAX_SOLVER_RESULT_MAGNITUDE
    ) {
      return false;
    }
  }

  return true;
}

/* ------------------------------------------------------------------------- */
/* Minimum-bending spline                                                    */
/* ------------------------------------------------------------------------- */

static void add_minimum_bending_segment(
    float augmented
      [SOLVER_VARIABLE_COUNT]
      [SOLVER_AUGMENTED_COLUMN_COUNT],
    Vec2 start_point,
    Vec2 end_point,
    float safe_length,
    const Vec2 start_coefficients
      [SOLVER_VARIABLE_COUNT],
    const Vec2 end_coefficients
      [SOLVER_VARIABLE_COUNT]
) {
  const float inverse_length =
    1.0f / safe_length;

  const float inverse_length_squared =
    inverse_length * inverse_length;

  const Vec2 chord =
    subtract_vec2(
      end_point,
      start_point
    );

  for (
      int row = 0;
      row < SOLVER_VARIABLE_COUNT;
      ++row
  ) {
    augmented[row][SOLVER_VARIABLE_COUNT] +=
      12.0f *
      inverse_length_squared *
      dot_vec2(
        chord,
        add_vec2(
          start_coefficients[row],
          end_coefficients[row]
        )
      );

    for (
        int column = 0;
        column < SOLVER_VARIABLE_COUNT;
        ++column
    ) {
      const float same_endpoint_term =
        dot_vec2(
          start_coefficients[row],
          start_coefficients[column]
        ) +
        dot_vec2(
          end_coefficients[row],
          end_coefficients[column]
        );

      const float cross_endpoint_term =
        dot_vec2(
          start_coefficients[row],
          end_coefficients[column]
        ) +
        dot_vec2(
          start_coefficients[column],
          end_coefficients[row]
        );

      augmented[row][column] +=
        inverse_length *
        (
          8.0f * same_endpoint_term +
          4.0f * cross_endpoint_term
        );
    }
  }
}

static void calculate_minimum_bending_derivatives(
    Vec2 hour_connector_point,
    Vec2 guide_point,
    Vec2 minute_connector_point,
    Vec2 hour_radial_in,
    Vec2 minute_radial_out,
    float safe_hour_span,
    float safe_minute_span,
    Vec2 *result_hour_derivative,
    Vec2 *result_guide_derivative,
    Vec2 *result_minute_derivative
) {
  float (*augmented)[SOLVER_AUGMENTED_COLUMN_COUNT] =
    s_solver_workspace.augmented;

  Vec2 *hour_start_coefficients =
    s_solver_workspace.hour_start_coefficients;

  Vec2 *hour_end_coefficients =
    s_solver_workspace.hour_end_coefficients;

  Vec2 *minute_start_coefficients =
    s_solver_workspace.minute_start_coefficients;

  Vec2 *minute_end_coefficients =
    s_solver_workspace.minute_end_coefficients;

  clear_augmented_system(augmented);

  /*
   * The remaining coefficient entries are fixed and were initialized
   * once in initialize_solver_workspace().
   */
  hour_start_coefficients[0] =
    hour_radial_in;

  minute_end_coefficients[3] =
    minute_radial_out;

  add_minimum_bending_segment(
    augmented,
    hour_connector_point,
    guide_point,
    safe_hour_span,
    hour_start_coefficients,
    hour_end_coefficients
  );

  add_minimum_bending_segment(
    augmented,
    guide_point,
    minute_connector_point,
    safe_minute_span,
    minute_start_coefficients,
    minute_end_coefficients
  );

  for (
      int index = 0;
      index < SOLVER_VARIABLE_COUNT;
      ++index
  ) {
    augmented[index][index] +=
      SOLVER_REGULARIZATION;
  }

  if (
    solve_augmented_system_4x4(augmented) &&
    solver_result_is_valid(augmented)
  ) {
    const float hour_solution =
      augmented[0][SOLVER_VARIABLE_COUNT];

    const float minute_solution =
      augmented[3][SOLVER_VARIABLE_COUNT];

    const float hour_magnitude =
      hour_solution > 0.0f
        ? hour_solution
        : 0.0f;

    const float minute_magnitude =
      minute_solution > 0.0f
        ? minute_solution
        : 0.0f;

    *result_hour_derivative =
      multiply_vec2(
        hour_radial_in,
        hour_magnitude
      );

    *result_guide_derivative =
      make_vec2(
        augmented[1][SOLVER_VARIABLE_COUNT],
        augmented[2][SOLVER_VARIABLE_COUNT]
      );

    *result_minute_derivative =
      multiply_vec2(
        minute_radial_out,
        minute_magnitude
      );

    return;
  }

  *result_hour_derivative =
    multiply_vec2(
      hour_radial_in,
      0.5f
    );

  *result_guide_derivative =
    direction_between(
      hour_connector_point,
      minute_connector_point
    );

  *result_minute_derivative =
    multiply_vec2(
      minute_radial_out,
      0.5f
    );
}

static void initialize_solver_workspace(void) {
  /*
   * Static storage is already zero-filled. Set only the four fixed
   * nonzero coefficient entries.
   *
   * Hour connector:
   *   D0 = x[0] * hour_radial_in
   *   D1 = (x[1], x[2])
   *
   * Minute connector:
   *   D0 = (x[1], x[2])
   *   D1 = x[3] * minute_radial_out
   */
  s_solver_workspace
    .hour_end_coefficients[1] =
      UNIT_X_VECTOR;

  s_solver_workspace
    .hour_end_coefficients[2] =
      UNIT_Y_VECTOR;

  s_solver_workspace
    .minute_start_coefficients[1] =
      UNIT_X_VECTOR;

  s_solver_workspace
    .minute_start_coefficients[2] =
      UNIT_Y_VECTOR;
}

/* ------------------------------------------------------------------------- */
/* Sampling                                                                  */
/* ------------------------------------------------------------------------- */

static Vec2 cubic_hermite(
    Vec2 start_point,
    Vec2 end_point,
    Vec2 start_derivative,
    Vec2 end_derivative,
    float parameter_length,
    float amount
) {
  const float t =
    clamp_float(amount, 0.0f, 1.0f);

  const float t_squared =
    t * t;

  const float t_cubed =
    t_squared * t;

  const float h00 =
    2.0f * t_cubed -
    3.0f * t_squared +
    1.0f;

  const float h10 =
    t_cubed -
    2.0f * t_squared +
    t;

  const float h01 =
    -2.0f * t_cubed +
    3.0f * t_squared;

  const float h11 =
    t_cubed -
    t_squared;

  return make_vec2(
    h00 * start_point.x +
      h10 *
      parameter_length *
      start_derivative.x +
      h01 * end_point.x +
      h11 *
      parameter_length *
      end_derivative.x,

    h00 * start_point.y +
      h10 *
      parameter_length *
      start_derivative.y +
      h01 * end_point.y +
      h11 *
      parameter_length *
      end_derivative.y
  );
}

static void sample_hermite_section(
    int first_index,
    int last_index,
    Vec2 start_point,
    Vec2 end_point,
    Vec2 start_derivative,
    Vec2 end_derivative,
    float parameter_length
) {
  const int segment_count =
    last_index - first_index;

  if (segment_count <= 0) {
    s_centerline[first_index] =
      start_point;
    return;
  }

  const float inverse_segment_count =
    1.0f / (float)segment_count;

  for (
      int index = first_index;
      index <= last_index;
      ++index
  ) {
    const float amount =
      (float)(index - first_index) *
      inverse_segment_count;

    s_centerline[index] =
      cubic_hermite(
        start_point,
        end_point,
        start_derivative,
        end_derivative,
        parameter_length,
        amount
      );
  }
}

static void fill_line_samples(
    int first_index,
    int last_index,
    Vec2 first_point,
    Vec2 last_point
) {
  const int segment_count =
    last_index - first_index;

  if (segment_count <= 0) {
    s_centerline[first_index] =
      first_point;
    return;
  }

  const float inverse_segment_count =
    1.0f / (float)segment_count;

  for (
      int index = first_index;
      index <= last_index;
      ++index
  ) {
    const float amount =
      (float)(index - first_index) *
      inverse_segment_count;

    s_centerline[index] =
      make_vec2(
        interpolate_float(
          first_point.x,
          last_point.x,
          amount
        ),
        interpolate_float(
          first_point.y,
          last_point.y,
          amount
        )
      );
  }
}

/* ------------------------------------------------------------------------- */
/* Centerline                                                                */
/* ------------------------------------------------------------------------- */

static CenterlineResult build_centerline(
    Vec2 center,
    float maximum_radius,
    int32_t hour_angle,
    int32_t minute_angle
) {
  CenterlineResult result = {
    .pivot_index =
      (uint8_t)(CENTERLINE_POINT_COUNT / 2),

    .waist_opening = 1.0f
  };

  const float hour_length =
    maximum_radius *
    HOUR_LENGTH_RATIO;

  const float minute_length =
    maximum_radius *
    MINUTE_LENGTH_RATIO;

  const Vec2 hour_point =
    point_on_clock(
      center,
      hour_angle,
      hour_length
    );

  const Vec2 minute_point =
    point_on_clock(
      center,
      minute_angle,
      minute_length
    );

  const Vec2 hour_radial_out =
    direction_between(
      center,
      hour_point
    );

  const Vec2 minute_radial_out =
    direction_between(
      center,
      minute_point
    );

  const Vec2 hour_radial_in =
    multiply_vec2(
      hour_radial_out,
      -1.0f
    );

  const Vec2 hour_connector_point =
    add_vec2(
      hour_point,
      multiply_vec2(
        hour_radial_in,
        hour_length *
        HOUR_STEM_RATIO
      )
    );

  const Vec2 minute_connector_point =
    subtract_vec2(
      minute_point,
      multiply_vec2(
        minute_radial_out,
        minute_length *
        MINUTE_STEM_RATIO
      )
    );

  /*
   * The pivot is placed from where the stems end, not from where the hands
   * end, so the connector points have to be in hand before it is placed.
   */
  const PivotResult pivot =
    calculate_pivot_point(
      center,
      hour_connector_point,
      minute_connector_point
    );

  const Vec2 guide_point =
    pivot.point;

  const int connector_first_index =
    HOUR_STEM_SEGMENTS;

  const int connector_last_index =
    HOUR_STEM_SEGMENTS +
    CONNECTOR_SEGMENTS;

  const float hour_span =
    distance_between(
      hour_connector_point,
      guide_point
    );

  const float minute_span =
    distance_between(
      guide_point,
      minute_connector_point
    );

  const float safe_hour_span =
    safe_parameter_length(hour_span);

  const float safe_minute_span =
    safe_parameter_length(minute_span);

  const float total_connector_span =
    hour_span + minute_span;

  float hour_fraction =
    0.5f;

  if (total_connector_span > VECTOR_EPSILON) {
    hour_fraction =
      hour_span /
      total_connector_span;
  }

  int guide_index =
    connector_first_index +
    (int)(
      CONNECTOR_SEGMENTS *
      hour_fraction +
      0.5f
    );

  const int minimum_guide_index =
    connector_first_index + 2;

  const int maximum_guide_index =
    connector_last_index - 2;

  if (guide_index < minimum_guide_index) {
    guide_index =
      minimum_guide_index;
  } else if (guide_index > maximum_guide_index) {
    guide_index =
      maximum_guide_index;
  }

  result.pivot_index =
    (uint8_t)guide_index;

  Vec2 hour_derivative;
  Vec2 guide_derivative;
  Vec2 minute_derivative;

  calculate_minimum_bending_derivatives(
    hour_connector_point,
    guide_point,
    minute_connector_point,
    hour_radial_in,
    minute_radial_out,
    safe_hour_span,
    safe_minute_span,
    &hour_derivative,
    &guide_derivative,
    &minute_derivative
  );

  fill_line_samples(
    0,
    connector_first_index,
    hour_point,
    hour_connector_point
  );

  fill_line_samples(
    connector_last_index,
    CENTERLINE_POINT_COUNT - 1,
    minute_connector_point,
    minute_point
  );

  sample_hermite_section(
    connector_first_index,
    guide_index,
    hour_connector_point,
    guide_point,
    hour_derivative,
    guide_derivative,
    safe_hour_span
  );

  sample_hermite_section(
    guide_index,
    connector_last_index,
    guide_point,
    minute_connector_point,
    guide_derivative,
    minute_derivative,
    safe_minute_span
  );

  result.waist_opening =
    pivot.waist_opening;

  return result;
}

/* ------------------------------------------------------------------------- */
/* Arc-length cache                                                          */
/* ------------------------------------------------------------------------- */

static void update_cumulative_lengths(void) {
  s_cumulative_length[0] =
    0.0f;

  for (
      int index = 1;
      index < CENTERLINE_POINT_COUNT;
      ++index
  ) {
    s_cumulative_length[index] =
      s_cumulative_length[index - 1] +
      distance_between(
        s_centerline[index - 1],
        s_centerline[index]
      );
  }
}

/* ------------------------------------------------------------------------- */
/* Width profile                                                             */
/* ------------------------------------------------------------------------- */

static float calculate_stroke_width(
    float position,
    float pivot_position,
    float middle_width
) {
  if (position <= pivot_position) {
    if (pivot_position < VECTOR_EPSILON) {
      return middle_width;
    }

    const float hour_position =
      clamp_float(
        position /
        pivot_position,
        0.0f,
        1.0f
      );

    if (hour_position <= HOUR_SWELL_POSITION) {
      const float swell_position =
        HOUR_SWELL_POSITION > VECTOR_EPSILON
          ? hour_position /
            HOUR_SWELL_POSITION
          : 1.0f;

      return interpolate_float(
        HOUR_TIP_WIDTH,
        HOUR_BODY_WIDTH,
        smooth_unit(swell_position)
      );
    }

    const float contraction_position =
      (
        hour_position -
        HOUR_SWELL_POSITION
      ) /
      (
        1.0f -
        HOUR_SWELL_POSITION
      );

    return interpolate_float(
      HOUR_BODY_WIDTH,
      middle_width,
      smooth_unit(contraction_position)
    );
  }

  const float remaining_length =
    1.0f - pivot_position;

  if (remaining_length < VECTOR_EPSILON) {
    return middle_width;
  }

  const float minute_position =
    clamp_float(
      (
        position -
        pivot_position
      ) /
      remaining_length,
      0.0f,
      1.0f
    );

  return interpolate_float(
    middle_width,
    MINUTE_TIP_WIDTH,
    smooth_unit(minute_position)
  );
}

/* ------------------------------------------------------------------------- */
/* Stroke polygon                                                            */
/* ------------------------------------------------------------------------- */

static Vec2 calculate_centerline_tangent(int index) {
  if (index <= 0) {
    return direction_between(
      s_centerline[0],
      s_centerline[1]
    );
  }

  if (index >= CENTERLINE_POINT_COUNT - 1) {
    return direction_between(
      s_centerline[CENTERLINE_POINT_COUNT - 2],
      s_centerline[CENTERLINE_POINT_COUNT - 1]
    );
  }

  const Vec2 incoming_delta =
    subtract_vec2(
      s_centerline[index],
      s_centerline[index - 1]
    );

  const Vec2 outgoing_delta =
    subtract_vec2(
      s_centerline[index + 1],
      s_centerline[index]
    );

  const float incoming_length =
    length_vec2(incoming_delta);

  const float outgoing_length =
    length_vec2(outgoing_delta);

  if (
    incoming_length < VECTOR_EPSILON &&
    outgoing_length < VECTOR_EPSILON
  ) {
    return make_vec2(0.0f, -1.0f);
  }

  if (incoming_length < VECTOR_EPSILON) {
    return multiply_vec2(
      outgoing_delta,
      1.0f / outgoing_length
    );
  }

  if (outgoing_length < VECTOR_EPSILON) {
    return multiply_vec2(
      incoming_delta,
      1.0f / incoming_length
    );
  }

  const Vec2 incoming_direction =
    multiply_vec2(
      incoming_delta,
      1.0f / incoming_length
    );

  const Vec2 outgoing_direction =
    multiply_vec2(
      outgoing_delta,
      1.0f / outgoing_length
    );

  const Vec2 direction_sum =
    add_vec2(
      incoming_direction,
      outgoing_direction
    );

  const float direction_sum_length =
    length_vec2(direction_sum);

  if (direction_sum_length < VECTOR_EPSILON) {
    return outgoing_direction;
  }

  return multiply_vec2(
    direction_sum,
    1.0f / direction_sum_length
  );
}

static void build_stroke_polygon(
    uint8_t pivot_index,
    float waist_opening
) {
  update_cumulative_lengths();

  const float total_length =
    s_cumulative_length[
      CENTERLINE_POINT_COUNT - 1
    ];

  const float pivot_length =
    s_cumulative_length[pivot_index];

  const bool has_length =
    total_length > VECTOR_EPSILON;

  const float pivot_position =
    has_length
      ? pivot_length / total_length
      : 0.0f;

  const float effective_middle_width =
    interpolate_float(
      MINIMUM_STROKE_WIDTH,
      MIDDLE_WIDTH,
      smooth_unit(waist_opening)
    );

  for (
      int index = 0;
      index < CENTERLINE_POINT_COUNT;
      ++index
  ) {
    const float position =
      has_length
        ? s_cumulative_length[index] /
          total_length
        : 0.0f;

    float stroke_width =
      calculate_stroke_width(
        position,
        pivot_position,
        effective_middle_width
      );

    const float body_envelope =
      4.0f *
      position *
      (1.0f - position);

    const float pressure_bias =
      1.0f +
      PRESSURE_VARIATION *
      body_envelope *
      (pivot_position - position);

    stroke_width *=
      pressure_bias;

    const float adjusted_width =
      stroke_width -
      OUTLINE_WIDTH_COMPENSATION;

    const float polygon_width =
      adjusted_width > 0.0f
        ? adjusted_width
        : 0.0f;

    const float half_width =
      polygon_width * 0.5f;

    const Vec2 tangent =
      calculate_centerline_tangent(index);

    const Vec2 normal =
      make_vec2(
        -tangent.y,
        tangent.x
      );

    const Vec2 normal_offset =
      multiply_vec2(
        normal,
        half_width
      );

    const Vec2 left =
      add_vec2(
        s_centerline[index],
        normal_offset
      );

    const Vec2 right =
      subtract_vec2(
        s_centerline[index],
        normal_offset
      );

    s_polygon_points[index] =
      vec2_to_gpoint(left);

    s_polygon_points[
      POLYGON_POINT_COUNT - 1 - index
    ] = vec2_to_gpoint(right);
  }

  const GPoint minute_tip =
    vec2_to_gpoint(
      s_centerline[
        CENTERLINE_POINT_COUNT - 1
      ]
    );

  s_polygon_points[
    CENTERLINE_POINT_COUNT - 1
  ] = minute_tip;

  s_polygon_points[
    CENTERLINE_POINT_COUNT
  ] = minute_tip;
}

/* ------------------------------------------------------------------------- */
/* Geometry cache                                                            */
/* ------------------------------------------------------------------------- */

static void invalidate_geometry(void) {
  s_geometry_state.valid =
    false;
}

static bool rebuild_geometry(
    GRect bounds,
    ClockAngles angles,
    uint16_t time_key
) {
  if (
    bounds.size.w <= 0 ||
    bounds.size.h <= 0
  ) {
    invalidate_geometry();
    return false;
  }

  const Vec2 center =
    make_vec2(
      bounds.origin.x +
        bounds.size.w * 0.5f,

      bounds.origin.y +
        bounds.size.h * 0.5f
    );

  const int16_t minimum_dimension =
    bounds.size.w < bounds.size.h
      ? bounds.size.w
      : bounds.size.h;

  const float maximum_radius =
    minimum_dimension * 0.5f;

  const CenterlineResult centerline_result =
    build_centerline(
      center,
      maximum_radius,
      angles.hour,
      angles.minute
    );

  build_stroke_polygon(
    centerline_result.pivot_index,
    centerline_result.waist_opening
  );

  s_geometry_state.bounds =
    bounds;

  s_geometry_state.time_key =
    time_key;

  s_geometry_state.pivot_index =
    centerline_result.pivot_index;

  s_geometry_state.valid =
    true;

  return true;
}

static bool ensure_geometry(GRect bounds) {
  const uint16_t time_key =
    get_current_time_key();

  if (
    s_geometry_state.valid &&
    grect_equal(
      &s_geometry_state.bounds,
      &bounds
    ) &&
    s_geometry_state.time_key ==
      time_key
  ) {
    return true;
  }

  return rebuild_geometry(
    bounds,
    get_current_clock_angles(),
    time_key
  );
}

static bool update_geometry_for_canvas(void) {
  if (!s_canvas_layer) {
    invalidate_geometry();
    return false;
  }

  const uint16_t time_key =
    get_current_time_key();

  return rebuild_geometry(
    layer_get_bounds(s_canvas_layer),
    get_current_clock_angles(),
    time_key
  );
}

/* ------------------------------------------------------------------------- */
/* Drawing                                                                   */
/* ------------------------------------------------------------------------- */

#if DRAW_MINUTE_PIXEL_CORE

static void draw_minute_pixel_core(
    GContext *context,
    uint8_t pivot_index
) {
  if (pivot_index >= CENTERLINE_POINT_COUNT) {
    return;
  }

  graphics_context_set_antialiased(
    context,
    false
  );

  graphics_context_set_stroke_color(
    context,
    GColorWhite
  );

  graphics_context_set_stroke_width(
    context,
    1
  );

  GPoint previous =
    vec2_to_gpoint(
      s_centerline[pivot_index]
    );

  for (
      int index = pivot_index + 1;
      index < CENTERLINE_POINT_COUNT;
      ++index
  ) {
    const GPoint current =
      vec2_to_gpoint(
        s_centerline[index]
      );

    if (!gpoint_equal(&current, &previous)) {
      graphics_draw_line(
        context,
        previous,
        current
      );
    }

    previous =
      current;
  }

  graphics_draw_pixel(
    context,
    previous
  );

  graphics_context_set_antialiased(
    context,
    true
  );
}

#endif

static void canvas_update_proc(
    Layer *layer,
    GContext *context
) {
  const GRect bounds =
    layer_get_bounds(layer);

  graphics_context_set_fill_color(
    context,
    GColorBlack
  );

  graphics_fill_rect(
    context,
    bounds,
    0,
    GCornerNone
  );

  if (
    !ensure_geometry(bounds) ||
    !s_stroke_path
  ) {
    return;
  }

  graphics_context_set_antialiased(
    context,
    true
  );

  graphics_context_set_fill_color(
    context,
    GColorWhite
  );

  gpath_draw_filled(
    context,
    s_stroke_path
  );

#if DRAW_ANTIALIASED_OUTLINE
  graphics_context_set_stroke_color(
    context,
    GColorWhite
  );

  graphics_context_set_stroke_width(
    context,
    1
  );

  gpath_draw_outline(
    context,
    s_stroke_path
  );
#endif

#if DRAW_MINUTE_PIXEL_CORE
  draw_minute_pixel_core(
    context,
    s_geometry_state.pivot_index
  );
#endif
}

/* ------------------------------------------------------------------------- */
/* Time                                                                      */
/* ------------------------------------------------------------------------- */

static bool read_local_time(
    time_t timestamp,
    struct tm *result
) {
  const struct tm *local_time =
    localtime(&timestamp);

  if (!local_time) {
    APP_LOG(
      APP_LOG_LEVEL_ERROR,
      "Failed to obtain local time"
    );

    return false;
  }

  *result =
    *local_time;

  return true;
}

static bool read_current_system_time(void) {
  return read_local_time(
    time(NULL),
    &s_current_time
  );
}

static void time_did_change(void) {
  if (!s_canvas_layer) {
    invalidate_geometry();
    return;
  }

  if (update_geometry_for_canvas()) {
    layer_mark_dirty(
      s_canvas_layer
    );
  }
}

#if ENABLE_DEBUG_TIME

static bool read_adjusted_debug_time(void) {
  const time_t adjusted_timestamp =
    time(NULL) +
    (time_t)s_debug_offset_minutes *
    60;

  return read_local_time(
    adjusted_timestamp,
    &s_current_time
  );
}

static void advance_debug_time(int minutes) {
  s_debug_offset_minutes +=
    minutes;

  if (!read_adjusted_debug_time()) {
    return;
  }

  time_did_change();
}

static void minute_click_handler(
    ClickRecognizerRef recognizer,
    void *context
) {
  (void)recognizer;
  (void)context;

  advance_debug_time(1);
}

static void hour_click_handler(
    ClickRecognizerRef recognizer,
    void *context
) {
  (void)recognizer;
  (void)context;

  advance_debug_time(60);
}

static void click_config_provider(void *context) {
  (void)context;

  window_single_click_subscribe(
    BUTTON_ID_UP,
    minute_click_handler
  );

  window_single_click_subscribe(
    BUTTON_ID_DOWN,
    hour_click_handler
  );
}

#endif

static void tick_handler(
    struct tm *tick_time,
    TimeUnits units_changed
) {
  (void)units_changed;

  if (!tick_time) {
    return;
  }

#if ENABLE_DEBUG_TIME
  if (!read_adjusted_debug_time()) {
    return;
  }
#else
  s_current_time =
    *tick_time;
#endif

  time_did_change();
}

/* ------------------------------------------------------------------------- */
/* Window                                                                    */
/* ------------------------------------------------------------------------- */

static void main_window_load(Window *window) {
  Layer *window_layer =
    window_get_root_layer(window);

  if (!window_layer) {
    APP_LOG(
      APP_LOG_LEVEL_ERROR,
      "Failed to obtain root layer"
    );

    return;
  }

  s_canvas_layer =
    layer_create(
      layer_get_bounds(window_layer)
    );

  if (!s_canvas_layer) {
    APP_LOG(
      APP_LOG_LEVEL_ERROR,
      "Failed to create canvas layer"
    );

    return;
  }

  layer_set_update_proc(
    s_canvas_layer,
    canvas_update_proc
  );

  layer_add_child(
    window_layer,
    s_canvas_layer
  );

  if (update_geometry_for_canvas()) {
    layer_mark_dirty(
      s_canvas_layer
    );
  }
}

static void main_window_unload(Window *window) {
  (void)window;

  if (s_canvas_layer) {
    layer_destroy(
      s_canvas_layer
    );

    s_canvas_layer =
      NULL;
  }

  invalidate_geometry();
}

/* ------------------------------------------------------------------------- */
/* Lifecycle                                                                 */
/* ------------------------------------------------------------------------- */

static bool init(void) {
  s_geometry_state = (GeometryState) {
    .bounds = GRectZero,
    .time_key = 0,
    .pivot_index =
      (uint8_t)(CENTERLINE_POINT_COUNT / 2),
    .valid = false
  };

  s_tick_timer_subscribed =
    false;

#if ENABLE_DEBUG_TIME
  s_debug_offset_minutes =
    0;
#endif

  initialize_solver_workspace();

  if (!read_current_system_time()) {
    s_current_time = (struct tm) {
      .tm_hour = 0,
      .tm_min = 0
    };
  }

  s_stroke_path =
    gpath_create(&s_path_info);

  if (!s_stroke_path) {
    APP_LOG(
      APP_LOG_LEVEL_ERROR,
      "Failed to create stroke path"
    );

    return false;
  }

  s_main_window =
    window_create();

  if (!s_main_window) {
    APP_LOG(
      APP_LOG_LEVEL_ERROR,
      "Failed to create main window"
    );

    return false;
  }

  window_set_background_color(
    s_main_window,
    GColorBlack
  );

#if ENABLE_DEBUG_TIME
  window_set_click_config_provider(
    s_main_window,
    click_config_provider
  );
#endif

  window_set_window_handlers(
    s_main_window,
    (WindowHandlers) {
      .load = main_window_load,
      .unload = main_window_unload
    }
  );

  tick_timer_service_subscribe(
    MINUTE_UNIT,
    tick_handler
  );

  s_tick_timer_subscribed =
    true;

  window_stack_push(
    s_main_window,
    false
  );

  return true;
}

static void deinit(void) {
  if (s_tick_timer_subscribed) {
    tick_timer_service_unsubscribe();

    s_tick_timer_subscribed =
      false;
  }

  if (s_main_window) {
    window_destroy(
      s_main_window
    );

    s_main_window =
      NULL;
  }

  /*
   * Defensive cleanup if initialization or window loading failed
   * before normal ownership teardown completed.
   */
  if (s_canvas_layer) {
    layer_destroy(
      s_canvas_layer
    );

    s_canvas_layer =
      NULL;
  }

  if (s_stroke_path) {
    gpath_destroy(
      s_stroke_path
    );

    s_stroke_path =
      NULL;
  }

  invalidate_geometry();
}

int main(void) {
  if (!init()) {
    deinit();
    return 1;
  }

  app_event_loop();
  deinit();

  return 0;
}