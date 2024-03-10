import { useState, useContext, useEffect } from 'react';
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

const welcomeMessage: MessageModel = {
    direction: "incoming",
    message: "Pitaj u vezi sadržaja kursa",
    position: "normal",
    sender: "Čet.kabinet",
};

export function Chat() {
    const [messages, setMessages] = useState<MessageModel[]>([welcomeMessage]);
    const [isAnswering, setAnswering] = useState(false);
    const [auth, setAuth] = useState("pending");
    const [history, setHistory] = useState<{ q: string; a: string }[]>([]);
    const context = useContext(AppContext);
    const [searchParams] = useSearchParams();
    const [courseKey, setCourseKey] = useState<string>("-");
    const [courseList, setCourseList] = useState<{course_key: string; title: string}[]>([{course_key: '-', title: '---'}]);
    const [lessonKey, setLessonKey] = useState<string>("-");
    const [lessonList, setLessonList] = useState<{key: string; title: string}[]>([{key: '-', title: '---'}]);
    const [activitiyKey, setActivityKey] = useState<string>("-");
    const [activityList, setActivityList] = useState<{key: string; title: string}[]>([{key: '-', title: '---'}]);

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
        console.log(lessons);
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
    }, [activitiyKey]);

    async function postQuestion(question: string, withHistory = true) {
        const bodyJson = {
            "history": withHistory ? history : [],
            "question": question,
            "accessKey": context?.accessKey ?? "default",
            "contextAttributes": {"activity_key": activitiyKey, "course_key": courseKey}
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
        const utf8decoder = new TextDecoder("utf-8");

        const outMessage: MessageModel = {
            direction: "outgoing",
            message: textContent,
            position: "normal",
            sender: "Ja",
        };

        setMessages([...messages, outMessage]);

        const r = await postQuestion(textContent)
        
        var answerText = ""

        const reader = r.body!.getReader()

        while(true) {
            const { done, value } = await reader.read();
            if (done)
                break;
            answerText += utf8decoder.decode(value)
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
            
            const r = await postQuestion("_test", false);
            const testAnswer = await r.text()
            if (testAnswer === "_OK") {
                setAuth("ok");
            }
            else {
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