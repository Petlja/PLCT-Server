"""The course contents, as the system message carries them."""

from ...knowledge.course_db import CourseDB


def render_course_map(db: CourseDB, course_key: str, *,
                      current: str | None = None) -> str:
    """The course as the answering model sees it: titles and position of the teacher."""
    lessons = db.lessons(course_key)
    if not lessons:
        return f"no such course: {course_key}"

    here_lesson, here_activity = (db.locate(course_key, current) if current
                                  else (None, None))

    out = [f"Course: {db.course_title(course_key)}",
           f"{len(lessons)} lessons, "
           f"{sum(len(lesson.activities) for lesson in lessons)} activities."]
    if here_lesson is not None and here_activity is not None:
        out.append(f"The teacher is on {here_activity.title}, "
                   f"in lesson {here_lesson.title}.")
    out.append('A lesson marked "activities not listed" is collapsed here, not empty.')
    out.append("")

    for lesson in lessons:
        here = lesson is here_lesson
        tags = [f"{len(lesson.activities)} activities",
                "current lesson" if here else "activities not listed"]
        out.append(f"{lesson.title} ({', '.join(tags)})")
        if not here:
            continue
        for activity in lesson.activities:
            mark = " (current activity)" if activity is here_activity else ""
            out.append(f"    {activity.title}{mark}")
    return "\n".join(out)
