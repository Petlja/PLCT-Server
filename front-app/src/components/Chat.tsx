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

const welcomeMessage: MessageModel = {
    direction: "incoming",
    message: "Pitaj šta želiš o programiranju u Pajtonu",
    position: "normal",
    sender: "Čet.kabinet",
};

interface OptionType {
    label: string;
    value: string;
}

export function Chat() {
    const [messages, setMessages] = useState<MessageModel[]>([welcomeMessage]);
    const [isAnswering, setAnswering] = useState(false);
    const [auth, setAuth] = useState("pending");
    const [history, setHistory] = useState<{ q: string; a: string }[]>([]);
    const [selectedOption, setSelectedOption] = useState<OptionType | null>(null);
    const context = useContext(AppContext);

    const options: OptionType[] = ChatSampleQuestions.map((l, i) => ({ label: l, value: i.toString() }));

    async function handleOptionChange(selectedOption: OptionType | null) {
        if (selectedOption) {
            await handleSend(selectedOption.label);
        }
        setSelectedOption(null);
    }

    async function postQuestion(question: string, withHistory = true) {
        const bodyJson = {
            "history": withHistory ? history : [],
            "question": question,
            "accessKey": context?.accessKey ?? "default"
        };
        const r = await fetch(
            "../api/chat",
            {
                method: 'POST',
                body: JSON.stringify(bodyJson),
                headers: {
                    Accept: "application/json",
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

        const r = await postQuestion(textContent);

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
        async function testAuth() {
            const r = await postQuestion("_test", false);
            const testAnswer = await r.text()
            if (testAnswer === "_OK") {
                setAuth("ok");
            }
            else {
                setAuth("fail");
            }
        }
        testAuth();
    }, []);

    if (auth === "ok") {
        return (
             <div>
                <h1>Programiranje u Pajtonu (gpt-4)</h1>
                <p>Pitanja koje postaviš i dati odgovori ostaju sačuvani u bazi radi unapređivanja rešenja. U pitanjima nemoj unositi lične niti bilo koje druge osetljive podatke.</p>
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
                <Select
                    options={options}
                    value={selectedOption}
                    onChange={handleOptionChange}
                    placeholder="Možeš pregledati i izabrati neke primere pitanja..."
                    isDisabled={isAnswering}

                />
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