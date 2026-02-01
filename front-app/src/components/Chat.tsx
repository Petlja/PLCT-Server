import { useState, useContext, useEffect, useRef } from 'react';
import { 
    ChatContainer,
    MainContainer,
    Message,
    MessageInput,
    MessageList,
    MessageModel,
    TypingIndicator,
} from "@chatscope/chat-ui-kit-react";
import "@chatscope/chat-ui-kit-styles/dist/default/styles.min.css";
import { marked } from 'marked';
import Select from 'react-select';
import { AppContext } from "../AppContext";
import  ChatSampleQuestions from "./ChatSampleQuestions";
import { useSearchParams } from 'react-router-dom';
import "./Chat.css";

const welcomeMessage: MessageModel = {
    direction: "incoming",
    message: "Pitaj u vezi sadržaja kursa",
    position: "normal",
    sender: "Čet.kabinet",
};

const defaultQuestions = ["Napravi mi pitanja za test iz ove lekcije.",
                          "Napravi mi domaći zadatak za ovu lekciju.",
                          "Napravi mi plan casa za ovu lekciju.",
                        ];

export function Chat() {
    const [messages, setMessages] = useState<MessageModel[]>([welcomeMessage]);
    const [isAnswering, setAnswering] = useState(false);
    const [auth, setAuth] = useState("pending");
    const [history, setHistory] = useState<{ q: string; a: string }[]>([]);
    const [condensedHistory, setCondensedHistory] = useState<string>("");
    const context = useContext(AppContext);
    const [searchParams] = useSearchParams();
    const [courseKey, setCourseKey] = useState<string>("-");
    const [courseList, setCourseList] = useState<{course_key: string; title: string}[]>([{course_key: '-', title: '---'}]);
    const [lessonKey, setLessonKey] = useState<string>("-");
    const [lessonList, setLessonList] = useState<{key: string; title: string}[]>([{key: '-', title: '---'}]);
    const [activitiyKey, setActivityKey] = useState<string>("-");
    const [activityList, setActivityList] = useState<{key: string; title: string}[]>([{key: '-', title: '---'}]);
    const [model, setModel] = useState<string>("gpt-4o-mini");
    const [questions, setQuestions] = useState<string[]>(defaultQuestions);

    async function handleCourseChange() {
        const r_lessons = await fetch(
            `../api/toc-list`,
            {
                method: 'post',
                body: JSON.stringify({ key: courseKey, item_path: []  }),
                headers: {
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            });
        const lessons = await r_lessons.json();
        setLessonList(lessons);
        if (lessons.length > 0)
            setLessonKey(lessons[0].key)
    }

    useEffect(() => {
        if (courseKey !== "-")
            handleCourseChange();
    }, [courseKey]); 
      
    async function handleLessonChange() {
        const r_activities = await fetch(
            `../api/toc-list`,
            {
                method: 'post',
                body: JSON.stringify({ key: courseKey, item_path: [lessonKey]  }),
                headers: {
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            });
        const activities = await r_activities.json()
        setActivityList(activities)
        if (activities.length > 0)
            await setActivityKey(activities[0].key)
    }

    useEffect(() => {
        if (lessonKey !== "-")
            handleLessonChange();
    }, [lessonKey]); 

    useEffect(() => {
        if(activitiyKey !== "-")
            setMessages([welcomeMessage])
            setHistory([])
            setCondensedHistory("")
            setQuestions(defaultQuestions)
    }, [activitiyKey]);

    async function postQuestion(question: string, withHistory = true) {
        const bodyJson = {
            "history": withHistory ? history : [],
            "question": question,
            "accessKey": context?.accessKey ?? "default",
            "condensedHistory": condensedHistory,
            "contextAttributes": {"activity_key": activitiyKey, "course_key": courseKey},
            "model": model
        };
        const r = await fetch(
            "../api/chat",
            {
                method: 'POST',
                body: JSON.stringify(bodyJson),
                headers: {
                    "Accept": "application/json",
                    "Content-Type": "application/json"
                }
            });
        return r;
    }

    async function handleSend(
        textContent: string
    ) {
        setAnswering(true);
        setQuestions([]);
        const utf8decoder = new TextDecoder("utf-8");

        const outMessage: MessageModel = {
            direction: "outgoing",
            message: textContent,
            position: "normal",
            sender: "Ja",
        };

        setMessages([...messages, outMessage]);

        const r = await postQuestion(textContent);
        var hasInitialData = false;   
        var answerText = "";

        const reader = r.body!.getReader()

        while(true) {
            const { done, value } = await reader.read();
            if (done)
                break;

            const chunkText = utf8decoder.decode(value);
            if (!hasInitialData) {
                const metadataEndIndex = chunkText.indexOf('\n');
                if (metadataEndIndex !== -1) {
                        const jsonText = chunkText.slice(0, metadataEndIndex);
                        const metadata = JSON.parse(jsonText);

                        let condensedHistory = metadata.condensed_history;
                        let followupQuestions = metadata.followup_questions;

                        if (condensedHistory !== "")
                            setCondensedHistory(condensedHistory ? condensedHistory : "");

                        if (followupQuestions) {
                                setQuestions(followupQuestions); 
                        }
                        else{
                            setQuestions([]);
                        }
                
                        hasInitialData = true;
                        answerText += chunkText.slice(metadataEndIndex + 1);
                }
                else{
                    answerText += chunkText;
                }
            } else {
                answerText += chunkText;
            }

            const answerHtml = marked.parse(answerText)
            const inMessage: MessageModel = {
                direction: "incoming",
                message: "<div class='answer-wrapper'>" + answerHtml + "</div>",
                position: "normal",
                sender: "Čet.kabinet",
            };
            setMessages([...messages, outMessage, inMessage]);

        };

        setHistory([...history, { q: textContent, a: answerText }]);
        setAnswering(false);
    }

    const handleQuestionClick = async (question: string) => {
        await handleSend(question);
      };
      

    useEffect(() => {
        async function init() {
            const r_courses = await fetch(
                "../api/courses",
                {
                    method: 'GET',
                    headers: {
                        "Accept": "application/json"
                    }
                });
            const courses = await r_courses.json()
            setCourseList(courses);
            if (courses.length > 0)
                setCourseKey(courses[0].course_key)
            
            const statusResponse = await fetch("../api/chat", {
                method: 'GET'
            });

            if (statusResponse.status === 200) {
                setAuth("ok");
            } else {
                setAuth("fail");
            }
        }
        init();
    }, []);

    if (auth === "ok") {
        return (
             <div>
                <h2>Izaberi kurs i lekciju, pa postavi pitanje</h2>
                <p>Pitanja koje postaviš i dati odgovori ostaju sačuvani u bazi radi unapređivanja rešenja. U pitanjima nemoj unositi lične niti bilo koje druge osetljive podatke.</p>
                <select className="form-select" value={courseKey} onChange={(e) => setCourseKey(e.target.value)}>
                    {courseList.map((c, i) => <option key={i} value={c.course_key}>{c.title}</option>)}
                </select>
                <br />
                <select className="form-select" value={lessonKey} onChange={(e) => setLessonKey(e.target.value)}>
                    {lessonList.map((c, i) => <option key={i} value={c.key}>{c.title}</option>)}
                </select>
                <br />
                <select className="form-select" value={activitiyKey} onChange={(e) => setActivityKey(e.target.value)}>
                    {activityList.map((c, i) => <option key={i} value={c.key}>{c.title}</option>)}
                </select>
                <br />
                <select className="form-select" value={model} onChange={(e) => setModel(e.target.value)}>
                    <option value="gpt-4o">gpt-4o</option>
                    <option value="gpt-4o-mini">gpt-4o-mini</option>
                    <option value="meta-llama/Meta-Llama-3.1-70B">llama-3.1-70b</option>
                    <option value="nvidia/Llama-3.3-70B-Instruct-FP8">llama-3.3-70B-FP8</option>
                    <option value="Qwen/Qwen3-32B">qwen3-32b</option>
                    <option value="Qwen/Qwen3-14B">qwen3-14b</option>
                    <option value="Qwen/Qwen3-8B">qwen3-8b</option>

                    
                 </select>
                <br />
                <MainContainer responsive>
                    <ChatContainer>
                        <MessageList
                            typingIndicator={
                                isAnswering && <TypingIndicator  />
                            }
                        >
                            {messages.map((v, i) => (
                                <Message model={v} key={i} />
                            ))}
                        </MessageList>
                        <MessageInput
                            placeholder={isAnswering ? "Sačekaj odgovor na postavljeno pitanje" : "Ovde unesi pitanje"}
                            attachButton={false}
                            onSend={handleSend}
                            disabled={isAnswering}
                            autoFocus={true}
                            activateAfterChange={true}
                        />
                    </ChatContainer>
                </MainContainer>
                <br />
                <div className="follow-up-questions">
                {questions.map((question, index) => (
                        <p key={index} onClick={() => handleQuestionClick(question)}>
                            {question}
                        </p>
                    ))}
                </div>
            </div>

        );
    }
    else if (auth === "fail") {
        return (
            <div>
                <h1>Pristup ovom delu aplikacije nije omogućen</h1>
            </div>
        );
    } else {
        return (
            <div>
                <h1>Sačekaj...</h1>
            </div>
        );
    }
}