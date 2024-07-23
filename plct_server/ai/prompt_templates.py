preprocess_system_message_template = (
    "Consider the context of the folowing course and lesson.\n\n"
    "Here is the course summery delimited by triple quotes:\n\n"
    "'''\n"
    "{course_summary}\n"
    "'''\n\n"
    "Here is the lesson summery delimited by triple quotes:\n"
    "'''\n\n"
    "{lesson_summary}\n"
    "'''\n\n"
    "Allways answer in the language of the question.\n\n"
)

preprocess_system_message_template_x1 = (
    "Consider the question in the context of a course summarized below delimited by tripple quotes:\n\n"
    "'''\n"
    "{course_summary}\n"
    "'''\n\n"

)

preprocess_user_message_template = (
    "Help me to elaborate the folowing request in more detail:\n\n{user_input}")

system_message_template = (
    #"Keep in the context of learning to code in Python.\n\n"
    "Format output with Markdown.\n\n"
    #"Avoid Python builtin functions sum, min, and max.\n\n"
    "When appropriate, provide example of code with explanation.\n\n"
    "If you are not sure, answer that you are not sure and that you can't help.\n\n"
    #"Never answer outside of the Python context.\n\n"
    "Answer in the Serbian language by default, using the same script as in the question (Latin or Cyrillic). When the question is in English, answer in English.\n\n"
)

system_message_summay_template = (
    "Consider the question in the context of the folowing course and lesson.\n\n"
    "Here is the course summary delimited by triple quotes:\n\n"
    "'''\n"
    "{course_summary}\n"
    "'''\n\n"
    "Here is the lesson summary delimited by triple quotes:\n"
    "'''\n\n"
    "{lesson_summary}\n"
    "'''\n\n"
)

system_message_rag_template = (
    "If the question is out of the scope of the above course and lesson, also consider the following.\n\n"
    "{chunks}\n\n"
)

compare_prompt =(
    "Compare these two texts:\n\n"
    "```\n"
    "{current_text}\n"
    "```\n\n"
    "```\n"
    "{benchmark_text}\n"
    "```\n\n"
    "Return your assessment of similarity as an integer on a scale from 0 to 5, where 0 means completely different and 5 means exactly the same.\n\n"
)