preprocess_system_message_template = (
    "Consider the context of the folowing course, lesson and summary of previous user questions and assistant explanations.\n\n"
    "Here is the course summery delimited by triple quotes:\n\n"
    "'''\n"
    "{course_summary}\n"
    "'''\n\n"
    "Here is the lesson summery delimited by triple quotes:\n"
    "'''\n\n"
    "{lesson_summary}\n"
    "'''\n\n"
    "Here is the summary of previous user questions and assistant explanations delimited by triple quotes: \n"
    "'''\n\n"
    "{condensed_history}\n"
    "```\n\n"
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

system_message_summary_template = (
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

compare_prompt = (
    "```\n"
    "Answers 1:\n"
    "{current_text}\n"
    "```\n\n"
    "Answers 2:\n"
    "```\n"
    "{benchmark_text}\n"
    "```\n\n"
)
system_message_condensed_history_template = (
    "Here is the summary of previous user questions and assistant explanations delimited by triple quotes \n\n"
    "```\n"
    "{condensed_history}"
    "'''\n\n"
)


system_compare_template = (
    "Your answer should be a number representing the similarity score, where 0 means the information is completely different and 5 means the information is very similar.\n\n"
    "Give no additional information, just the number.\n\n"
    )

condensed_history_template = (
    "User and Assistant have discussed various topics. This is the summary: {condensed_history}\n"
    "Latest conversation includes this user question: {latest_user_question}.\n"
    "Assistant explained: {latest_assistant_explanation}.\n"
    "Provide me a new summary based on the previous summary and the latest question and answer in the language of the latest question."
)

new_condensed_history_template = (
    "Here are two previous interactions with the assistant.\n"
    "User question: {previous_user_question_1}\n"
    "Assistant explained: {previous_assistant_explanation_1}\n"
    "User question: {previous_user_question_2}\n"
    "Assistant explained: {previous_assistant_explanation_2}\n"
    "Provide me a summary based on previous questions and explanations in the language of the latest question."
)

no_condensed_history_template = (
    "This is the first interaction in this conversation, there is no condensed history\n"
)