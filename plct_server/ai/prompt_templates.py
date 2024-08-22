preprocess_system_message_template_with_history = (
    "Consider the context of the following course, lesson and summary of previous user questions and assistant explanations.\n\n"
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
    "'''\n\n"
    "Always answer in the language of the question.\n\n"
)
preprocess_system_message_template = (
    "Consider the context of the following course, lesson and summary of previous user questions and assistant explanations.\n\n"
    "Here is the course summery delimited by triple quotes:\n\n"
    "'''\n"
    "{course_summary}\n"
    "'''\n\n"
    "Here is the lesson summery delimited by triple quotes:\n"
    "'''\n\n"
    "{lesson_summary}\n"
    "'''\n\n"
    "Always answer in the language of the question.\n\n"
)

preprocess_user_message_template = (
    "Help me to elaborate the following request in more detail:\n\n{user_input}")

system_message_template = (
    "Format output with Markdown.\n\n"
    "When appropriate, provide example of code with explanation.\n\n"
    "If you are not sure, answer that you are not sure and that you can't help.\n\n"
    "Answer in the Serbian language by default, using the same script as in the question (Latin or Cyrillic). When the question is in English, answer in English.\n\n"
)

system_message_summary_template = (
    "Consider the question in the context of the following course and lesson.\n\n"
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

system_compare_template = (
    "Your answer should be a number representing the similarity score, where 0 means the information is completely different and 5 means the information is very similar.\n\n"
    "Give no additional information, just the number.\n\n"
)

compare_prompt = (
    "Here are the two answers delimited by triple quotes.\n\n"
    "'''\n"
    "Answers 1:\n"
    "{current_text}\n"
    "'''\n\n"
    "Answers 2:\n"
    "'''\n"
    "{benchmark_text}\n"
    "'''\n\n"
)

system_message_condensed_history_template = (
    "Here is the summary of previous user questions and assistant explanations delimited by triple quotes \n\n"
    "'''\n"
    "{condensed_history}\n"
    "'''\n\n"
)

condensed_history_system = (
    "You are an AI assistant. Your task is to help summarize conversations between the user and the assistant.\n"
    "You are either asked to provide a summary of the conversation or to provide a new summary based on the previous summary and the latest question and answer.\n"
)

condensed_history_template = (
    "Summarize the conversation between the user and the assistant.\n"
    "Here is the condensed history delimited by triple quotes:\n"
    "'''\n"
    "{condensed_history}\n"
    "''''\n"
    "Latest conversation includes this user question delimited by triple quotes:\n"
    "'''\n"
    "{latest_user_question}.\n"
    "'''\n"
    "Assistant explained delimited by triple quotes:\n"
    "'''\n"
    "{latest_assistant_explanation}.\n"
    "'''\n"
)

new_condensed_history_template = (
    "Summarize the conversation between the user and the assistant.\n"
    "User question delimited by triple quotes:\n "
    "'''\n"
    "{previous_user_question_1}\n"
    "'''\n"
    "Assistant explained delimited by triple quotes:\n"
    "'''\n"
    "{previous_assistant_explanation_1}\n"
    "'''\n"
    "User question delimited by triple quotes:"
    "'''\n"
    "{previous_user_question_2}\n"
    "'''\n"
    "Assistant explained delimited by triple quotes:"
    "'''\n"
    "{previous_assistant_explanation_2}\n"
    "'''\n"
)
