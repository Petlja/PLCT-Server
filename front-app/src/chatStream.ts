export type DebugEvent = {
    type: "debug";
    level: string;
    source: string;
    message: string;
    elapsed: number;
};

export type ChatEvent =
    | { type: "progress"; stage: string; message: string; detail?: string }
    | { type: "content"; text: string }
    | DebugEvent
    | { type: "error"; message: string }
    | { type: "done"; model: string };

export async function readChatEvents(
    response: Response,
    handleEvent: (event: ChatEvent) => void,
) {
    if (!response.ok)
        throw new Error(`Chat request failed: ${response.status}`);
    if (!response.body)
        throw new Error("Chat response has no body");

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
        const { done, value } = await reader.read();
        if (done) {
            buffer += decoder.decode();
            break;
        }

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
            if (line.trim())
                handleEvent(JSON.parse(line) as ChatEvent);
        }
    }

    if (buffer.trim())
        handleEvent(JSON.parse(buffer) as ChatEvent);
}